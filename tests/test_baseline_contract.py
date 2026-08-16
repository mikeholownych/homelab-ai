from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import tempfile
import textwrap
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


def ansible_playbook_bin() -> str:
    candidate = REPO_ROOT / ".venv" / "bin" / "ansible-playbook"
    if candidate.exists():
        return str(candidate)
    discovered = shutil.which("ansible-playbook")
    if discovered:
        return discovered
    raise AssertionError("ansible-playbook is required for localhost role probes")


def make_probe_workspace() -> Path:
    return Path(tempfile.mkdtemp(prefix="aihost-baseline-probe-"))


def load_filter_module():
    module_path = REPO_ROOT / "filter_plugins" / "aihost_validators.py"
    spec = importlib.util.spec_from_file_location("aihost_validators", module_path)
    if spec is None or spec.loader is None:
        raise AssertionError("Unable to load aihost_validators filter plugin")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_local_role_probe(
    playbook_text: str,
    *,
    workspace: Path | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    if workspace is None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            return run_local_role_probe(playbook_text, workspace=temp_root, check=check)

    playbook_path = workspace / "probe.yml"
    playbook_path.write_text(playbook_text, encoding="utf-8")
    env = os.environ.copy()
    env["ANSIBLE_CONFIG"] = str(REPO_ROOT / "ansible.cfg")
    env["ANSIBLE_ROLES_PATH"] = str(REPO_ROOT / "roles")
    command = [
        ansible_playbook_bin(),
        "-i",
        str(REPO_ROOT / "tests" / "fixtures" / "inventory" / "healthy.yml"),
    ]
    if check:
        command.append("--check")
    command.append(str(playbook_path))
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


class BaselineContractTests(unittest.TestCase):
    maxDiff = None

    def test_bootstrap_baseline_and_site_playbooks_compose_expected_roles(self) -> None:
        bootstrap_text = read_text(PLAYBOOKS["bootstrap"])
        baseline_text = read_text(PLAYBOOKS["baseline"])
        site_text = read_text(PLAYBOOKS["site"])

        for playbook_name, text in (
            ("bootstrap", bootstrap_text),
            ("baseline", baseline_text),
            ("site", site_text),
        ):
            self.assertNotIn("scaffold", text, f"{playbook_name} playbook still contains scaffold placeholder text")

        for required in ("base_os", "time_sync", "users", "ssh"):
            self.assertIn(required, bootstrap_text)
        self.assertNotIn("security", bootstrap_text)
        self.assertIn("bootstrap", bootstrap_text)
        self.assertIn("users", bootstrap_text)
        self.assertIn("ssh", bootstrap_text)

        for required in ROLE_NAMES:
            self.assertIn(required, baseline_text)
        self.assertIn("baseline", baseline_text)
        self.assertIn("security", baseline_text)
        self.assertIn("storage_mounts", baseline_text)
        self.assertIn("networking_manage_netplan", baseline_text)

        self.assertIn("import_playbook: baseline.yml", site_text)
        self.assertIn("features.", site_text)
        self.assertIn("capabilities.", site_text)
        self.assertNotIn("tags_identity", site_text)

    def test_users_ssh_and_security_defaults_are_safe_and_explicit(self) -> None:
        users_defaults = load_role_yaml("users", "defaults/main.yml")
        users_tasks = read_text(ROLE_ROOT / "users" / "tasks" / "main.yml")
        ssh_defaults = load_role_yaml("ssh", "defaults/main.yml")
        ssh_tasks = read_text(ROLE_ROOT / "ssh" / "tasks" / "main.yml")
        ssh_template = read_text(ROLE_ROOT / "ssh" / "templates" / "60-aihost-hardening.conf.j2")
        ssh_handlers = read_text(ROLE_ROOT / "ssh" / "handlers" / "main.yml")
        security_defaults = load_role_yaml("security", "defaults/main.yml")
        security_tasks = read_text(ROLE_ROOT / "security" / "tasks" / "main.yml")
        security_handlers = read_text(ROLE_ROOT / "security" / "handlers" / "main.yml")
        sudoers_template = read_text(ROLE_ROOT / "security" / "templates" / "90-aihost-operators.sudoers.j2")
        auditd_template = read_text(ROLE_ROOT / "security" / "templates" / "60-aihost-baseline.rules.j2")
        controls_doc = read_text(REPO_ROOT / "docs" / "security-controls.md")

        self.assertEqual([], users_defaults.get("operator_users"))
        self.assertEqual("lock", users_defaults.get("users_disabled_operator_state"))
        self.assertEqual(False, users_defaults.get("users_local_ai_manage_device_groups"))
        self.assertEqual("local-ai", users_defaults.get("users_local_ai_service_account", {}).get("name"))
        self.assertEqual("/usr/sbin/nologin", users_defaults.get("users_local_ai_service_account", {}).get("shell"))
        self.assertIn("ssh_authorized_keys", users_tasks)
        self.assertIn("sudo_passwordless_all", users_tasks)
        self.assertIn("sudo_commands", users_tasks)
        self.assertNotIn("password:", users_tasks)

        self.assertEqual(False, ssh_defaults.get("ssh_disable_password_auth"))
        self.assertEqual("no", ssh_defaults.get("ssh_permit_root_login"))
        self.assertEqual(False, ssh_defaults.get("ssh_kbd_interactive_authentication"))
        self.assertEqual(False, ssh_defaults.get("ssh_x11_forwarding"))
        self.assertIn("operator_users", ssh_tasks)
        self.assertIn("authorized_keys", ssh_tasks)
        self.assertIn("slurp", ssh_tasks)
        self.assertIn("sshd -t", str(ssh_defaults.get("ssh_validate_command")))
        self.assertIn("Include=", str(ssh_defaults.get("ssh_validate_command")))
        self.assertIn("PasswordAuthentication", ssh_template)
        self.assertIn("PermitEmptyPasswords no", ssh_template)
        self.assertIn("ChallengeResponseAuthentication no", ssh_template)
        self.assertIn("state: reloaded", ssh_handlers)
        self.assertNotIn("state: restarted", ssh_handlers)

        self.assertEqual(False, security_defaults.get("security_firewall_enabled"))
        self.assertEqual([], security_defaults.get("security_management_cidrs"))
        self.assertEqual(False, security_defaults.get("security_inference_api_firewall_enabled"))
        self.assertEqual([], security_defaults.get("security_inference_api_ports"))
        self.assertIn("community.general.ufw", security_tasks)
        self.assertIn("visudo -cf %s", str(security_defaults.get("security_sudoers_validate_command")))
        self.assertIn("operator_users", sudoers_template)
        self.assertIn("NOPASSWD:ALL", sudoers_template)
        self.assertIn("/etc/ssh/sshd_config.d", auditd_template)
        self.assertIn("auditd", security_handlers)
        self.assertNotIn("CIS", controls_doc)
        for token in (
            "render",
            "video",
            "DeviceAllow",
            "mlock",
            "OpenAI API",
            "audit overhead",
            "SSH forwarding",
            "unattended upgrades",
        ):
            self.assertIn(token, controls_doc)

    def test_networking_base_os_and_security_validation_contracts_fail_before_mutation(self) -> None:
        networking_defaults = load_role_yaml("networking", "defaults/main.yml")
        networking_tasks = read_text(ROLE_ROOT / "networking" / "tasks" / "main.yml")
        networking_handlers = read_text(ROLE_ROOT / "networking" / "handlers" / "main.yml")
        base_os_defaults = load_role_yaml("base_os", "defaults/main.yml")
        base_os_tasks = read_text(ROLE_ROOT / "base_os" / "tasks" / "main.yml")
        base_os_handlers = read_text(ROLE_ROOT / "base_os" / "handlers" / "main.yml")
        base_os_logrotate_template = read_text(ROLE_ROOT / "base_os" / "templates" / "aihost-logrotate.j2")
        security_tasks = read_text(ROLE_ROOT / "security" / "tasks" / "main.yml")
        security_handlers = read_text(ROLE_ROOT / "security" / "handlers" / "main.yml")

        self.assertEqual("networkd", networking_defaults.get("networking_renderer"))
        self.assertIn("networking_staging_root", networking_tasks)
        self.assertIn("--root-dir", networking_tasks)
        self.assertIn("check_mode: false", networking_tasks)
        self.assertLess(networking_tasks.index("networking_staging_root"), networking_tasks.index("networking_netplan_file"))
        self.assertLess(networking_tasks.index("Validate staged netplan configuration"), networking_tasks.index("Install validated netplan configuration"))
        self.assertNotIn("notify:", networking_tasks.split("Validate staged netplan configuration", 1)[0])
        self.assertIn("networking_apply | bool", networking_handlers)

        self.assertEqual(False, base_os_defaults.get("base_os_manage_boot_parameters"))
        self.assertEqual([], base_os_defaults.get("base_os_boot_parameters"))
        self.assertIn("base_os_grub_dropin_path", base_os_tasks)
        self.assertIn("update-grub", base_os_handlers)
        self.assertIn("logrotate --debug", str(base_os_defaults.get("base_os_logrotate_validate_command")))
        self.assertEqual(["/var/log/local-ai/*.log"], base_os_defaults.get("base_os_logrotate_paths"))
        self.assertNotIn("/var/log/*.log", base_os_logrotate_template)
        self.assertNotIn("sysctl --system", base_os_handlers)
        self.assertIn("base_os_update_grub_command", base_os_handlers)

        self.assertLess(
            security_tasks.index("Allow SSH only from configured management CIDRs"),
            security_tasks.index("Allow inference API only from configured CIDRs"),
        )
        self.assertLess(
            security_tasks.index("Allow inference API only from configured CIDRs"),
            security_tasks.index("Set UFW default deny incoming policy"),
        )
        self.assertLess(
            security_tasks.index("Set UFW default allow outgoing policy"),
            security_tasks.index("Enable managed UFW policy"),
        )
        self.assertIn("security_management_cidrs_invalid", security_tasks)
        self.assertIn("security_inference_api_ports_invalid", security_tasks)
        self.assertNotIn("sysctl --system", security_handlers)
        self.assertIn("aihost_invalid_logrotate_paths", read_text(REPO_ROOT / "filter_plugins" / "aihost_validators.py"))

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
        for required in ("base_os", "time_sync", "storage", "networking"):
            self.assertIn(required, scenario_text)
        self.assertIn("does not assert host convergence", makefile)

    def test_staged_netplan_validation_fails_before_destination_mutation_even_in_check_mode(self) -> None:
        workspace = make_probe_workspace()
        try:
            destination_path = workspace / "root" / "etc" / "netplan" / "60-aihost.yaml"
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            destination_path.write_text("sentinel: keep\n", encoding="utf-8")
            playbook_text = textwrap.dedent(
                """
                ---
                - name: Networking staged validation negative probe
                  hosts: localhost
                  connection: local
                  gather_facts: false
                  become: false
                  vars:
                    networking_root_dir: "{{ playbook_dir }}/root"
                    networking_staging_root: "{{ playbook_dir }}/staging"
                    networking_manage_runtime: true
                    networking_manage_netplan: true
                    networking_apply: false
                    networking_renderer: networkd
                    networking_netplan_binary: "{{ playbook_dir }}/bin/netplan"
                    networking_ethernets:
                      eno1:
                        dhcp4: true
                        gateway4: 300.0.0.1
                  pre_tasks:
                    - name: Create staged netplan probe directories
                      ansible.builtin.file:
                        path: "{{ item }}"
                        state: directory
                        mode: "0755"
                      loop:
                        - "{{ playbook_dir }}/bin"
                        - "{{ playbook_dir }}/root/etc/netplan"
                        - "{{ playbook_dir }}/staging"
                      check_mode: false
                    - name: Install fake netplan validator
                      ansible.builtin.copy:
                        dest: "{{ playbook_dir }}/bin/netplan"
                        mode: "0755"
                        content: |
                          #!/bin/sh
                          root_dir=""
                          prev=""
                          for arg in "$@"; do
                            if [ "$prev" = "--root-dir" ]; then
                              root_dir="$arg"
                            fi
                            prev="$arg"
                          done
                          probe_file="$root_dir/etc/netplan/60-aihost.yaml"
                          if grep -q "gateway4: 300.0.0.1" "$probe_file"; then
                            echo "semantic netplan failure" >&2
                            exit 12
                          fi
                          exit 0
                      check_mode: false
                  tasks:
                    - name: Include networking role
                      ansible.builtin.include_role:
                        name: networking
                """
            )

            result = run_local_role_probe(playbook_text, workspace=workspace, check=True)
            self.assertNotEqual(0, result.returncode)
            self.assertIn("semantic netplan failure", result.stdout + result.stderr)
            self.assertEqual("sentinel: keep\n", destination_path.read_text(encoding="utf-8"))
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_invalid_firewall_cidr_fails_with_specific_message_before_ufw(self) -> None:
        playbook_text = textwrap.dedent(
            """
            ---
            - name: Security invalid CIDR probe
              hosts: localhost
              connection: local
              gather_facts: false
              become: false
              vars:
                security_root_dir: "{{ playbook_dir }}/root"
                security_manage_runtime: false
                security_firewall_enabled: true
                security_management_cidrs:
                  - 10.0.0.999/24
                security_auditd_enabled: false
                security_sudoers_validate_command: "/usr/bin/env true %s"
              pre_tasks:
                - name: Create security probe directories
                  ansible.builtin.file:
                    path: "{{ item }}"
                    state: directory
                    mode: "0755"
                  loop:
                    - "{{ playbook_dir }}/root/etc"
                    - "{{ playbook_dir }}/root/etc/sudoers.d"
                    - "{{ playbook_dir }}/root/etc/audit/rules.d"
              tasks:
                - name: Include security role
                  ansible.builtin.include_role:
                    name: security
            """
        )

        result = run_local_role_probe(playbook_text)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("security_management_cidrs must contain valid CIDR networks", result.stdout + result.stderr)

    def test_invalid_firewall_port_fails_with_specific_message_before_ufw(self) -> None:
        playbook_text = textwrap.dedent(
            """
            ---
            - name: Security invalid port probe
              hosts: localhost
              connection: local
              gather_facts: false
              become: false
              vars:
                security_root_dir: "{{ playbook_dir }}/root"
                security_manage_runtime: false
                security_firewall_enabled: true
                security_management_cidrs:
                  - 10.0.0.0/24
                security_inference_api_firewall_enabled: true
                security_inference_api_cidrs:
                  - 10.1.0.0/24
                security_inference_api_ports:
                  - "22"
                security_auditd_enabled: false
                security_sudoers_validate_command: "/usr/bin/env true %s"
              pre_tasks:
                - name: Create security probe directories
                  ansible.builtin.file:
                    path: "{{ item }}"
                    state: directory
                    mode: "0755"
                  loop:
                    - "{{ playbook_dir }}/root/etc"
                    - "{{ playbook_dir }}/root/etc/sudoers.d"
                    - "{{ playbook_dir }}/root/etc/audit/rules.d"
              tasks:
                - name: Include security role
                  ansible.builtin.include_role:
                    name: security
            """
        )

        result = run_local_role_probe(playbook_text)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("security_inference_api_ports must be YAML integers between 1 and 65535", result.stdout + result.stderr)

    def test_port_and_logrotate_filters_reject_invalid_values(self) -> None:
        validators = load_filter_module()
        self.assertEqual(
            ["True", "1.5", "22", "0", "65536"],
            validators.invalid_ports([True, 1.5, "22", 0, 65536, 22]),
        )
        self.assertEqual(
            ["/var/log/local-ai/../auth.log", "relative.log", "/var/log/*.log"],
            validators.invalid_logrotate_paths(
                [
                    "/var/log/local-ai/app.log",
                    "/var/log/local-ai/*.log",
                    "/var/log/local-ai/../auth.log",
                    "relative.log",
                    "/var/log/*.log",
                ]
            ),
        )

    def test_invalid_logrotate_escape_path_fails_with_specific_message(self) -> None:
        playbook_text = textwrap.dedent(
            """
            ---
            - name: Base OS invalid logrotate path probe
              hosts: localhost
              connection: local
              gather_facts: true
              become: false
              vars:
                baseline_skip_platform_guard: true
                base_os_root_dir: "{{ playbook_dir }}/root"
                base_os_mutating_operations_enabled: false
                base_os_logrotate_validate_command: "/usr/bin/env true %s"
                base_os_logrotate_paths:
                  - /var/log/local-ai/../auth.log
              pre_tasks:
                - name: Create base OS probe directories
                  ansible.builtin.file:
                    path: "{{ item }}"
                    state: directory
                    mode: "0755"
                  loop:
                    - "{{ playbook_dir }}/root/etc"
                    - "{{ playbook_dir }}/root/etc/apt"
                    - "{{ playbook_dir }}/root/etc/apt/apt.conf.d"
                    - "{{ playbook_dir }}/root/etc/apt/preferences.d"
                    - "{{ playbook_dir }}/root/etc/apt/sources.list.d"
                    - "{{ playbook_dir }}/root/etc/default"
                    - "{{ playbook_dir }}/root/etc/logrotate.d"
                    - "{{ playbook_dir }}/root/etc/systemd"
                    - "{{ playbook_dir }}/root/etc/systemd/journald.conf.d"
              tasks:
                - name: Include base OS role
                  ansible.builtin.include_role:
                    name: base_os
            """
        )

        result = run_local_role_probe(playbook_text)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("base_os_logrotate_paths must stay within /var/log/local-ai", result.stdout + result.stderr)

    def test_boot_parameter_probe_writes_validated_dropin_only_when_enabled(self) -> None:
        workspace = make_probe_workspace()
        try:
            playbook_text = textwrap.dedent(
                """
                ---
                - name: Base OS boot parameter probe
                  hosts: localhost
                  connection: local
                  gather_facts: true
                  become: false
                  vars:
                    baseline_skip_platform_guard: true
                    base_os_root_dir: "{{ playbook_dir }}/root"
                    base_os_mutating_operations_enabled: false
                    base_os_manage_boot_parameters: true
                    base_os_boot_parameters:
                      - intel_iommu=on
                      - iommu=pt
                    base_os_logrotate_validate_command: "/usr/bin/env true %s"
                    base_os_grub_shell_validate_command: "/usr/bin/env true %s"
                  pre_tasks:
                    - name: Create base OS probe directories
                      ansible.builtin.file:
                        path: "{{ item }}"
                        state: directory
                        mode: "0755"
                      loop:
                        - "{{ playbook_dir }}/root/etc"
                        - "{{ playbook_dir }}/root/etc/apt"
                        - "{{ playbook_dir }}/root/etc/apt/apt.conf.d"
                        - "{{ playbook_dir }}/root/etc/apt/preferences.d"
                        - "{{ playbook_dir }}/root/etc/apt/sources.list.d"
                        - "{{ playbook_dir }}/root/etc/default"
                        - "{{ playbook_dir }}/root/etc/default/grub.d"
                        - "{{ playbook_dir }}/root/etc/logrotate.d"
                        - "{{ playbook_dir }}/root/etc/systemd"
                        - "{{ playbook_dir }}/root/etc/systemd/journald.conf.d"
                  tasks:
                    - name: Include base OS role
                      ansible.builtin.include_role:
                        name: base_os
                """
            )

            result = run_local_role_probe(playbook_text, workspace=workspace)
            dropin_path = workspace / "root" / "etc" / "default" / "grub.d" / "90-aihost.cfg"
            self.assertEqual(0, result.returncode, msg=result.stdout + result.stderr)
            self.assertTrue(dropin_path.exists(), "Expected boot-parameter drop-in to be rendered when enabled")
            dropin_text = dropin_path.read_text(encoding="utf-8")
            self.assertIn("intel_iommu=on", dropin_text)
            self.assertIn("iommu=pt", dropin_text)
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_boot_parameter_disable_removes_dropin_and_invokes_update_grub(self) -> None:
        workspace = make_probe_workspace()
        try:
            dropin_path = workspace / "root" / "etc" / "default" / "grub.d" / "90-aihost.cfg"
            grub_marker = workspace / "update-grub.called"
            dropin_path.parent.mkdir(parents=True, exist_ok=True)
            dropin_path.write_text("legacy dropin\n", encoding="utf-8")
            playbook_text = textwrap.dedent(
                """
                ---
                - name: Base OS boot parameter removal probe
                  hosts: localhost
                  connection: local
                  gather_facts: true
                  become: false
                  vars:
                    baseline_skip_platform_guard: true
                    base_os_root_dir: "{{ playbook_dir }}/root"
                    base_os_mutating_operations_enabled: false
                    base_os_manage_boot_parameters: false
                    base_os_logrotate_validate_command: "/usr/bin/env true %s"
                    base_os_update_grub_manage_runtime: true
                    base_os_update_grub_command:
                      - /usr/bin/touch
                      - "{{ playbook_dir }}/update-grub.called"
                  pre_tasks:
                    - name: Create base OS probe directories
                      ansible.builtin.file:
                        path: "{{ item }}"
                        state: directory
                        mode: "0755"
                      loop:
                        - "{{ playbook_dir }}/root/etc"
                        - "{{ playbook_dir }}/root/etc/apt"
                        - "{{ playbook_dir }}/root/etc/apt/apt.conf.d"
                        - "{{ playbook_dir }}/root/etc/apt/preferences.d"
                        - "{{ playbook_dir }}/root/etc/apt/sources.list.d"
                        - "{{ playbook_dir }}/root/etc/default"
                        - "{{ playbook_dir }}/root/etc/default/grub.d"
                        - "{{ playbook_dir }}/root/etc/logrotate.d"
                        - "{{ playbook_dir }}/root/etc/systemd"
                        - "{{ playbook_dir }}/root/etc/systemd/journald.conf.d"
                  tasks:
                    - name: Include base OS role
                      ansible.builtin.include_role:
                        name: base_os
                """
            )

            result = run_local_role_probe(playbook_text, workspace=workspace)
            self.assertEqual(0, result.returncode, msg=result.stdout + result.stderr)
            self.assertFalse(dropin_path.exists(), "Expected disabled boot-parameter path to remove prior drop-in")
            self.assertTrue(grub_marker.exists(), "Expected disabled transition to invoke update-grub handler")
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def test_bootstrap_probe_succeeds_locally_with_password_auth_enabled(self) -> None:
        playbook_text = textwrap.dedent(
            """
            ---
            - name: Bootstrap localhost-safe access probe
              hosts: localhost
              connection: local
              gather_facts: true
              become: false
              vars:
                baseline_localhost_safe_mode: true
                baseline_skip_platform_guard: true
                base_os_root_dir: "{{ playbook_dir }}/root"
                base_os_mutating_operations_enabled: false
                base_os_logrotate_validate_command: "/usr/bin/env true %s"
                time_sync_root_dir: "{{ playbook_dir }}/root"
                time_sync_manage_runtime: false
                users_root_dir: "{{ playbook_dir }}/root"
                users_manage_runtime: false
                ssh_root_dir: "{{ playbook_dir }}/root"
                ssh_manage_runtime: false
                ssh_validate_command: "/usr/bin/env true %s"
                operator_users:
                  - name: ops
                    enabled: true
                    ssh_authorized_keys:
                      - ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAbootstrap bootstrap@example
                    sudo: false
                security_root_dir: "{{ playbook_dir }}/root"
                security_manage_runtime: false
                security_firewall_enabled: false
                security_auditd_enabled: false
                security_sudoers_validate_command: "/usr/bin/env true %s"
              pre_tasks:
                - name: Create localhost-safe probe root
                  ansible.builtin.file:
                    path: "{{ item }}"
                    state: directory
                    mode: "0755"
                  loop:
                    - "{{ playbook_dir }}/root"
                    - "{{ playbook_dir }}/root/etc"
                    - "{{ playbook_dir }}/root/etc/apt"
                    - "{{ playbook_dir }}/root/etc/apt/apt.conf.d"
                    - "{{ playbook_dir }}/root/etc/apt/preferences.d"
                    - "{{ playbook_dir }}/root/etc/apt/sources.list.d"
                    - "{{ playbook_dir }}/root/etc/default"
                    - "{{ playbook_dir }}/root/etc/systemd"
                    - "{{ playbook_dir }}/root/etc/systemd/journald.conf.d"
                    - "{{ playbook_dir }}/root/etc/systemd/timesyncd.conf.d"
                    - "{{ playbook_dir }}/root/etc/chrony"
                    - "{{ playbook_dir }}/root/etc/chrony/sources.d"
                    - "{{ playbook_dir }}/root/etc/ssh"
                    - "{{ playbook_dir }}/root/etc/ssh/sshd_config.d"
                    - "{{ playbook_dir }}/root/etc/sudoers.d"
              tasks:
                - name: Include base OS role
                  ansible.builtin.include_role:
                    name: base_os
                - name: Include time sync role
                  ansible.builtin.include_role:
                    name: time_sync
                - name: Include users role
                  ansible.builtin.include_role:
                    name: users
                - name: Include SSH role
                  ansible.builtin.include_role:
                    name: ssh
                - name: Include security role
                  ansible.builtin.include_role:
                    name: security
            """
        )

        result = run_local_role_probe(playbook_text)
        self.assertEqual(0, result.returncode, msg=result.stdout + result.stderr)

    def test_disabling_password_auth_without_managed_key_fails_with_lockout_message(self) -> None:
        playbook_text = textwrap.dedent(
            """
            ---
            - name: SSH lockout guard negative probe
              hosts: localhost
              connection: local
              gather_facts: false
              become: false
              vars:
                ssh_root_dir: "{{ playbook_dir }}/root"
                ssh_manage_runtime: false
                ssh_disable_password_auth: true
                ssh_validate_command: "/usr/bin/env true %s"
                operator_users:
                  - name: ops
                    enabled: true
                    ssh_authorized_keys:
                      - ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIAnegative negative@example
                    sudo: false
              pre_tasks:
                - name: Create empty localhost-safe SSH directories
                  ansible.builtin.file:
                    path: "{{ playbook_dir }}/root/etc/ssh/sshd_config.d"
                    state: directory
                    mode: "0755"
              tasks:
                - name: Include SSH role
                  ansible.builtin.include_role:
                    name: ssh
            """
        )

        result = run_local_role_probe(playbook_text)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("ssh_disable_password_auth=true requires at least one managed operator", result.stdout + result.stderr)

    def test_disabling_password_auth_with_temp_key_proof_succeeds_without_touching_etc(self) -> None:
        playbook_text = textwrap.dedent(
            """
            ---
            - name: SSH lockout guard positive probe
              hosts: localhost
              connection: local
              gather_facts: false
              become: false
              vars:
                ssh_root_dir: "{{ playbook_dir }}/root"
                ssh_manage_runtime: false
                ssh_disable_password_auth: true
                ssh_validate_command: "/usr/bin/env true %s"
                operator_users:
                  - name: ops
                    enabled: true
                    home: "{{ playbook_dir }}/root/home/ops"
                    ssh_authorized_keys:
                      - ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIApositive positive@example
                    sudo: false
              pre_tasks:
                - name: Create localhost-safe SSH tree
                  ansible.builtin.file:
                    path: "{{ item }}"
                    state: directory
                    mode: "0755"
                  loop:
                    - "{{ playbook_dir }}/root/etc/ssh/sshd_config.d"
                    - "{{ playbook_dir }}/root/home/ops/.ssh"
                - name: Write managed authorized_keys proof
                  ansible.builtin.copy:
                    dest: "{{ playbook_dir }}/root/home/ops/.ssh/authorized_keys"
                    mode: "0600"
                    content: |
                      ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIApositive positive@example
              tasks:
                - name: Include SSH role
                  ansible.builtin.include_role:
                    name: ssh
            """
        )

        result = run_local_role_probe(playbook_text)
        self.assertEqual(0, result.returncode, msg=result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
