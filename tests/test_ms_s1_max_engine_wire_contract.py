"""Phase 2d contract: the Strix Halo bake-off winner (llama.cpp HIP) is wired on the lab host only."""
from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[1]
HOST = "ai-ms-s1-max-01"
ENGINE_FLAGS = (
    "llama_cpp_container_enabled",
    "llama_cpp_hip_enabled",
    "vllm_rocm_enabled",
    "sglang_rocm_enabled",
)


def load(path: str):
    return yaml.safe_load((ROOT / path).read_text())


def host_vars() -> dict:
    return load(f"inventory/lab/host_vars/{HOST}.yml")


def test_lab_ms_s1_inference_enabled_for_winner_only():
    hv = host_vars()
    assert hv["node_roles"]["inference"] is True
    assert hv["capabilities"]["inference"] is True
    enabled = [flag for flag in ENGINE_FLAGS if hv.get(flag)]
    assert enabled == ["llama_cpp_hip_enabled"]


def test_host_not_in_production_inventory():
    production = load("inventory/production/hosts.yml")
    groups = production["all"]["children"]
    for name, group in groups.items():
        assert HOST not in (group or {}).get("hosts", {}), name
    assert not (ROOT / f"inventory/production/host_vars/{HOST}.yml").exists()


def test_gpu_stack_stays_rocm_only():
    hv = host_vars()
    assert hv["rocm_install_enabled"] is True
    assert hv["intel_gpu_install_enabled"] is False


def test_winner_pins_match_bakeoff_recommendation():
    hv = host_vars()
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", hv["llama_cpp_hip_digest"])
    assert hv["llama_cpp_hip_digest"] == (
        "sha256:9c44da4d33fa3e1250ec910d3af7b7acd1154baef3fe0efda53d91ae4a9f4184"
    )
    assert hv["llama_cpp_hip_drain_via_gateway"] is False
    workers = hv["llama_cpp_hip_workers"]
    assert len(workers) == 1
    worker = next(iter(workers.values()))
    assert worker["model_file"] == "Qwen3-Coder-30B-A3B-Instruct-Q8_0.gguf"
    assert worker["port"] == 8101
    assert worker["context"] == 65536
    assert worker["args"] == ["-ngl", "99", "-fa", "on", "--jinja", "-np", "4"]

def test_hip_role_is_disabled_by_default_and_fail_closed():
    defaults = load("roles/llama_cpp_hip/defaults/main.yml")
    assert defaults["llama_cpp_hip_enabled"] is False
    assert defaults["llama_cpp_hip_host"] == "127.0.0.1"
    assert defaults["llama_cpp_hip_drain_via_gateway"] is False
    tasks = (ROOT / "roles/llama_cpp_hip/tasks/main.yml").read_text()
    assert "sha256:[0-9a-f]{64}" in tasks


def test_hip_unit_has_no_sycl_or_policy_coupling():
    unit = (ROOT / "roles/llama_cpp_hip/templates/llama-hip.service.j2").read_text()
    for forbidden in (
        "local-ai.intel/gpu",
        "ONEAPI",
        "ZE_AFFINITY",
        "SYCL",
        "aihost-inference-policy",
        "HSA_OVERRIDE_GFX_VERSION",
    ):
        assert forbidden not in unit, forbidden
    for required in ("--device /dev/kfd", "--device /dev/dri", "--group-add keep-groups", "--network host"):
        assert required in unit, required


def test_site_wires_hip_role_behind_enable_flag_and_tag():
    site = (ROOT / "playbooks/site.yml").read_text()
    play = yaml.safe_load(site)[1]
    tasks = [
        t for t in play["tasks"]
        if (t.get("ansible.builtin.include_role") or {}).get("name") == "llama_cpp_hip"
    ]
    assert len(tasks) == 1
    task = tasks[0]
    assert "llama_cpp_hip_enabled | default(false) | bool" in task["when"]
    assert "llama_cpp_hip" in task["tags"]


def test_commissioning_doc_covers_phase_2():
    doc = (ROOT / "docs/commissioning.md").read_text()
    assert "MS-S1 Max Phase 2" in doc
    assert "--tags llama_cpp_hip" in doc
