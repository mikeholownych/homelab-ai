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
    assert doc["status"] == "PASS"
    assert doc["simulated"] is True
    assert doc["execution"]["gpu_count"] == 1


def test_playbook_benchmark_structure():
    content = (REPO_ROOT / "playbooks/benchmark.yml").read_text()
    assert "benchmark" in content
    assert "benchmarking" in content
