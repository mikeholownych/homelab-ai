from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import pytest
import jsonschema

REPO_ROOT = Path(__file__).resolve().parents[1]
AGGREGATOR_PATH = REPO_ROOT / "roles/validation/files/aggregate_validation.py"
SCHEMA_PATH = REPO_ROOT / "schemas/validation.schema.json"


def load_aggregator():
    spec = importlib.util.spec_from_file_location("aggregate_validation", AGGREGATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_aggregator_script_exists():
    assert AGGREGATOR_PATH.exists()


def test_aggregator_produces_valid_schema_document(tmp_path):
    mod = load_aggregator()
    schema = load_schema()

    out_file = tmp_path / "validation.json"
    summary_file = tmp_path / "validation_summary.txt"

    doc = mod.build_validation_document(
        node_id="ai-p620-01",
        environment="production",
        hardware_profile="p620_dual_b65",
        git_sha="0123456789abcdef0123456789abcdef01234567",
        simulated=True,
        checks_data={
            "cpu": {"status": "PASS", "expected": "AMD Threadripper PRO 3945WX", "observed": "AMD Threadripper PRO 3945WX"},
            "machine_model": {"status": "PASS", "expected": "30E1S7NJ00", "observed": "30E1S7NJ00"},
            "gpu_count": {"status": "PASS", "expected": 2, "observed": 2},
            "gpu_model": {"status": "PASS", "expected": "Intel Arc Pro B65", "observed": "Intel Arc Pro B65"},
            "gpu_vram": {"status": "PASS", "expected": 32.0, "observed": 32.0},
            "level_zero": {"status": "PASS", "expected": 2, "observed": 2},
            "pytorch_xpu": {"status": "PASS", "expected": 2, "observed": 2},
            "pcie_topology": {"status": "PASS", "expected": "Gen4 x16", "observed": "Gen4 x16"},
            "rebar": {"status": "PASS", "expected": True, "observed": True},
            "vllm_service": {"status": "PASS", "expected": "healthy", "observed": "healthy"},
            "single_gpu_inference": {"status": "PASS", "expected": "PASS", "observed": "PASS"},
            "dual_gpu_inference": {"status": "PASS", "expected": "PASS", "observed": "PASS"},
            "llama_cpp_fallback": {"status": "PASS", "expected": "PASS", "observed": "PASS"},
            "required_services": {"status": "PASS", "expected": "active", "observed": "active"},
            "scheduled_reconciliation": {"status": "PASS", "expected": "enabled", "observed": "enabled"},
            "vault_access": {"status": "PASS", "expected": "accessible", "observed": "accessible"},
            "os_tuning_profile": {"status": "PASS", "expected": "baseline", "observed": "baseline"},
            "os_tuning_governor": {"status": "PASS", "expected": "PASS", "observed": "PASS"},
            "os_tuning_thp": {"status": "PASS", "expected": "PASS", "observed": "PASS"},
            "os_tuning_hugepages": {"status": "PASS", "expected": "PASS", "observed": "PASS"},
            "os_tuning_sysctl": {"status": "PASS", "expected": "PASS", "observed": "PASS"},
            "running_kernel": {"status": "PASS", "expected": "PASS", "observed": "PASS"},
            "numa_topology": {"status": "PASS", "expected": "stable", "observed": "PASS"},
        }
    )

    jsonschema.validate(instance=doc, schema=schema)
    assert doc["status"] == "PASS"
    assert doc["summary"]["classification"] == "healthy"
    assert doc["simulated"] is True


def test_blocking_failure_causes_blocked_status(tmp_path):
    mod = load_aggregator()
    schema = load_schema()

    doc = mod.build_validation_document(
        node_id="ai-p620-01",
        environment="production",
        hardware_profile="p620_dual_b65",
        git_sha="0123456789abcdef0123456789abcdef01234567",
        simulated=False,
        checks_data={
            "gpu_count": {"status": "FAIL", "expected": 2, "observed": 1, "severity": "blocking"},
        }
    )

    jsonschema.validate(instance=doc, schema=schema)
    assert doc["status"] in ("BLOCKED", "FAIL")
    assert doc["summary"]["blocking_failures"] > 0
    assert doc["summary"]["classification"] == "blocked"


def test_uncommissioned_not_tested_causes_incomplete_status():
    mod = load_aggregator()
    schema = load_schema()

    doc = mod.build_validation_document(
        node_id="ai-p620-01",
        environment="production",
        hardware_profile="p620_dual_b65",
        git_sha="0123456789abcdef0123456789abcdef01234567",
        simulated=False,
        checks_data={}
    )

    jsonschema.validate(instance=doc, schema=schema)
    assert doc["status"] == "NOT_TESTED"
    assert doc["summary"]["classification"] == "incomplete"
    assert doc["summary"]["not_tested"] > 0
