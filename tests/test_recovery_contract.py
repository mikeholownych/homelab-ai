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
    # StartLimit* are [Unit]-section directives; placing them in [Service]
    # makes systemd silently ignore them, leaving restarts unbounded.
    unit_section = template.split("\n[Service]")[0]
    service_section = template.split("\n[Service]")[1]
    assert "StartLimitIntervalSec=300s" in unit_section
    assert "StartLimitBurst=3" in unit_section
    assert "StartLimitIntervalSec" not in service_section
    assert "StartLimitBurst" not in service_section
    # WorkingDirectory must be accessible to the service account; the shared
    # /etc/local-ai root is root:render (not fully traversable by the runtime
    # user as a systemd chdir), so the unit chdirs into the account home.
    assert "WorkingDirectory=" in template
    assert "host_runtime_account.home" in template


def test_shared_local_ai_root_is_group_traversable_for_runtime():
    monitoring = (REPO_ROOT / "roles/monitoring/tasks/main.yml").read_text()
    # The shared config root must be group-traversable so the runtime account
    # (group render) can reach its own role subdirectory; per-role modes still
    # gate content. Root:root 0750 on /etc/local-ai breaks service startup
    # (CHDIR / config read) on every convergence.
    assert "host_runtime_account.group" in monitoring
    assert monitoring.count('"/etc/local-ai"') >= 1 or "monitoring_config_dir" in monitoring


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


def test_restart_count_read_from_systemd_not_hardcoded():
    launcher = (REPO_ROOT / "roles/vllm_xpu/files/vllm-xpu-runner.sh").read_text()
    assert '"restart_count": "0"' not in launcher
    assert "systemctl show" in launcher
    assert "NRestarts" in launcher
    assert "restart_count_source" in launcher
    assert "restart_count_obtained_at" in launcher
    # Failure to read the authoritative counter must surface, never fabricate 0
    assert 'restart_count="null"' in launcher
    assert 'restart_count_source="unavailable"' in launcher


def test_recovery_policy_documents_restart_count_provenance():
    policy = load_yaml("policies/lifecycle-recovery.yml")
    rc = policy["restart_count"]
    assert rc["source"] == "systemctl show {unit} -p NRestarts --value"
    assert "current activation/lifecycle" in rc["scope"]
    assert "never a silent 0" in rc["failure_behavior"]
    assert "service_invocation_id" in rc["related_identity"]


def test_readiness_evidence_contract_distinguishes_starting_from_ready():
    policy = load_yaml("policies/lifecycle-recovery.yml")
    ev = policy["readiness_evidence"]
    assert ev["record"].endswith("/vllm_readiness.json")
    assert set(ev["states"]) == {"STARTING", "READY", "STALLED"}
    assert "health_ready_at" in ev["fields"]
    assert "model_ready_at" in ev["fields"]
    assert "validation_ready_at" in ev["fields"]
    assert "startup_duration" in ev["fields"]
    assert "model_identity" in ev["fields"]
    assert "tensor_parallel_size" in ev["fields"]
    assert "boot_id" in ev["fields"]
    assert "service_invocation_id" in ev["fields"]


def test_readiness_evidence_not_in_systemd_supervision_path():
    ev = load_yaml("policies/lifecycle-recovery.yml")["readiness_evidence"]
    assert "NOT in the systemd supervision path" in ev["observer"]
    template = (REPO_ROOT / "roles/vllm_xpu/templates/vllm.service.j2").read_text()
    # systemd must not invoke the readiness prober (would couple supervision to
    # a probe and enable restart loops on slow cold starts).
    probe = (REPO_ROOT / "roles/vllm_xpu/templates/vllm.service.j2").read_text()
    assert "local-ai-vllm-readiness" not in probe
    assert "ExecStartPre" not in template or "readiness" not in template


def test_readiness_prober_written_by_launcher_and_precreated_for_writes():
    launcher = (REPO_ROOT / "roles/vllm_xpu/files/vllm-xpu-runner.sh").read_text()
    assert "local-ai-vllm-readiness" in launcher
    assert "READINESS_RECORD" in launcher
    prober = (REPO_ROOT / "roles/vllm_xpu/files/vllm-readiness-probe.sh").read_text()
    assert "/health" in prober
    assert "/v1/models" in prober
    assert "READY" in prober
    assert "STARTING" in prober
    assert "STALLED" in prober
    tasks = (REPO_ROOT / "roles/vllm_xpu/tasks/main.yml").read_text()
    assert "vllm_xpu_readiness_record" in tasks
    assert "vllm-readiness-probe.sh" in tasks