from __future__ import annotations

import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]

PLAYBOOKS = {
    "bootstrap": REPO_ROOT / "playbooks" / "bootstrap.yml",
    "baseline": REPO_ROOT / "playbooks" / "baseline.yml",
    "site": REPO_ROOT / "playbooks" / "site.yml",
}

ROLE_ROOT = REPO_ROOT / "roles"
ROLE_NAMES = ("base_os", "time_sync", "storage", "networking", "users", "ssh", "security")

CONTROL_KEYS = {
    "name",
    "when",
    "tags",
    "vars",
    "register",
    "notify",
    "become",
    "changed_when",
    "failed_when",
    "check_mode",
    "delegate_to",
    "run_once",
    "loop",
    "loop_control",
    "with_items",
    "with_dict",
    "with_list",
    "args",
    "environment",
    "block",
    "rescue",
    "always",
}


def load_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def task_module_name(task: dict[str, object]) -> str | None:
    for key in task:
        if key not in CONTROL_KEYS:
            return key
    return None


def load_role_yaml(role: str, relpath: str) -> object:
    return load_yaml(ROLE_ROOT / role / relpath)


class BaselineContractTests(unittest.TestCase):
    maxDiff = None

    def test_bootstrap_and_baseline_playbooks_compose_expected_roles(self) -> None:
        bootstrap = load_yaml(PLAYBOOKS["bootstrap"])
        baseline = load_yaml(PLAYBOOKS["baseline"])
        site = load_yaml(PLAYBOOKS["site"])

        bootstrap_text = read_text(PLAYBOOKS["bootstrap"])
        baseline_text = read_text(PLAYBOOKS["baseline"])
        site_text = read_text(PLAYBOOKS["site"])

        self.assertIsInstance(bootstrap, list)
        self.assertIsInstance(baseline, list)
        self.assertIsInstance(site, list)

        for playbook_name, text in (("bootstrap", bootstrap_text), ("baseline", baseline_text), ("site", site_text)):
            self.assertNotIn("scaffold", text, f"{playbook_name} playbook still contains scaffold placeholder text")

        for required in ("base_os", "time_sync", "users", "ssh"):
            self.assertIn(required, bootstrap_text)

        for required in ROLE_NAMES:
            self.assertIn(required, baseline_text)

        self.assertIn("bootstrap", bootstrap_text)
        self.assertIn("baseline", baseline_text)
        self.assertIn("security", baseline_text)
        self.assertIn("network", baseline_text)
        self.assertIn("storage", baseline_text)
        self.assertIn("features.", site_text)
        self.assertIn("capabilities.", site_text)

    def test_base_os_role_covers_ubuntu_apt_and_logging_controls(self) -> None:
        defaults = load_role_yaml("base_os", "defaults/main.yml")
        tasks = read_text(ROLE_ROOT / "base_os" / "tasks" / "main.yml")
        sources_template = read_text(ROLE_ROOT / "base_os" / "templates" / "aihost-baseline.sources.j2")

        self.assertIsInstance(defaults, dict)
        self.assertEqual("Ubuntu", defaults.get("base_os_supported_distribution"))
        self.assertEqual("24.04", defaults.get("base_os_supported_release"))
        self.assertEqual(False, defaults.get("base_os_manage_installer_sources"))
        self.assertEqual(["amd64"], defaults.get("base_os_apt_architectures"))
        self.assertIn("archive.ubuntu.com", " ".join(defaults.get("base_os_apt_uris", [])))
        self.assertIn("security.ubuntu.com", " ".join(defaults.get("base_os_apt_uris", [])))
        self.assertIn("unattended-upgrades", tasks)
        self.assertTrue(
            "deb822_repository" in tasks or ".sources.j2" in tasks,
            "base_os must manage deb822 sources via module or template",
        )
        self.assertIn("Signed-By", sources_template)
        self.assertIn("community.general.locale_gen", tasks)
        self.assertIn("community.general.timezone", tasks)
        self.assertIn("ansible.posix.sysctl", tasks)
        self.assertIn("ansible.builtin.dpkg_selections", tasks)
        self.assertNotIn("upgrade: dist", tasks)
        self.assertNotIn("upgrade: full", tasks)

    def test_time_sync_storage_and_networking_roles_are_safe_by_default(self) -> None:
        time_sync_defaults = load_role_yaml("time_sync", "defaults/main.yml")
        time_sync_tasks = read_text(ROLE_ROOT / "time_sync" / "tasks" / "main.yml")
        storage_defaults = load_role_yaml("storage", "defaults/main.yml")
        storage_tasks = read_text(ROLE_ROOT / "storage" / "tasks" / "main.yml")
        networking_defaults = load_role_yaml("networking", "defaults/main.yml")
        networking_tasks = read_text(ROLE_ROOT / "networking" / "tasks" / "main.yml")

        self.assertEqual("systemd-timesyncd", time_sync_defaults.get("time_sync_provider"))
        self.assertIn("chrony", time_sync_defaults.get("time_sync_supported_providers", []))
        self.assertIn("systemd-timesyncd", time_sync_tasks)
        self.assertIn("chrony", time_sync_tasks)

        self.assertEqual([], storage_defaults.get("storage_mounts"))
        self.assertIn("ansible.posix.mount", storage_tasks)
        self.assertNotIn("community.general.filesystem", storage_tasks)
        self.assertNotIn("community.general.parted", storage_tasks)

        self.assertEqual(False, networking_defaults.get("networking_manage_netplan"))
        self.assertEqual(False, networking_defaults.get("networking_apply"))
        self.assertIn("netplan", networking_tasks)
        self.assertIn("generate", networking_tasks)
        self.assertIn("networking_allow_ssh_disruption", networking_tasks)

    def test_users_and_ssh_roles_enforce_key_based_access_and_lockout_guards(self) -> None:
        users_defaults = load_role_yaml("users", "defaults/main.yml")
        users_tasks = read_text(ROLE_ROOT / "users" / "tasks" / "main.yml")
        ssh_defaults = load_role_yaml("ssh", "defaults/main.yml")
        ssh_tasks = read_text(ROLE_ROOT / "ssh" / "tasks" / "main.yml")
        ssh_handlers = read_text(ROLE_ROOT / "ssh" / "handlers" / "main.yml")
        ssh_template = read_text(ROLE_ROOT / "ssh" / "templates" / "60-aihost-hardening.conf.j2")

        self.assertIn("users_service_accounts", users_defaults)
        self.assertIn("users_operator_accounts", users_defaults)
        self.assertIn("ansible.posix.authorized_key", users_tasks)
        self.assertIn("ansible.builtin.user", users_tasks)
        self.assertNotIn("password:", users_tasks)

        self.assertEqual(False, ssh_defaults.get("ssh_disable_password_auth"))
        self.assertIn("authorized_keys", ssh_tasks)
        self.assertIn("PasswordAuthentication", ssh_template)
        self.assertIn("assert", ssh_tasks)
        self.assertIn("validate:", ssh_tasks)
        self.assertIn("sshd -t", ssh_handlers)
        self.assertNotIn("Ciphers", ssh_template)
        self.assertNotIn("KexAlgorithms", ssh_template)

    def test_security_role_implements_firewall_auditd_and_validated_sudoers(self) -> None:
        security_defaults = load_role_yaml("security", "defaults/main.yml")
        security_tasks = read_text(ROLE_ROOT / "security" / "tasks" / "main.yml")
        security_handlers = read_text(ROLE_ROOT / "security" / "handlers" / "main.yml")
        controls_doc = REPO_ROOT / "docs" / "security-controls.md"
        security_defaults_text = read_text(ROLE_ROOT / "security" / "defaults" / "main.yml")

        self.assertEqual(False, security_defaults.get("security_firewall_enabled"))
        self.assertIn("auditd", security_tasks)
        self.assertIn("community.general.ufw", security_tasks)
        self.assertIn("visudo -cf", security_defaults_text)
        self.assertIn("ansible.posix.sysctl", security_tasks)
        self.assertIn("reload ufw", security_handlers.lower())
        self.assertTrue(controls_doc.exists(), "Expected docs/security-controls.md to exist")
        controls_text = read_text(controls_doc)
        for token in ("render", "video", "mlock", "firewall", "audit"):
            self.assertIn(token, controls_text)

    def test_baseline_roles_avoid_shell_and_keep_command_usage_narrow(self) -> None:
        for role in ROLE_NAMES:
            tasks = load_role_yaml(role, "tasks/main.yml")
            handlers = load_role_yaml(role, "handlers/main.yml")
            for section_name, items in (("tasks", tasks), ("handlers", handlers)):
                self.assertIsInstance(items, list, f"{role} {section_name} must be a YAML list")
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    module_name = task_module_name(item)
                    self.assertNotEqual("ansible.builtin.shell", module_name, f"{role} must not use shell")
                    self.assertNotIn("ignore_errors", item, f"{role} must not use ignore_errors")
                    if module_name == "ansible.builtin.command":
                        self.assertIn(
                            "changed_when",
                            item,
                            f"{role} command tasks must declare changed_when",
                        )
                        self.assertEqual(
                            False,
                            item["changed_when"],
                            f"{role} command tasks must be probes or validators only",
                        )
                        self.assertRegex(
                            str(item.get("name", "")),
                            r"(Validate|Check|Inspect|Probe|Generate)",
                            f"{role} command task names must explain their reason",
                        )

    def test_local_check_and_idempotency_paths_are_honest_and_repo_local(self) -> None:
        makefile = read_text(REPO_ROOT / "Makefile")
        scenario_path = REPO_ROOT / "tests" / "integration" / "baseline.yml"
        self.assertTrue(scenario_path.exists(), "Expected tests/integration/baseline.yml to exist")
        self.assertIn("tests/integration/baseline.yml", makefile)
        self.assertIn("localhost-safe", makefile)
        self.assertIn("Ubuntu 24.04", read_text(scenario_path))
        self.assertIn("check_mode", read_text(scenario_path))
        self.assertIn("does not assert host convergence", makefile)


if __name__ == "__main__":
    unittest.main()
