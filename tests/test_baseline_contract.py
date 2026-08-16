from __future__ import annotations

import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]

PLAYBOOKS = {
    "baseline": REPO_ROOT / "playbooks" / "baseline.yml",
    "site": REPO_ROOT / "playbooks" / "site.yml",
}

ROLE_ROOT = REPO_ROOT / "roles"
ROLE_NAMES = ("base_os", "time_sync", "storage", "networking")

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

    def test_baseline_playbook_wires_only_task4a_roles_and_site_imports_it(self) -> None:
        baseline = load_yaml(PLAYBOOKS["baseline"])
        site = load_yaml(PLAYBOOKS["site"])

        baseline_text = read_text(PLAYBOOKS["baseline"])
        site_text = read_text(PLAYBOOKS["site"])

        self.assertIsInstance(baseline, list)
        self.assertIsInstance(site, list)

        for playbook_name, text in (("baseline", baseline_text), ("site", site_text)):
            self.assertNotIn("scaffold", text, f"{playbook_name} playbook still contains scaffold placeholder text")

        for required in ROLE_NAMES:
            self.assertIn(required, baseline_text)

        self.assertIn("baseline", baseline_text)
        self.assertIn("network", baseline_text)
        self.assertIn("storage", baseline_text)
        self.assertNotIn("users", baseline_text)
        self.assertNotIn("ssh", baseline_text)
        self.assertNotIn("security", baseline_text)
        self.assertIn("storage_mounts", baseline_text)
        self.assertIn("networking_manage_netplan", baseline_text)
        self.assertIn("import_playbook: baseline.yml", site_text)
        self.assertIn("features.", site_text)
        self.assertIn("capabilities.", site_text)

    def test_base_os_role_enforces_explicit_ubuntu_package_logging_and_kernel_controls(self) -> None:
        defaults = load_role_yaml("base_os", "defaults/main.yml")
        tasks = read_text(ROLE_ROOT / "base_os" / "tasks" / "main.yml")
        handlers = read_text(ROLE_ROOT / "base_os" / "handlers" / "main.yml")
        sources_template = read_text(ROLE_ROOT / "base_os" / "templates" / "aihost-baseline.sources.j2")

        self.assertIsInstance(defaults, dict)
        self.assertEqual("Ubuntu", defaults.get("base_os_supported_distribution"))
        self.assertEqual("24.04", defaults.get("base_os_supported_release"))
        self.assertEqual(False, defaults.get("base_os_manage_ubuntu_sources"))
        self.assertEqual(["amd64"], defaults.get("base_os_apt_architectures"))
        self.assertEqual("https://archive.ubuntu.com/ubuntu", defaults.get("base_os_archive_uri"))
        self.assertEqual("https://security.ubuntu.com/ubuntu", defaults.get("base_os_security_uri"))
        self.assertEqual(["noble", "noble-updates", "noble-backports", "noble-security"], defaults.get("base_os_apt_suites"))
        self.assertEqual(["main", "restricted", "universe", "multiverse"], defaults.get("base_os_apt_components"))
        self.assertEqual({}, defaults.get("base_os_kernel_sysctl"))
        self.assertEqual([], defaults.get("base_os_boot_parameters"))
        self.assertIn("base_os_manage_ubuntu_sources | bool", tasks)
        self.assertIn("URIs:", sources_template)
        self.assertIn("noble-security", sources_template)
        self.assertIn("Signed-By", sources_template)
        self.assertIn("community.general.locale_gen", tasks)
        self.assertIn("community.general.timezone", tasks)
        self.assertIn("ansible.posix.sysctl", tasks)
        self.assertIn("ansible.builtin.dpkg_selections", tasks)
        self.assertIn("base_os_allowed_sysctl", tasks)
        self.assertIn("base_os_high_risk_packages", tasks)
        self.assertIn("unattended-upgrades", tasks)
        self.assertIn("service_facts", tasks)
        self.assertIn("masked: true", tasks)
        self.assertIn("/usr/sbin/sysctl", handlers)
        self.assertIn("--system", handlers)
        self.assertNotIn("upgrade: dist", tasks)
        self.assertNotIn("upgrade: full", tasks)

    def test_time_sync_storage_and_networking_roles_are_safe_by_default(self) -> None:
        time_sync_defaults = load_role_yaml("time_sync", "defaults/main.yml")
        time_sync_tasks = read_text(ROLE_ROOT / "time_sync" / "tasks" / "main.yml")
        time_sync_handlers = read_text(ROLE_ROOT / "time_sync" / "handlers" / "main.yml")
        storage_defaults = load_role_yaml("storage", "defaults/main.yml")
        storage_tasks = read_text(ROLE_ROOT / "storage" / "tasks" / "main.yml")
        networking_defaults = load_role_yaml("networking", "defaults/main.yml")
        networking_tasks = read_text(ROLE_ROOT / "networking" / "tasks" / "main.yml")
        networking_handlers = read_text(ROLE_ROOT / "networking" / "handlers" / "main.yml")

        self.assertEqual("systemd-timesyncd", time_sync_defaults.get("time_sync_provider"))
        self.assertIn("chrony", time_sync_defaults.get("time_sync_supported_providers", []))
        self.assertIn("systemd-timesyncd", time_sync_tasks)
        self.assertIn("chrony", time_sync_tasks)
        self.assertIn("not ansible_check_mode", time_sync_tasks)
        self.assertIn("enabled: false", time_sync_tasks)
        self.assertIn("state: stopped", time_sync_tasks)
        self.assertIn("state: restarted", time_sync_handlers)

        self.assertEqual([], storage_defaults.get("storage_mounts"))
        self.assertIn("ansible.posix.mount", storage_tasks)
        self.assertIn("LABEL=", storage_tasks)
        self.assertNotIn("community.general.filesystem", storage_tasks)
        self.assertNotIn("community.general.parted", storage_tasks)

        self.assertEqual(False, networking_defaults.get("networking_manage_netplan"))
        self.assertEqual(False, networking_defaults.get("networking_apply"))
        self.assertIn("netplan", networking_tasks)
        self.assertIn("generate", networking_tasks)
        self.assertIn("networking_allow_ssh_disruption", networking_tasks)
        self.assertIn("notify:", networking_tasks)
        self.assertIn("netplan", networking_handlers)
        self.assertIn("apply", networking_handlers)
        self.assertIn("not ansible_check_mode", networking_handlers)

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
                            r"(Validate|Check|Inspect|Probe|Generate|Apply)",
                            f"{role} command task names must explain their reason",
                        )

    def test_local_check_fixture_is_repo_local_and_honest(self) -> None:
        makefile = read_text(REPO_ROOT / "Makefile")
        scenario_path = REPO_ROOT / "tests" / "integration" / "baseline_os.yml"
        scenario_text = read_text(scenario_path)
        self.assertTrue(scenario_path.exists(), "Expected tests/integration/baseline_os.yml to exist")
        self.assertIn("tests/integration/baseline_os.yml", makefile)
        self.assertIn("localhost-safe", makefile)
        self.assertNotIn("idempotency probe", makefile)
        self.assertIn("Ubuntu 24.04", scenario_text)
        self.assertIn("check_mode: true", scenario_text)
        for required in ROLE_NAMES:
            self.assertIn(required, scenario_text)
        for deferred_role in ("users", "ssh", "security"):
            self.assertNotIn(deferred_role, scenario_text)
        self.assertIn("does not assert host convergence", makefile)


if __name__ == "__main__":
    unittest.main()
