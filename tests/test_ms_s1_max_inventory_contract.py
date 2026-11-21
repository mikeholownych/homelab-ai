from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(path: str):
    return yaml.safe_load((ROOT / path).read_text())


def test_production_hosts_registers_ms_s1_max():
    # Phase 3a promoted the host out of lab (see test_ms_s1_max_promotion_contract.py).
    hosts = load("inventory/production/hosts.yml")
    children = hosts["all"]["children"]
    for group in ("production", "gpu", "inference", "cluster", "monitoring"):
        assert "ai-ms-s1-max-01" in children[group]["hosts"], group
    lab = load("inventory/lab/hosts.yml")
    for name, group in lab["all"]["children"].items():
        assert "ai-ms-s1-max-01" not in (group or {}).get("hosts", {}), name


def test_ms_s1_max_host_vars_phase1_contract():
    hv = load("inventory/production/host_vars/ai-ms-s1-max-01.yml")
    assert hv["ansible_host"] == "10.0.8.6"
    assert hv["hardware_profile"] == "ms_s1_max_strix_halo"
    assert hv["os_tuning_profile"] == "baseline"
    assert hv["node_metadata"]["hostname"] == "ai-ms-s1-max-01"
    assert hv["node_metadata"]["hardware_profile"] == "ms_s1_max_strix_halo"
    # Phase 1 kept inference off; Phase 2d enables it for the winner only
    # (see test_ms_s1_max_engine_wire_contract.py).
    assert hv["node_roles"]["gpu"] is True
    assert hv["capabilities"]["gpu"] is True
    assert hv["users_local_ai_manage_device_groups"] is True
    assert hv["users_local_ai_device_groups"] == ["render", "video"]
    assert hv["rocm_install_enabled"] is True
    assert hv["intel_gpu_install_enabled"] is False
    assert hv["intel_gpu_physical_validation_enabled"] is False
    assert hv["storage_lvm"]["enabled"] is True
    assert hv["storage_lvm"]["size"] == "1024g"
    assert hv["storage_lvm"]["reserve_gib"] == 100
    assert hv["storage_lvm"]["expected_pvs"] == ["/dev/nvme0n1p3"]