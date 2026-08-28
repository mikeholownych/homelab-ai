from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path
import pytest
import jsonschema
import yaml

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
            "intel_gpu_stack_status": {"status": "PASS", "expected": "pre_verification_fail_closed",
                                       "observed": "pre_verification_fail_closed"},
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


def _load_d5820_profile():
    path = REPO_ROOT / "profiles" / "hardware" / "d5820_dual_b65.yml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_hardware_profile_spec_derives_d5820_expected_values():
    mod = load_aggregator()
    schema = load_schema()

    doc = mod.build_validation_document(
        node_id="ai-5820-01",
        environment="production",
        hardware_profile="d5820_dual_b65",
        git_sha="0123456789abcdef0123456789abcdef01234567",
        simulated=True,
        checks_data={},
        hardware_profile_spec=_load_d5820_profile(),
    )

    jsonschema.validate(instance=doc, schema=schema)
    by_id = {check["id"]: check for check in doc["checks"]}
    assert by_id["machine_model"]["expected"]["value"] == "Precision 5820 Tower"
    assert by_id["cpu"]["expected"]["value"] == "Intel(R) Xeon(R) W-2123"
    assert by_id["gpu_count"]["expected"]["value"] == 2
    assert by_id["gpu_vram"]["expected"]["value"] == 32.0
    assert by_id["pcie_topology"]["expected"]["value"] == "Gen3"
    assert by_id["machine_model"]["expected"]["summary"] == "Precision 5820 Tower"
    assert doc["status"] == "NOT_TESTED"


def test_aggregator_cli_accepts_hardware_profile_json(tmp_path):
    profile_path = tmp_path / "d5820.json"
    profile_path.write_text(json.dumps(_load_d5820_profile()))

    process = subprocess.run(
        [str(AGGREGATOR_PATH), "--node-id", "ai-5820-01", "--hardware-profile",
         "d5820_dual_b65", "--git-sha", "0123456789abcdef0123456789abcdef01234567",
         "--simulated", "--hardware-profile-json", str(profile_path)],
        check=False, capture_output=True, text=True,
    )
    assert process.returncode == 0, process.stderr
    doc = json.loads(process.stdout)
    by_id = {check["id"]: check for check in doc["checks"]}
    assert by_id["machine_model"]["expected"]["value"] == "Precision 5820 Tower"
    assert by_id["gpu_count"]["expected"]["value"] == 2
