from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest
from jsonschema import Draft202012Validator, FormatChecker
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = REPO_ROOT / "roles/benchmarking/files/run_benchmark.py"
SCHEMA_DIR = REPO_ROOT / "schemas"
VALIDATE_SCRIPT = REPO_ROOT / "scripts/validate_contract.py"
RUN_ID = "20260923T000000Z-abcd1234"


def load_harness():
    spec = importlib.util.spec_from_file_location("run_benchmark", HARNESS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_yaml(relpath: str):
    return yaml.safe_load((REPO_ROOT / relpath).read_text(encoding="utf-8"))


def load_validate_contract():
    spec = importlib.util.spec_from_file_location("validate_contract", VALIDATE_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def validate(schema_name: str, doc: dict) -> list[str]:
    validator = Draft202012Validator(load_schema(schema_name), format_checker=FormatChecker())
    return sorted(validator.iter_errors(doc), key=lambda error: list(error.absolute_path))  # type: ignore[no-any-return]


def base_args(mod, **overrides) -> argparse.Namespace:
    kwargs = {
        "profile": "small",
        "hostname": "ai-5820-01",
        "git_sha": "0123456789abcdef0123456789abcdef01234567",
        "runtime": "vllm",
        "base_url": "http://127.0.0.1:1",
        "auth_env_file": None,
        "api_key_env": "VLLM_API_KEY",
        "model": "cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
        "revision": "main",
        "artifact_sha256": "0" * 64,
        "quantization": "AWQ-4bit",
        "prompt": "Write a short sentence about efficient inference.",
        "max_new_tokens": 32,
        "iterations": 1,
        "duration": 2.0,
        "request_timeout": 5.0,
        "tensor_parallelism": 1,
        "context_window_tokens": 4096,
        "gpu_count": 1,
        "psu_capacity_watts": 1000.0,
        "gpu_tdp_watts": 225.0,
        "system_base_power_watts": 250.0,
        "power_headroom_pct": 20.0,
        "abort_temperature_c": 90.0,
        "run_id": RUN_ID,
        "baseline_id": "B0",
        "config_id": "b0",
        "git_dirty": False,
        "generated_at": "2026-09-23T00:00:00Z",
        "prompt_class": "short",
        "output_class": "short",
        "concurrency": 1,
        "requests": 1,
        "warmup_requests": 0,
        "max_deviation_pct": 5.0,
        "correctness_sentinel": False,
        "service_unit": "vllm.service",
        "container_name": "vllm-xpu",
    }
    kwargs.update(overrides)
    return argparse.Namespace(**kwargs)


def full_identity(mod) -> dict:
    return {
        "boot_id": "ae00235f-d992-4926-b6cd-5f3c60396aca",
        "systemd_invocation_id": "d279b0c9757240ac8b89695cbde627a6",
        "systemd_nrestarts": 0,
        "systemd_active_state": "active",
        "container_id": "1ede1ad090a9",
        "image_ref": "localhost/vllm-openai-xpu:v0.9.1",
        "image_digest": "sha256:4bdfd5b928b4a6a95c92b1edc861f13587a797a32db8c1bc96ca4e2c0d58629d",
        "model_observed": ["cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit"],
        "model_expected": "cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
        "gpu_identity": [
            {"gpu_index": 0, "card": "card1", "pci_address": "0000:51:00.0",
             "driver": "xe", "vendor": "8086", "device": "e222", "hwmon": "hwmon4"},
            {"gpu_index": 1, "card": "card2", "pci_address": "0000:93:00.0",
             "driver": "xe", "vendor": "8086", "device": "e222", "hwmon": "hwmon5"},
        ],
        "service_unit": "vllm.service",
        "api_key_configured": True,
    }


def measured_record(i: int, *, warmup: bool = False, ttft_ms: float = 40.0) -> dict:
    return {
        "status": "ok",
        "sample_class": "warmup" if warmup else "measured",
        "http_status": 200,
        "ttft_ms": ttft_ms,
        "completion_tokens": 128,
        "prompt_tokens": 4102,
        "generation_seconds": 3.2,
        "elapsed_seconds": 3.4,
        "generation_tokens_per_second": 40.0,
        "finish_reason": "stop",
        "request_id": f"req-{i:04d}",
        "inter_token_latency_ms": [30.0, 28.0, 31.0],
    }


# --------------------------------------------------------------------------- A

def test_real_pass_run_card_validates_against_schema():
    mod = load_harness()
    doc = mod.build_benchmark_document(
        profile_name="small", hostname="ai-5820-01",
        git_sha="0123456789abcdef0123456789abcdef01234567",
        simulated=False, model_id="cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
        revision="main", quantization="AWQ-4bit", gpu_count=2, tensor_parallelism=2,
        context_window_tokens=4096, duration_seconds=30.0, status="PASS", mode="real",
        runtime="vllm", benchmark_run_id=RUN_ID, baseline_id="B0", config_id="b0",
        identity=full_identity(mod),
        workload=mod.build_workload_document(
            RUN_ID, {"observed_tokens": 4102, "deviation_tokens": 6, "deviation_pct": 0.1,
                     "token_source": "server_tokenize", "tokenize_endpoint": "/tokenize",
                     "prompt_text": "// b0 workload block\n" * 40},
            "medium", "short", 512, 1, 20, 5, 5.0, "cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
            profile="small"),
        safety=mod.default_safety_block("real", "vllm"),
        metrics={"generation_tokens_per_second": 42.1, "ttft_ms": 35.8},
        validity={"state": "VALID", "reasons": [], "interrupted": False},
    )
    errors = validate("benchmark", doc)
    assert not errors, [f"{e.message} @ {list(e.absolute_path)}" for e in errors]
    assert doc["status"] == "PASS"
    assert doc["identity"] is not None and doc["workload"] is not None


def test_component_documents_validate_against_component_schemas():
    mod = load_harness()
    identity = full_identity(mod)
    system = {"hostname": "ai-5820-01", "bios_version": "S0KT99A",
              "kernel_version": "6.12.0-amd64", "intel_runtime_version": "1.5.1",
              "level_zero_version": "1.19.0", "pytorch_version": "2.8.0+xpu",
              "vllm_version": "0.9.1", "llama_commit": "abc1234def5678"}
    prompt = {"observed_tokens": 4102, "deviation_tokens": 6, "deviation_pct": 0.1,
              "token_source": "server_tokenize", "tokenize_endpoint": "/tokenize",
              "prompt_text": "// b0 workload block\n" * 40}
    pairs = [
        ("benchmark-environment", mod.build_environment_document(RUN_ID, identity, "ai-5820-01", system)),
        ("benchmark-workload", mod.build_workload_document(
            RUN_ID, prompt, "medium", "short", 512, 1, 20, 5, 5.0,
            "cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit", profile="small")),
        ("benchmark-metrics", mod.build_metrics_document(RUN_ID, [measured_record(0)])),
        ("benchmark-validity", mod.build_validity_document(RUN_ID, {"state": "VALID", "reasons": []})),
    ]
    for name, doc in pairs:
        errors = validate(name, doc)
        assert not errors, f"{name}: {[e.message for e in errors]}"


# --------------------------------------------------------------------------- B

def test_cli_real_mode_requires_model_attribute():
    result = subprocess.run(
        [sys.executable, str(HARNESS_PATH), "--mode", "real",
         "--base-url", "http://127.0.0.1:1", "--output", "/tmp/never-written.json"],
        capture_output=True, text=True, timeout=30, env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 2
    assert "--model is required" in result.stderr


def test_playbook_and_inventory_wire_b0_identity():
    tasks = load_yaml("roles/benchmarking/tasks/main.yml")
    run = next(task for task in tasks if task.get("name") == "Run inference benchmark harness")
    argv = str(run["ansible.builtin.command"]["argv"])
    for flag in ("--model", "--baseline-id", "--config-id", "--service-unit",
                 "--prompt-class", "--output-class", "--concurrency", "--requests",
                 "--warmup-requests", "--max-deviation-pct", "--evidence-dir"):
        assert flag in argv, f"playbook must pass {flag}"
    defaults = load_yaml("roles/benchmarking/defaults/main.yml")
    assert defaults["benchmarking_baseline_id"] == "B0"
    assert defaults["benchmarking_model"] == "cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit"
    production = load_yaml("inventory/production/host_vars/ai-5820-01.yml")
    lab = load_yaml("inventory/lab/host_vars/ai-5820-test-01.yml")
    for host_vars in (production, lab):
        assert host_vars["benchmarking_baseline_id"] == "B0"
        assert host_vars["benchmarking_model"] == defaults["benchmarking_model"]
        assert host_vars["benchmarking_quantization"] == "AWQ-4bit"
    assert production["benchmarking_service_unit"] == "vllm.service"


def test_b0_matrix_file_is_self_consistent():
    matrix = json.loads((REPO_ROOT / "roles/benchmarking/files/b0-matrix.json").read_text())
    points = matrix["load_points"]
    assert [p["id"] for p in points] == matrix["matrix"]["order"]
    assert len(points) == 11
    expected_classes = {"short", "medium", "large", "very_large", "max_near_window"}
    for point in points:
        assert point["prompt_class"] in expected_classes
        assert point["prompt_tokens"] + point["output_tokens"] <= 65536
        assert point["concurrency"] >= 1 and point["requests"] >= 1
    identity = matrix["matrix"]["frozen_identity"]
    assert identity["model"] == "cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit"
    assert identity["tensor_parallel_size"] == 2
    assert identity["max_model_len"] == 65536
    assert matrix["matrix"]["global_stop_conditions"]
    assert matrix["matrix"]["elimination_rule"]["code"] == "DEVICE_ERROR_BUDGET_EXCEEDED"
    assert "throughput floor" not in matrix["matrix"]["elimination_rule"]["condition"]


@pytest.mark.parametrize("throughput", [0.5, 1.0, 4.0, 8.0])
def test_low_throughput_is_valid_and_not_evaluated(throughput):
    mod = load_harness()
    validity = mod.compute_validity("PASS", [])
    doc = mod.build_benchmark_document(
        status="PASS", mode="real", runtime="vllm", validity=validity,
        benchmark_run_id=RUN_ID, identity=full_identity(mod),
        workload={"workload_id": "b0-medium-short-c1"},
        metrics={"generation_tokens_per_second": throughput},
    )
    assert doc["validity"]["state"] == "VALID"
    assert doc["validity"]["performance_assessment"] == "NOT_EVALUATED"
    assert doc["telemetry"]["generation_tokens_per_second"]["observed"]["value"] == throughput


def test_validity_rejects_performance_failure_reason():
    validate_contract = load_validate_contract()
    payload = {
        "status": "PASS", "simulated": False, "identity": {}, "workload": {},
        "failure_criteria": [],
        "validity": {"state": "VALID", "reasons": [
            {"code": "LOW_THROUGHPUT", "detail": "below reference"}
        ]},
    }
    errors = validate_contract.validate_benchmark_payload(payload)
    assert any("performance observation" in error for error in errors)


# --------------------------------------------------------------------------- C

def test_sampler_fails_closed_without_hwmon():
    mod = load_harness()
    sampler = mod.TelemetrySampler(interval_sec=0.01)
    sampler.sample_once()
    if not mod.discover_gpu_hwmons():
        assert sampler.telemetry_source == "unavailable"
        assert sampler.max_temperature() is None
        assert sampler.required_sensor_present is False


def test_real_run_without_server_is_not_run_not_fabrication():
    mod = load_harness()
    args = base_args(mod, requests=1, concurrency=1, warmup_requests=0)
    doc, records, metrics_doc = mod.run_real_benchmark(args)
    assert doc["status"] == "NOT_RUN"
    assert doc["simulated"] is False
    assert doc["failure_criteria"] == []
    assert doc["validity"]["state"] == "INVALID"
    codes = {r["code"] for r in doc["validity"]["reasons"]}
    assert "SERVICE_UNREACHABLE" in codes
    assert metrics_doc["counts"]["failed"] > 0
    assert any(r.get("status") != "ok" for r in records)


# --------------------------------------------------------------------------- D

def test_metrics_distributions_include_percentiles_and_itl():
    mod = load_harness()
    records = [measured_record(0, ttft_ms=35.0), measured_record(1, ttft_ms=40.0),
               measured_record(2, ttft_ms=39.0), measured_record(3, warmup=True)]
    metrics = mod.build_metrics_document(RUN_ID, records)
    dist = metrics["distributions"]
    for key in ("ttft_ms", "inter_token_latency_ms", "end_to_end_ms", "decode_tokens_per_second"):
        for pct in ("p50", "p95", "p99"):
            assert dist[key][pct] is not None, f"{key}.{pct} missing"
    assert metrics["counts"]["measured"] == 3
    assert metrics["counts"]["warmup"] == 1


# --------------------------------------------------------------------------- E

def test_prefill_never_reported_as_derived():
    mod = load_harness()
    metrics = mod.build_metrics_document(RUN_ID, [measured_record(0)])
    assert metrics["prefill"]["classification"] == "UNSUPPORTED"
    assert metrics["prefill"]["tokens_per_second"] is None
    assert "never" in metrics["prefill"]["reason"].lower()
    assert not validate("benchmark-metrics", metrics)


def test_workload_classes_span_context_window():
    mod = load_harness()
    window = 65536
    for prompt_class in ("short", "medium", "large", "very_large", "max_near_window"):
        target = mod.PROMPT_CLASSES[prompt_class]
        assert target >= 1024 and target < window
    assert set(mod.OUTPUT_CLASSES) == {"tiny", "short", "medium", "large"}


def test_concurrency_bounds_enforced():
    result = subprocess.run(
        [sys.executable, str(HARNESS_PATH), "--mode", "real", "--model", "m",
         "--base-url", "http://127.0.0.1:1", "--concurrency", "0"],
        capture_output=True, text=True, timeout=30, env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 2
    assert "--concurrency must be at least 1" in result.stderr


# --------------------------------------------------------------------------- F

def test_environment_document_binds_identity_chain():
    mod = load_harness()
    identity = full_identity(mod)
    system = {"hostname": "ai-5820-01", "bios_version": "S0KT99A",
              "kernel_version": "6.12.0-amd64", "vllm_version": "0.9.1"}
    env = mod.build_environment_document(RUN_ID, identity, "ai-5820-01", system)
    ident = env["identity"]
    assert ident["boot_id"] == "ae00235f-d992-4926-b6cd-5f3c60396aca"
    assert ident["systemd_invocation_id"] == "d279b0c9757240ac8b89695cbde627a6"
    assert ident["container_id"] == "1ede1ad090a9"
    assert ident["image_digest"].startswith("sha256:")
    assert ident["service"]["unit"] == "vllm.service"
    assert ident["service"]["active_state"] == "active"
    assert ident["service"]["nrestarts"] == 0
    assert [g["pci_address"] for g in ident["gpu_identity"]] == ["0000:51:00.0", "0000:93:00.0"]
    assert ident["versions"]["api_key_configured"] is True


def test_identity_fail_closed_requires_bindings():
    mod = load_harness()
    assert mod.identity_requires_fail_closed({}, 1)
    assert mod.identity_requires_fail_closed(full_identity(mod), 2) == []


# --------------------------------------------------------------------------- G

def test_sentinel_is_deterministic_and_checked():
    mod = load_harness()
    first = mod.build_sentinel("medium", RUN_ID)
    second = mod.build_sentinel("medium", RUN_ID)
    assert first == second and first.startswith("RESPONSE_MARKER_")
    assert mod.build_sentinel("medium", "20260923T000000Z-00000000") != first


def test_sentinel_correctness_failure_records_invalid():
    mod = load_harness()
    validity = mod.compute_validity("FAIL", [{"code": "CORRECTNESS_FAILURE", "detail": "all responses invalid"}])
    doc = mod.build_benchmark_document(
        status="FAIL", mode="real", runtime="vllm", validity=validity,
        benchmark_run_id=RUN_ID, identity=full_identity(mod),
        workload={"workload_id": "b0-medium-short-c1"},
    )
    assert doc["validity"]["state"] == "INVALID"
    assert any(r["code"] == "CORRECTNESS_FAILURE" for r in doc["validity"]["reasons"])


# --------------------------------------------------------------------------- I

def test_warmup_records_excluded_from_metrics():
    mod = load_harness()
    records = [measured_record(0, warmup=True), measured_record(1, warmup=True),
               measured_record(2), measured_record(3), measured_record(4)]
    metrics = mod.build_metrics_document(RUN_ID, records)
    assert metrics["counts"]["measured"] == 3
    assert metrics["counts"]["warmup"] == 2
    assert metrics["distributions"]["ttft_ms"]["count"] == 3


def test_deterministic_filler_hits_exact_char_budget():
    mod = load_harness()
    budget = int(1024 * 3.8)
    filler = mod._deterministic_filler(1024, 3.8, "b0-short-1024")
    assert len(filler) == budget
    assert filler.startswith("// b0-short-1024")


def test_prompt_calibration_iterates_to_deviation_bound(monkeypatch):
    mod = load_harness()
    state = {"calls": 0}

    def fake_tokenize(base_url, api_key, model, prompt, timeout_sec=30.0):
        state["calls"] += 1
        cpt = state["calls"]
        ratio = 3.8 - 0.05 * cpt
        return {"ok": True, "count": max(int(len(prompt) / ratio), 1), "endpoint": "/tokenize"}

    monkeypatch.setattr(mod, "tokenize_prompt", fake_tokenize)
    result = mod.build_deterministic_prompt(
        prompt_class="short", target_tokens=1024,
        base_url="http://127.0.0.1:8000", api_key=None,
        model="m", max_deviation_pct=5.0,
    )
    assert result["token_source"] == "server_tokenize"
    assert result["deviation_pct"] <= 5.0
    assert state["calls"] >= 2


# --------------------------------------------------------------------------- J

def test_thermal_abort_sampler_stops(monkeypatch):
    mod = load_harness()
    monkeypatch.setattr(mod, "discover_gpu_topology",
                        lambda: [{"card": "card1", "hwmon": "hwmonFake"}])
    monkeypatch.setattr(mod, "_gpu_max_temp_c", lambda hwmon: 95.0)
    sampler = mod.TelemetrySampler(interval_sec=0.01, abort_threshold_c=90.0)
    sampler.run()
    assert sampler.aborted is True
    assert sampler.max_temperature() == 95.0
    assert sampler.required_sensor_present is True


def test_thermal_abort_reason_code_is_in_failure_taxonomy():
    mod = load_harness()
    assert "THERMAL_ABORT" in mod.FAILURE_TAXONOMY
    validity = mod.compute_validity(
        "FAIL", [{"code": "THERMAL_ABORT", "detail": mod.FAILURE_TAXONOMY["THERMAL_ABORT"]}]
    )
    assert validity["state"] == "INVALID"


def test_power_budget_over_refusal_respects_not_run():
    mod = load_harness()
    args = base_args(mod, gpu_count=2, gpu_tdp_watts=300.0, psu_capacity_watts=750.0,
                     system_base_power_watts=200.0, power_headroom_pct=10.0)
    doc, records, metrics_doc = mod.run_real_benchmark(args)
    assert doc["safety"]["power_budget"]["status"] == "refused"
    assert doc["status"] == "NOT_RUN"
    assert doc["failure_criteria"] == []
    codes = {r["code"] for r in doc["validity"]["reasons"]}
    assert "POWER_BUDGET_EXCEEDED" in codes
    assert records == []


# --------------------------------------------------------------------------- L/M

def test_evidence_bundle_immutable_rejects_duplicate_run_id(tmp_path):
    mod = load_harness()
    docs = {"manifest": {"benchmark_run_id": RUN_ID}, "validity": {"state": "VALID"}}
    mod.write_run_evidence(tmp_path, RUN_ID, docs)
    with pytest.raises(FileExistsError):
        mod.write_run_evidence(tmp_path, RUN_ID, docs)


def test_simulated_projection_isolated_and_non_authoritative(tmp_path):
    mod = load_harness()
    doc = mod.run_simulated_benchmark(base_args(mod))
    assert doc["status"] == "SIMULATED_PASS"
    paths = mod.write_simulated_projection(tmp_path, doc)
    assert "benchmarks/simulated/benchmark.json" in str(paths["benchmark"])
    index = json.loads(Path(paths["index"]).read_text())
    assert index["authoritative"] is False
    assert "Not physical acceptance evidence" in index["note"]
    assert not (tmp_path / "benchmarks" / RUN_ID).exists()


def test_run_card_carries_run_id_and_harness_identity():
    mod = load_harness()
    doc = mod.build_benchmark_document(
        status="SIMULATED_PASS", mode="simulated", runtime="simulated",
        benchmark_run_id="20260923T000000Z-feedface",
        raw_artifacts={"requests_jsonl": "raw/requests.jsonl"},
    )
    assert re.match(r"^[0-9]{8}T[0-9]{6}Z-[a-f0-9]{8}$", doc["benchmark_run_id"])
    assert doc["harness"]["version"]
    assert re.match(r"^[0-9a-f]{64}$", doc["harness"]["source_sha256"])
    assert re.match(r"^[0-9a-f]{40}$", doc["git_sha"])


def test_validate_contract_accepts_benchmark_fixture_end_to_end():
    fixture = REPO_ROOT / "tests/fixtures/schemas/benchmark.valid.json"
    result = subprocess.run(
        [sys.executable, str(VALIDATE_SCRIPT), "benchmark", str(fixture)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_validator_accepts_all_supported_failure_criterion_codes():
    mod = load_harness()
    validate_contract = load_validate_contract()
    base = mod.build_benchmark_document(
        status="NOT_RUN", mode="real", runtime="vllm",
        identity=full_identity(mod),
        workload={"workload_id": "b0-medium-short-c1"},
    )
    for code in ("power_budget_exceeded", "thermal_abort", "telemetry_lost"):
        doc = dict(base)
        doc["failure_criteria"] = [{"criterion": code, "status": "triggered"}]
        errors = validate_contract.validate_benchmark_payload(doc)
        assert not errors, f"{code}: {errors}"
    doc = dict(base)
    doc["failure_criteria"] = [{"criterion": "telemetry_lost", "status": "triggered"}]
    errors = validate_contract.validate_benchmark_payload(doc)
    assert not errors
