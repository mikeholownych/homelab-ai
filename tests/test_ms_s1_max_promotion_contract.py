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


def test_ms_s1_gateway_is_rocm_only():
    """Phase 3c: the local gateway serves the ROCm alias from one HIP worker and never the Intel aliases."""
    hv = load(f"inventory/production/host_vars/{HOST}.yml")
    assert hv["orchestrator_gateway_engine"] == "asgi"
    assert hv["orchestrator_gateway_remote_host"] == "10.0.8.6"
    assert hv["orchestrator_gateway_remote_port"] == 8443
    assert hv["orchestrator_gateway_tls_sans"] == ["IP:10.0.8.6", "DNS:ai-ms-s1-max-01"]

    aliases = hv["orchestrator_gateway_model_aliases"]
    assert aliases == {"engineering/interactive-rocm": {
        "pool": "rocm", "reasoning": {"mode": "off", "answer_allowance": 8192}}}
    for intel_alias in ("engineering/lead", "engineering/deep", "engineering/lead-reasoning"):
        assert intel_alias not in aliases, intel_alias

    routes = hv["orchestrator_gateway_routes"]
    assert [route["id"] for route in routes] == ["interactive-rocm", "default"]
    assert routes[0]["match"] == {"model": ["engineering/interactive-rocm"]}
    assert {route["pool"] for route in routes} == {"rocm"}
    assert all(route["fallback"] == [] for route in routes)

    (worker,) = hv["orchestrator_gateway_workers"]
    assert worker["worker_id"] == "ms-s1-hip-coder30b"
    assert worker["pool"] == "rocm"
    assert worker["endpoint"] == "http://10.0.8.6:8101"
    assert worker["credential_source"] == "/etc/local-ai/llama-hip/qwen3_coder_30b_q8/worker-api-key"
    assert worker["runtime_image_digest"] == hv["llama_cpp_hip_digest"]
    assert worker["model_id"] == hv["llama_cpp_hip_workers"]["qwen3_coder_30b_q8"]["served_name"]
    assert hv["orchestrator_gateway_production_worker_count"] == 1
    assert worker["port"] == hv["llama_cpp_hip_workers"]["qwen3_coder_30b_q8"]["port"]
    assert {w["pool"] for w in hv["orchestrator_gateway_workers"]} == {"rocm"}


def test_ms_s1_gateway_tls_port_open_to_controller_only():
    hv = load(f"inventory/production/host_vars/{HOST}.yml")
    assert hv["security_inference_api_port_cidrs"] == [{"port": 8443, "cidrs": ["10.0.8.95/32"]}]
    assert hv["orchestrator_gateway_remote_client_cidrs"] == ["10.0.8.95/32"]
    # The HIP worker port stays reachable from the 5820 gateway only.
    assert hv["security_inference_api_cidrs"] == ["10.0.8.5/32"]
    assert hv["security_inference_api_ports"] == [8101]


def test_ms_s1_gateway_does_not_replace_the_5820_controller_trust():
    hv = load(f"inventory/production/host_vars/{HOST}.yml")
    assert hv["orchestrator_gateway_tls_controller_trust_store_enabled"] is False
    assert hv["orchestrator_gateway_tls_pki_dir"].endswith("/pki/ai-ms-s1-max-01")
    intel = load("inventory/production/host_vars/ai-5820-01.yml")
    assert hv["orchestrator_gateway_tls_pki_dir"] != intel["orchestrator_gateway_tls_pki_dir"]
