from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import pytest
import jsonschema
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = REPO_ROOT / "roles/benchmarking/files/run_benchmark.py"
SCHEMA_PATH = REPO_ROOT / "schemas/benchmark.schema.json"


def load_yaml(relpath: str) -> object:
    return yaml.safe_load((REPO_ROOT / relpath).read_text(encoding="utf-8"))


def load_harness():
    spec = importlib.util.spec_from_file_location("run_benchmark", HARNESS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_benchmark_harness_script_exists():
    assert HARNESS_PATH.exists()


def test_benchmark_defaults_contain_five_profiles():
    defaults = load_yaml("roles/benchmarking/defaults/main.yml")
    profiles = defaults["benchmarking_profiles"]
    expected_profiles = {"small", "medium_32b", "large_70b", "low_precision_moe", "sustained_load"}
    assert expected_profiles <= set(profiles.keys())


def test_harness_generates_schema_valid_result(tmp_path):
    mod = load_harness()
    schema = load_schema()

    doc = mod.build_benchmark_document(
        profile_name="small",
        hostname="ai-p620-01",
        git_sha="0123456789abcdef0123456789abcdef01234567",
        simulated=True,
        model_id="Qwen/Qwen2.5-Coder-7B-Instruct",
        revision="main",
        artifact_sha256="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        quantization="FP16",
        gpu_count=1,
        tensor_parallelism=1,
        context_window_tokens=4096,
        duration_seconds=30.0,
        status="PASS",
    )

    jsonschema.validate(instance=doc, schema=schema)
    assert doc["status"] == "SIMULATED_PASS"
    assert doc["simulated"] is True
    assert "not physical acceptance evidence" in doc["correctness"]["summary"].lower()
    assert doc["execution"]["gpu_count"] == 1


def test_playbook_benchmark_structure():
    content = (REPO_ROOT / "playbooks/benchmark.yml").read_text()
    assert "benchmark" in content
    assert "benchmarking" in content


def test_power_budget_refusal_math():
    mod = load_harness()
    ok = mod.evaluate_power_budget(2, 225, 1000, 250, 20.0)
    assert ok["status"] == "ok" and ok["limit_watts"] == 800.0
    refused = mod.evaluate_power_budget(2, 300, 750, 200, 10.0)
    assert refused["status"] == "refused"
    assert refused["estimated_watts"] > refused["limit_watts"]


def test_real_mode_fails_honestly_without_server(tmp_path):
    import subprocess
    import sys as _sys

    out = tmp_path / "bench.json"
    result = subprocess.run(
        [
            _sys.executable, str(HARNESS_PATH),
            "--mode", "real", "--runtime", "vllm", "--model", "test/model",
            "--base-url", "http://127.0.0.1:1",
            "--iterations", "1", "--duration", "2",
            "--output", str(out),
        ],
        capture_output=True, text=True, timeout=60,
        env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode != 0
    doc = json.loads(out.read_text())
    jsonschema.validate(instance=doc, schema=load_schema())
    assert doc["simulated"] is False
    # Nothing was measured, so the honest state is NOT_RUN with unavailable
    # telemetry - never a fabricated FAIL or PASS.
    assert doc["status"] == "NOT_RUN"
    assert doc["failure_criteria"] == []
    for metric in doc["telemetry"].values():
        assert metric["observed"]["status"] == "unavailable"


def test_thermal_abort_marks_failure_criterion():
    mod = load_harness()
    safety = {
        "mode": "real", "runtime": "vllm",
        "guardrails": {
            "psu_capacity_watts": 1000, "gpu_tdp_watts_per_gpu": 225,
            "system_base_power_watts": 250, "power_headroom_pct": 20.0,
            "abort_temperature_c": 90,
        },
        "power_budget": {"status": "ok", "estimated_watts": 700.0, "limit_watts": 800.0},
        "thermal_abort_triggered": True,
        "telemetry_source": "hwmon", "peak_gpu_temperature_c": 91.2,
    }
    doc = mod.build_benchmark_document(status="FAIL", mode="real", runtime="vllm", safety=safety)
    criteria = [c["criterion"] for c in doc["failure_criteria"]]
    assert "thermal_abort" in criteria
    assert doc["safety"]["thermal_abort_triggered"] is True


def test_sampler_records_unavailable_without_hwmon():
    mod = load_harness()
    sampler = mod.TelemetrySampler(interval_sec=0.01)
    sampler.sample_once()
    # On CI hosts without GPU hwmon the source is honestly unavailable.
    if not mod.discover_gpu_hwmons():
        assert sampler.telemetry_source == "unavailable"
        assert sampler.max_temperature() is None


def test_stream_parser_reports_connection_failure_not_pass():
    mod = load_harness()
    result = mod.stream_vllm_completion(
        base_url="http://127.0.0.1:1", api_key=None, model="m",
        prompt="p", max_new_tokens=8, timeout_sec=5,
    )
    assert result["status"] == "error"
    assert "tokens_per_second" not in result


def test_system_provenance_is_never_fabricated():
    mod = load_harness()
    source = HARNESS_PATH.read_text()
    for literal in ("M34KT39A", "6.8.0-40-generic", "26.27.39122.11", "b374829a"):
        assert literal not in source, f"harness still hard-codes {literal}"
    prov = mod._live_system_provenance("test-host")
    import re
    assert re.match(r"^\d+\.\d+\.\d+", prov["kernel_version"])
    for value in prov.values():
        assert isinstance(value, str) and len(value) > 0
