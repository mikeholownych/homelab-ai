from __future__ import annotations

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


class DriftArtifactContractTests(unittest.TestCase):
    def test_drift_check_emits_machine_readable_status(self) -> None:
        text = (REPO_ROOT / "playbooks" / "drift-check.yml").read_text(encoding="utf-8")
        self.assertIn("drift-status.json", text)
        for classification in ("blocking_drift", "unresolved_drift", "no_drift"):
            self.assertIn(classification, text)


if __name__ == "__main__":
    unittest.main()
