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


def test_not_applicable_checks_do_not_block_healthy_status():
    mod = load_aggregator()
    schema = load_schema()

    checks_data = {
        check_id: {"status": "PASS", "expected": "PASS", "observed": "PASS"}
        for check_id in mod.REQUIRED_CHECKS_SPEC
    }
    # Set unmanaged/retired checks to NOT_APPLICABLE
    checks_data["vllm_service"] = {"status": "NOT_APPLICABLE", "expected": "unmanaged", "observed": "NOT_APPLICABLE"}
    checks_data["dual_gpu_inference"] = {"status": "NOT_APPLICABLE", "expected": "unmanaged", "observed": "NOT_APPLICABLE"}
    checks_data["os_tuning_governor"] = {"status": "NOT_APPLICABLE", "expected": "unmanaged", "observed": "NOT_APPLICABLE"}
    checks_data["os_tuning_thp"] = {"status": "NOT_APPLICABLE", "expected": "unmanaged", "observed": "NOT_APPLICABLE"}
    checks_data["os_tuning_hugepages"] = {"status": "NOT_APPLICABLE", "expected": "unmanaged", "observed": "NOT_APPLICABLE"}
    checks_data["os_tuning_sysctl"] = {"status": "NOT_APPLICABLE", "expected": "unmanaged", "observed": "NOT_APPLICABLE"}
    checks_data["running_kernel"] = {"status": "NOT_APPLICABLE", "expected": "unmanaged", "observed": "NOT_APPLICABLE"}

    doc = mod.build_validation_document(
        node_id="ai-5820-01",
        environment="production",
        hardware_profile="d5820_dual_b65",
        git_sha="0123456789abcdef0123456789abcdef01234567",
        simulated=False,
        checks_data=checks_data,
        hardware_profile_spec=_load_d5820_profile(),
    )

    jsonschema.validate(instance=doc, schema=schema)
    assert doc["status"] == "PASS"
    assert doc["summary"]["classification"] == "healthy"
    assert doc["summary"]["not_tested"] == 0
    assert doc["summary"]["not_applicable"] == 7
    assert doc["summary"]["blocking_failures"] == 0
    assert doc["summary"]["failed_checks"] == 0


def test_evidence_dir_auto_discovery(tmp_path):
    mod = load_aggregator()
    schema = load_schema()

    # Create mock hardware.json and pci.json and xpu-validation.json
    hw_file = tmp_path / "hardware.json"
    hw_file.write_text(json.dumps({
        "status": "pass",
        "checks": [
            {"rule": "machine_model", "status": "pass", "expected": "Precision 5820 Tower", "observed": "Precision 5820 Tower"},
            {"rule": "cpu_model", "status": "pass", "expected": "Intel(R) Xeon(R) W-2123", "observed": "Intel(R) Xeon(R) W-2123 CPU @ 3.60GHz"},
            {"rule": "gpu_count", "status": "pass", "expected": 2, "observed": ["0000:51:00.0", "0000:93:00.0"]},
            {"rule": "gpu_model_match", "status": "pass", "expected": "Intel Arc Pro B65", "observed": "Intel Arc Pro B65"},
            {"rule": "gpu_memory", "status": "pass", "expected": 32.0, "observed": [32.0, 32.0]},
            {"rule": "level_zero_detected", "status": "pass", "expected": 2, "observed": [{"uuid": "uuid1"}, {"uuid": "uuid2"}]},
        ]
    }))

    pci_file = tmp_path / "pci.json"
    pci_file.write_text(json.dumps({
        "status": "pass",
        "checks": [
            {"rule": "pcie_link_health", "status": "pass", "expected": "Gen3 Link", "observed": []},
            {"rule": "resizable_bar_enabled", "status": "pass", "expected": True, "observed": [True, True]},
        ]
    }))

    xpu_file = tmp_path / "xpu-validation.json"
    xpu_file.write_text(json.dumps({
        "status": "PASS",
        "device_count": 2,
        "torch_version": "2.12.1+xpu",
    }))

    profile_path = tmp_path / "d5820.json"
    profile_path.write_text(json.dumps(_load_d5820_profile()))

    # Run aggregator CLI with --evidence-dir
    process = subprocess.run(
        [str(AGGREGATOR_PATH), "--node-id", "ai-5820-01", "--hardware-profile",
         "d5820_dual_b65", "--git-sha", "0123456789abcdef0123456789abcdef01234567",
         "--simulated", "--hardware-profile-json", str(profile_path),
         "--evidence-dir", str(tmp_path)],
        check=False, capture_output=True, text=True,
    )
    assert process.returncode == 0, process.stderr
    doc = json.loads(process.stdout)
    jsonschema.validate(instance=doc, schema=schema)
    by_id = {check["id"]: check for check in doc["checks"]}
    assert by_id["machine_model"]["status"] == "PASS"
    assert by_id["cpu"]["status"] == "PASS"
    assert by_id["gpu_count"]["status"] == "PASS"
    assert by_id["gpu_model"]["status"] == "PASS"
    assert by_id["gpu_vram"]["status"] == "PASS"
    assert by_id["level_zero"]["status"] == "PASS"
    assert by_id["pytorch_xpu"]["status"] == "PASS"
    assert by_id["pcie_topology"]["status"] == "PASS"
    assert by_id["rebar"]["status"] == "PASS"
    assert by_id["vllm_service"]["status"] == "NOT_APPLICABLE"
    assert by_id["dual_gpu_inference"]["status"] == "NOT_APPLICABLE"

