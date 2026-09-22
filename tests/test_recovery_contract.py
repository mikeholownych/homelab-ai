from __future__ import annotations

from pathlib import Path
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_yaml(relpath: str) -> object:
    return yaml.safe_load((REPO_ROOT / relpath).read_text(encoding="utf-8"))


def test_recovery_policy_defines_full_readiness_ladder():
    policy = load_yaml("policies/lifecycle-recovery.yml")
    ladder = policy["readiness_ladder"]
    assert list(ladder) == ["A", "B", "C", "D", "E", "F"]
    expected_ids = [
        "prerequisites_valid",
        "container_started",
        "http_reachable",
        "model_loaded",
        "inference_functional",
        "tp_topology_active",
    ]
    observed = [ladder[k]["id"] for k in ladder]
    assert observed == expected_ids


def test_recovery_policy_defines_expected_failure_classes():
    policy = load_yaml("policies/lifecycle-recovery.yml")
    classes = policy["failure_classes"]
    assert set(classes) == {
        "vllm_crash",
        "container_crash",
        "userns_bootstrap_failure",
        "stale_pause_pid",
        "missing_model_cache",
        "model_identity_mismatch",
        "unavailable_gpu",
        "invalid_tp_topology",
        "xpu_device_lost",
        "startup_timeout",
        "inference_oom",
        "invalid_config",
        "host_reboot",
    }


def test_every_failure_class_has_bounded_recovery_fields():
    policy = load_yaml("policies/lifecycle-recovery.yml")
    for name, spec in policy["failure_classes"].items():
        assert spec["class"] in ("runtime", "prerequisite", "configuration", "operations"), name
        assert "detectable_signal" in spec and spec["detectable_signal"], name
        assert "safe_auto_recovery" in spec, name
        assert "recovery_action" in spec, name
        assert "evidence_emitted" in spec, name
        assert "max_retries" in spec, name
        assert "backoff_seconds" in spec, name
        assert "terminal_state" in spec, name
        if spec["safe_auto_recovery"]:
            assert spec["max_retries"] >= 1, f"{name} must declare retries when auto-recovery is true"
        else:
            assert spec["max_retries"] == 0, f"{name} must not loop when auto-recovery is false"


def test_recovery_policy_bounded_ceiling_no_unbounded_loops():
    policy = load_yaml("policies/lifecycle-recovery.yml")
    bounded = policy["bounded_recovery"]["unit_directives"]
    assert bounded["Restart"] == "on-failure"
    assert bounded["StartLimitBurst"] == "3"
    assert bounded["RestartPreventExitStatus"] == "78"
    for name, spec in policy["failure_classes"].items():
        if spec["safe_auto_recovery"]:
            assert spec["max_retries"] <= int(bounded["StartLimitBurst"]), name


def test_vllm_unit_embeds_bounded_recovery():
    template = (REPO_ROOT / "roles/vllm_xpu/templates/vllm.service.j2").read_text()
    assert "StartLimitIntervalSec=300s" in template
    assert "StartLimitBurst=3" in template
    assert "RestartPreventExitStatus=78" in template
    assert "Restart=on-failure" in template


def test_vllm_runner_writes_recovery_record_and_config_fail_closed():
    launcher = (REPO_ROOT / "roles/vllm_xpu/files/vllm-xpu-runner.sh").read_text()
    assert "write_recovery_record" in launcher
    assert "vllm_recovery.json" in launcher
    # config/prerequisite failures are terminal (exit 78), never restartable
    assert launcher.count("exit 78") >= 3
    assert "RestartPreventExitStatus=78" in (REPO_ROOT / "roles/vllm_xpu/templates/vllm.service.j2").read_text()


def test_vllm_env_pins_recovery_record_path():
    env_tpl = (REPO_ROOT / "roles/vllm_xpu/templates/vllm.env.j2").read_text()
    assert "RECOVERY_RECORD=" in env_tpl
    assert "vllm_xpu_recovery_record" in env_tpl
    defaults = load_yaml("roles/vllm_xpu/defaults/main.yml")
    assert defaults["vllm_xpu_evidence_dir"] == "/var/lib/aihost/evidence"
    record = defaults["vllm_xpu_recovery_record"]
    assert "vllm_xpu_evidence_dir" in record
    assert record.endswith("/vllm_recovery.json")