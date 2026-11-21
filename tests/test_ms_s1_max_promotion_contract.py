"""Phase 3a contract: ai-ms-s1-max-01 is a production peer, no longer a lab host."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
HOST = "ai-ms-s1-max-01"


def load(path: str):
    return yaml.safe_load((ROOT / path).read_text())


def test_production_hosts_registers_ms_s1_max():
    hosts = load("inventory/production/hosts.yml")
    for group in ("production", "inference", "gpu", "monitoring", "cluster"):
        assert HOST in hosts["all"]["children"][group]["hosts"], group


def test_lab_no_longer_lists_live_ms_s1_max():
    hosts = load("inventory/lab/hosts.yml")
    for name, group in hosts["all"]["children"].items():
        assert HOST not in (group or {}).get("hosts", {}), name
    assert not (ROOT / f"inventory/lab/host_vars/{HOST}.yml").exists()


def test_production_host_vars_promotion_contract():
    hv = load(f"inventory/production/host_vars/{HOST}.yml")
    assert hv["node_metadata"]["environment"] == "production"
    assert hv["capabilities"]["cluster_eligible"] is True
    features = hv["features"]
    for flag in ("monitoring", "scheduled_reconciliation", "observability", "os_tuning"):
        assert features[flag] is True, flag
    for flag in (
        "model_registry",
        "clustering",
        "cmdb_export",
        "itsm_integration",
        "ray_enabled",
        "distributed_vllm_enabled",
    ):
        assert features[flag] is False, flag
    assert hv["llama_cpp_hip_enabled"] is True
    assert hv["llama_cpp_hip_host"] == "10.0.8.6"
    assert hv["orchestrator_gateway_enabled"] is True
    assert hv["security_firewall_enabled"] is True
    assert hv["security_inference_api_firewall_enabled"] is True
    assert hv["security_inference_api_cidrs"] == ["10.0.8.5/32"]
    assert hv["security_inference_api_ports"] == [8101]
    assert hv["rocm_install_enabled"] is True
    assert hv["intel_gpu_install_enabled"] is False
    assert hv["intel_gpu_physical_validation_enabled"] is False
    assert hv["users_runtime_rootless_enabled"] is True
    assert hv["storage_lvm"]["enabled"] is True
