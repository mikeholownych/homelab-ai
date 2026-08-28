from __future__ import annotations

import json
from pathlib import Path
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_yaml(relpath: str) -> object:
    return yaml.safe_load((REPO_ROOT / relpath).read_text(encoding="utf-8"))


def test_reconciliation_timer_enabled_by_default():
    defaults = load_yaml("roles/scheduled_ansible/defaults/main.yml")
    assert defaults["scheduled_ansible_reconcile_enabled"] is True
    assert defaults["scheduled_ansible_reconcile_timer_schedule"]
    assert "RandomizedDelaySec" in (REPO_ROOT / "roles/scheduled_ansible/templates/aihost-reconcile.timer.j2").read_text()


def test_patch_and_benchmark_timers_disabled_by_default():
    defaults = load_yaml("roles/scheduled_ansible/defaults/main.yml")
    assert defaults["scheduled_ansible_patch_enabled"] is False
    assert defaults["scheduled_ansible_benchmark_enabled"] is False


def test_systemd_unit_templates_use_lock_and_snapshot_runner():
    reconcile_service = (REPO_ROOT / "roles/scheduled_ansible/templates/aihost-reconcile.service.j2").read_text()
    assert "run-ansible-snapshot" in reconcile_service
    assert "site.yml" in reconcile_service
    assert "LimitNOFILE=" in reconcile_service


WRAPPER_REQUIRED_ARGS = (
    "--repo-root",
    "--schema-root",
    "--inventory",
    "--target",
    "--playbook",
    "--lock-root",
)


def test_scheduled_units_pass_full_wrapper_argv():
    """The snapshot wrapper exits 64 on missing args; the units must send them all."""
    for unit in ("aihost-reconcile.service.j2", "aihost-patch.service.j2"):
        text = (REPO_ROOT / "roles/scheduled_ansible/templates" / unit).read_text()
        for arg in WRAPPER_REQUIRED_ARGS:
            assert arg in text, f"{unit} is missing required wrapper argument {arg}"
        assert "{{ inventory_hostname }}" in text, f"{unit} must target its own host"
        # Playbook name travels via --playbook, never as a bare positional.
        assert "--playbook" in text


def test_no_git_network_operations_in_reconcile_service():
    reconcile_service = (REPO_ROOT / "roles/scheduled_ansible/templates/aihost-reconcile.service.j2").read_text()
    assert "git pull" not in reconcile_service
    assert "git fetch" not in reconcile_service


def test_reconcile_service_runs_drift_check_after_site():
    reconcile_service = (REPO_ROOT / "roles/scheduled_ansible/templates/aihost-reconcile.service.j2").read_text()
    assert reconcile_service.count("ExecStart=") == 2
    assert "--playbook site.yml" in reconcile_service
    assert "--playbook drift-check.yml" in reconcile_service
    # Drift classification must run after convergence so blocking drift is raised.
    assert reconcile_service.find("--playbook drift-check.yml") > reconcile_service.find("--playbook site.yml")


def test_drift_check_playbook_is_wrapper_allowlisted():
    wrapper = (REPO_ROOT / "scripts" / "run-ansible-snapshot").read_text()
    assert '"drift-check.yml"' in wrapper


def test_monitoring_gpu_thermal_thresholds_below_benchmark_abort():
    monitoring_defaults = load_yaml("roles/monitoring/defaults/main.yml")
    benchmarking_defaults = load_yaml("roles/benchmarking/defaults/main.yml")
    warn = float(monitoring_defaults["monitoring_gpu_temp_warn_threshold_c"])
    crit = float(monitoring_defaults["monitoring_gpu_temp_crit_threshold_c"])
    abort = float(benchmarking_defaults["benchmarking_abort_temperature_c"])
    assert 0 < warn < crit < abort
    assert monitoring_defaults["monitoring_gpu_temp_alert_enabled"] is True


def test_monitoring_defaults_and_tasks_contract():
    defaults = load_yaml("roles/monitoring/defaults/main.yml")
    assert defaults["monitoring_enabled"] is True
    assert defaults["monitoring_log_dir"] == "/var/log/local-ai/monitoring"
    tasks = (REPO_ROOT / "roles/monitoring/tasks/main.yml").read_text()
    assert "ansible_check_mode" in tasks
    assert "ignore_errors" not in tasks
