from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
MONITORING_DIR = REPO_ROOT / "roles" / "monitoring"
SCHEDULED_DIR = REPO_ROOT / "roles" / "scheduled_ansible"


def load_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class FailureVisibilityContractTests(unittest.TestCase):
    def test_alert_infrastructure_files_exist(self) -> None:
        for relative in (
            "files/alert.sh",
            "templates/aihost-alert@.service.j2",
            "defaults/main.yml",
        ):
            self.assertTrue((MONITORING_DIR / relative).exists(), relative)

    def test_timer_units_declare_on_failure_hook(self) -> None:
        for unit in ("aihost-reconcile.service.j2", "aihost-patch.service.j2"):
            text = (SCHEDULED_DIR / "templates" / unit).read_text(encoding="utf-8")
            self.assertIn("OnFailure=aihost-alert@%n", text, unit)

    def test_alert_script_never_evaluates_untrusted_content(self) -> None:
        script = (MONITORING_DIR / "files" / "alert.sh").read_text(encoding="utf-8")
        self.assertNotIn("eval ", script)
        self.assertIn('"$AIHOST_ALERT_COMMAND" "$unit" "$ts"', script)

    def test_evidence_sync_is_disabled_until_configured(self) -> None:
        defaults = load_yaml(MONITORING_DIR / "defaults" / "main.yml")
        self.assertFalse(defaults["monitoring_evidence_sync_enabled"])
        self.assertIsNone(defaults["monitoring_evidence_sync_destination"])

    def test_evidence_sync_requires_destination_when_enabled(self) -> None:
        tasks = load_yaml(MONITORING_DIR / "tasks" / "main.yml")
        assert_task = next(
            task for task in tasks
            if isinstance(task, dict) and task.get("name") == "Validate monitoring inputs"
        )
        joined = str(assert_task["ansible.builtin.assert"]["that"])
        self.assertIn("monitoring_evidence_sync_destination", joined)

    def test_evidence_mirror_is_append_only(self) -> None:
        script = (MONITORING_DIR / "files" / "sync-evidence.sh").read_text(encoding="utf-8")
        command_lines = [ln for ln in script.splitlines() if ln.strip().startswith("rsync")]
        self.assertTrue(command_lines, "expected an rsync invocation")
        for line in command_lines:
            self.assertIn("rsync -a", line)
            self.assertNotIn("--delete", line)


class RebootVerifyContractTests(unittest.TestCase):
    PLAYBOOK = REPO_ROOT / "playbooks" / "reboot-verify.yml"

    def test_playbook_exists_and_verifies_before_reboot(self) -> None:
        text = self.PLAYBOOK.read_text(encoding="utf-8")
        self.assertIn("ansible.builtin.reboot:", text)
        # Kernel presence is verified before the reboot task appears.
        stat_position = text.find("vmlinuz-{{ reboot_verify_expected_kernel }}")
        reboot_position = text.find("ansible.builtin.reboot:")
        self.assertGreater(reboot_position, stat_position > 0 and stat_position or -1)

    def test_kernel_mismatch_fails_closed_after_boot(self) -> None:
        text = self.PLAYBOOK.read_text(encoding="utf-8")
        self.assertIn("ansible.builtin.assert", text)
        self.assertIn("ansible_kernel == reboot_verify_expected_kernel", text)

    def test_post_reboot_validation_runs(self) -> None:
        text = self.PLAYBOOK.read_text(encoding="utf-8")
        self.assertIn("import_playbook: validate.yml", text)

    def test_wrapper_can_run_reboot_verify(self) -> None:
        wrapper = (REPO_ROOT / "scripts" / "run-ansible-snapshot").read_text(encoding="utf-8")
        self.assertIn('"reboot-verify.yml"', wrapper)


