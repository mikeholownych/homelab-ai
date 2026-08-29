from __future__ import annotations

import re
import unittest
from pathlib import Path

import jinja2
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

OBSERVABILITY_DIR = REPO_ROOT / "roles" / "observability"
DEFAULTS_PATH = OBSERVABILITY_DIR / "defaults" / "main.yml"
TASKS_PATH = OBSERVABILITY_DIR / "tasks" / "main.yml"
TEMPLATES_DIR = OBSERVABILITY_DIR / "templates"
SITE_PLAYBOOK = REPO_ROOT / "playbooks" / "site.yml"
GROUP_VARS = REPO_ROOT / "inventory" / "production" / "group_vars"


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def render_jinja_vars(template_text: str, context: dict) -> str:
    rendered = template_text
    for _ in range(3):
        if "{{" not in rendered:
            break
        rendered = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(
            rendered
        ).render(**context)
    return rendered


class ObservabilityRoleContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.defaults = load_yaml(DEFAULTS_PATH)
        self.tasks = load_yaml(TASKS_PATH)

    def test_role_layout_mirrors_monitoring(self) -> None:
        for name in (
            "defaults/main.yml",
            "tasks/main.yml",
            "handlers/main.yml",
            "meta/main.yml",
        ):
            self.assertTrue((OBSERVABILITY_DIR / name).is_file(), name)

    def test_fail_closed_by_default(self) -> None:
        self.assertFalse(self.defaults["observability_install_enabled"])
        self.assertEqual(
            "pre_verification_fail_closed",
            self.defaults["observability_stack_status"],
        )

    def test_verification_checklist_defaults_to_empty(self) -> None:
        self.assertEqual([], self.defaults["observability_verification_checklist"])

    def test_all_upstream_artifacts_hash_pinned(self) -> None:
        for name in ("alloy", "vm", "grafana", "loki"):
            self.assertIsInstance(
                self.defaults[f"observability_{name}_version"], str
            )
            self.assertNotEqual(
                "latest", self.defaults[f"observability_{name}_version"].lower()
            )
            sha256 = self.defaults[f"observability_{name}_sha256"]
            self.assertRegex(sha256, r"^[0-9a-f]{64}$", name)
            url = render_jinja_vars(
                self.defaults[f"observability_{name}_archive_url"],
                self.defaults,
            )
            self.assertTrue(url.startswith("https://"), name)

    def test_vmutils_tarball_hash_pinned_and_disabled_recording_rules(self) -> None:
        self.assertRegex(
            self.defaults["observability_vmutils_sha256"], r"^[0-9a-f]{64}$"
        )
        vmutils_url = render_jinja_vars(
            self.defaults["observability_vmutils_archive_url"], self.defaults
        )
        self.assertTrue(vmutils_url.startswith("https://"), vmutils_url)
        self.assertFalse(
            self.defaults["observability_vllm_recording_rules_enabled"]
        )

    def test_tasks_refuse_unverified_install_before_commissioning(self) -> None:
        refusal = next(
            task
            for task in self.tasks
            if task.get("name") == "Refuse unverified observability stack installation"
        )
        self.assertIn("ansible.builtin.fail", refusal)
        self.assertEqual(
            "{{ observability_install_blocker }}",
            refusal["ansible.builtin.fail"]["msg"],
        )
        self.assertTrue("observability_stack_status" in str(refusal["when"]))
        self.assertTrue("'commissioned'" in str(refusal["when"]))

    def test_tasks_download_each_artifact_with_checksum(self) -> None:
        download_tasks = [
            task
            for task in self.tasks
            if task.get("name", "").startswith("Download pinned")
        ]
        self.assertEqual(5, len(download_tasks))
        for task in download_tasks:
            get_url = task["ansible.builtin.get_url"]
            self.assertTrue(
                str(get_url["checksum"]).startswith("sha256:"),
                task["name"],
            )
            resolved_url = render_jinja_vars(get_url["url"], self.defaults)
            self.assertTrue(resolved_url.startswith("https://"), task["name"])

    def test_execution_tasks_are_check_mode_inert(self) -> None:
        execution_prefixes = ("Download pinned", "Extract ", "Verify extracted", "Enable and start")
        for task in self.tasks:
            if not task.get("name", "").startswith(execution_prefixes):
                continue
            self.assertIn("not ansible_check_mode", task["when"], task["name"])
        daemon_reload = next(
            task
            for task in self.tasks
            if task.get("name") == "Reload systemd for new observability units"
        )
        self.assertIn("not ansible_check_mode", daemon_reload["when"])

    def test_no_mutable_latest_or_dangerous_patterns_in_role(self) -> None:
        scanned = []
        for root in (OBSERVABILITY_DIR,):
            scanned.extend(p for p in root.rglob("*") if p.is_file())
        text_suffixes = {".yml", ".yaml", ".j2", ".service", ".py", ".sh", ".env"}
        for path in scanned:
            if path.suffix not in text_suffixes:
                continue
            content = path.read_text(encoding="utf-8")
            self.assertNotIn("$ANSIBLE_VAULT", content, path)
            self.assertNotRegex(content, r"(?i)\bcurl\b.*\|\s*(?:bash|sh)\b", path)
            self.assertNotRegex(content, r"(?i)\bwget\b.*\|\s*(?:bash|sh)\b", path)

    def test_alloy_config_scrapes_textfile_bridge(self) -> None:
        alloy = (TEMPLATES_DIR / "config.alloy.j2").read_text(encoding="utf-8")
        self.assertIn("prometheus.exporter.unix", alloy)
        self.assertIn("textfile", alloy)
        self.assertIn("observability_textfile_metrics_dir", alloy)
        self.assertIn("prometheus.remote_write", alloy)

    def test_recording_rules_template_contains_host_synthesis(self) -> None:
        rules = (TEMPLATES_DIR / "vmalert-recording-rules.yml.j2").read_text(
            encoding="utf-8"
        )
        self.assertIn("aihost:gpu_temperature_celsius:peak", rules)
        self.assertIn("aihost:gpu_thermal_severity:peak", rules)
        self.assertIn("observability_vllm_recording_rules_enabled", rules)

    def test_site_playbook_gates_observability_behind_feature(self) -> None:
        site = SITE_PLAYBOOK.read_text(encoding="utf-8")
        self.assertIn("name: observability", site)
        self.assertIn("features.observability", site)

    def test_host_observability_feature_defaults_disabled(self) -> None:
        hosts_dir = (
            REPO_ROOT / "inventory" / "production" / "host_vars"
        )
        for host_file in hosts_dir.iterdir():
            if host_file.suffix != ".yml":
                continue
            host_vars = load_yaml(host_file)
            self.assertIn("observability", host_vars["features"], host_file.name)
            self.assertFalse(host_vars["features"]["observability"], host_file.name)

    def test_group_vars_follow_vault_secret_path_convention(self) -> None:
        observability_vars = load_yaml(GROUP_VARS / "observability.yml")
        for secret_path in observability_vars["observability_secret_paths"].values():
            self.assertTrue(
                secret_path.startswith("secret/"), secret_path
            )

    def test_grafana_admin_password_never_committed(self) -> None:
        admin_env = (TEMPLATES_DIR / "grafana-admin.env.j2").read_text(
            encoding="utf-8"
        )
        self.assertIn("GF_SECURITY_ADMIN_PASSWORD", admin_env)
        self.assertIsNone(self.defaults["observability_grafana_admin_password"])

    def test_gate_check_integration_playbook_wired_into_make_check(self) -> None:
        gate = REPO_ROOT / "tests" / "integration" / "observability_gate_check.yml"
        self.assertTrue(gate.is_file())
        content = gate.read_text(encoding="utf-8")
        self.assertIn("observability_install_enabled: true", content)
        self.assertIn("observability_stack_status: commissioned", content)
        self.assertIn("ansible_check_mode", content)
        self.assertIn("observability_validation_status", content)
        self.assertIn("NOT_TESTED", content)
        makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("observability_gate_check.yml", makefile)
        self.assertIn("--check", makefile)


if __name__ == "__main__":
    unittest.main()