class GpuThermalGuardContractTests(unittest.TestCase):
    def test_copy_installed_scripts_are_jinja_free(self) -> None:
        """copy-installed scripts must not carry literal Jinja markers."""
        for relative in ("files/alert.sh", "files/write-textfile-metrics.sh"):
            script = (MONITORING_DIR / relative).read_text(encoding="utf-8")
            self.assertNotIn("{{", script, relative)
            self.assertNotIn("}}", script, relative)
            self.assertIn("/etc/local-ai/monitoring.env", script, relative)

    def test_config_env_is_templated_and_carries_thresholds(self) -> None:
        template = (MONITORING_DIR / "templates" / "monitoring.env.j2").read_text(encoding="utf-8")
        for marker in (
            "MONITORING_METRICS_TEXTFILE_DIR=",
            "MONITORING_ALERT_LOG_DIR=",
            "MONITORING_GPU_TEMP_STATE_DIR=",
            "MONITORING_GPU_TEMP_WARN_C=",
            "MONITORING_GPU_TEMP_CRIT_C=",
        ):
            self.assertIn(marker, template)
        tasks = load_yaml(MONITORING_DIR / "tasks" / "main.yml")
        template_task = next(
            task for task in tasks
            if isinstance(task, dict) and task.get("name") == "Install shared script runtime configuration"
        )
        self.assertEqual(template_task["ansible.builtin.template"]["mode"], "0640")

    def test_metrics_writer_emits_per_device_series_and_severity(self) -> None:
        script = (MONITORING_DIR / "files" / "write-textfile-metrics.sh").read_text(encoding="utf-8")
        self.assertIn('device=\\"$label\\"', script)
        self.assertIn("aihost_gpu_temperature_celsius $max_c", script)
        self.assertIn("aihost_gpu_thermal_severity", script)
        self.assertIn("gpu-temp.state", script)

    def test_metrics_writer_alert_path_is_argv_forward_only(self) -> None:
        script = (MONITORING_DIR / "files" / "write-textfile-metrics.sh").read_text(encoding="utf-8")
        self.assertNotIn("eval ", script)
        self.assertIn('"$AIHOST_ALERT_COMMAND" "aihost-gpu-thermal" "$ts"', script)

    def test_thermal_guard_defaults_are_sane(self) -> None:
        defaults = load_yaml(MONITORING_DIR / "defaults" / "main.yml")
        self.assertLess(defaults["monitoring_gpu_temp_warn_threshold_c"], defaults["monitoring_gpu_temp_crit_threshold_c"])

    def test_thermal_guard_state_directory_is_created(self) -> None:
        tasks = load_yaml(MONITORING_DIR / "tasks" / "main.yml")
        dirs = []
        for task in tasks:
            if not isinstance(task, dict) or task.get("ansible.builtin.file") is None:
                continue
            loop = task.get("loop")
            if isinstance(loop, list):
                dirs.extend(str(e) for e in loop)
        self.assertIn("{{ monitoring_gpu_temp_state_dir }}", dirs)
        self.assertIn("{{ monitoring_config_dir }}", dirs)


class DriftArtifactContractTests(unittest.TestCase):
    def test_drift_check_emits_machine_readable_status(self) -> None:
        text = (REPO_ROOT / "playbooks" / "drift-check.yml").read_text(encoding="utf-8")
        self.assertIn("drift-status.json", text)
        self.assertIn("schema_version", text)
        self.assertIn("classification", text)

    def test_drift_check_uses_honest_classifier_filter(self) -> None:
        text = (REPO_ROOT / "playbooks" / "drift-check.yml").read_text(encoding="utf-8")
        self.assertIn("aihost_drift_classify", text)

    def test_drift_check_alerts_operator_on_blocking_or_unknown_drift(self) -> None:
        text = (REPO_ROOT / "playbooks" / "drift-check.yml").read_text(encoding="utf-8")
        self.assertIn("Notify operator on blocking or indeterminate drift", text)
        self.assertIn("drift_classification in ['blocking_drift', 'unknown_drift']", text)
        self.assertIn("local-ai-alert", text)
        self.assertIn("aihost-drift-check", text)

    def test_drift_check_artifacts_record_evidence_presence(self) -> None:
        text = (REPO_ROOT / "playbooks" / "drift-check.yml").read_text(encoding="utf-8")
        self.assertIn("validation_evidence_present", text)


class DriftClassifierContractTests(unittest.TestCase):
    def _classify(self, document: object, numa: object = "PASS") -> str:
        spec = importlib.util.spec_from_file_location(
            "aihost_validators_drift_under_test",
            REPO_ROOT / "filter_plugins" / "aihost_validators.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return module.drift_classify(document, numa)

    def test_blocked_validation_is_blocking_drift(self) -> None:
        self.assertEqual("blocking_drift", self._classify({"status": "BLOCKED"}))
        self.assertEqual("blocking_drift", self._classify({"status": "BLOCKED"}, numa="FAIL"))

    def test_failed_validation_is_unresolved_drift(self) -> None:
        self.assertEqual("unresolved_drift", self._classify({"status": "FAIL"}))
        self.assertEqual("unresolved_drift", self._classify({"status": "PASS"}, numa="FAIL"))

    def test_missing_or_not_tested_validation_is_unknown_drift(self) -> None:
        self.assertEqual("unknown_drift", self._classify({"status": "NOT_TESTED"}))
        self.assertEqual("unknown_drift", self._classify({}))
        self.assertEqual("unknown_drift", self._classify(None))
        self.assertEqual("unknown_drift", self._classify("not-a-document"))

    def test_passing_validation_is_no_drift(self) -> None:
        self.assertEqual("no_drift", self._classify({"status": "PASS"}))

    def test_unknown_is_never_reported_as_no_drift(self) -> None:
        self.assertNotEqual("no_drift", self._classify({"status": "NOT_TESTED"}))
        self.assertNotEqual("no_drift", self._classify({}))


if __name__ == "__main__":
    unittest.main()
