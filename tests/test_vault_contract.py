from __future__ import annotations

import grp
import os
import pwd
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
ROLE_ROOT = REPO_ROOT / "roles" / "vault_integration"
TASKS_ROOT = ROLE_ROOT / "tasks"
DEFAULTS_PATH = ROLE_ROOT / "defaults" / "main.yml"
BOOTSTRAP_PLAYBOOK = REPO_ROOT / "playbooks" / "bootstrap.yml"
SITE_PLAYBOOK = REPO_ROOT / "playbooks" / "site.yml"
REQUIREMENTS_YML = REPO_ROOT / "requirements.yml"
DOCS_PATH = REPO_ROOT / "docs" / "vault.md"
CURRENT_USER = pwd.getpwuid(os.getuid()).pw_name
CURRENT_GROUP = grp.getgrgid(os.getgid()).gr_name


def load_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_task_documents(path: Path) -> list[dict[str, object]]:
    data = load_yaml(path)
    if data is None:
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    raise AssertionError(f"Expected a task list in {path}")


def flatten_tasks(paths: list[Path]) -> list[dict[str, object]]:
    tasks: list[dict[str, object]] = []
    for path in paths:
        tasks.extend(load_task_documents(path))
    return tasks


def load_role_tasks() -> list[dict[str, object]]:
    return flatten_tasks(sorted(TASKS_ROOT.glob("*.yml")))


def load_role_text() -> str:
    return "\n".join(load_text(path) for path in sorted(TASKS_ROOT.glob("*.yml")))


def ansible_playbook_bin() -> str | None:
    candidate = REPO_ROOT / ".venv" / "bin" / "ansible-playbook"
    if candidate.exists():
        return str(candidate)
    return shutil.which("ansible-playbook")


def write_yaml(path: Path, data: object) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def run_probe_playbook(playbook: list[dict[str, object]], *, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    binary = ansible_playbook_bin()
    if binary is None:
        raise unittest.SkipTest("ansible-playbook is not available")
    with tempfile.TemporaryDirectory(prefix="aihost-vault-probe-") as tmpdir:
        temp_root = Path(tmpdir)
        playbook_path = temp_root / "probe.yml"
        write_yaml(playbook_path, playbook)
        env = os.environ.copy()
        env.update(
            {
                "ANSIBLE_CONFIG": str(REPO_ROOT / "ansible.cfg"),
                "ANSIBLE_ROLES_PATH": str(REPO_ROOT / "roles"),
            }
        )
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [
                binary,
                "-i",
                "localhost,",
                str(playbook_path),
                "-e",
                "ansible_connection=local",
                "-e",
                "ansible_python_interpreter=/usr/bin/python3",
            ],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )


def make_credentials(temp_root: Path) -> Path:
    credentials_dir = temp_root / "credentials"
    credentials_dir.mkdir()
    role_id = credentials_dir / "vault-role-id"
    secret_id = credentials_dir / "vault-secret-id"
    role_id.write_text("role-id-value\n", encoding="utf-8")
    secret_id.write_text("secret-id-value\n", encoding="utf-8")
    role_id.chmod(stat.S_IRUSR)
    secret_id.chmod(stat.S_IRUSR)
    return credentials_dir


def simulated_login_result() -> dict[str, object]:
    return {
        "login": {
            "auth": {
                "client_token": "simulated-token",
                "lease_duration": 900,
                "renewable": True,
                "policies": ["local-ai-runtime"],
                "token_policies": ["local-ai-runtime"],
            }
        }
    }


def simulated_secret_result() -> dict[str, object]:
    return {
        "secret": {"required": "value"},
        "metadata": {"version": 3, "created_time": "2026-08-17T00:00:00Z"},
    }


class VaultContractTests(unittest.TestCase):
    maxDiff = None

    def test_defaults_define_controller_env_lookup_and_safe_interface(self) -> None:
        defaults = load_yaml(DEFAULTS_PATH)
        defaults_text = load_text(DEFAULTS_PATH)
        self.assertIsInstance(defaults, dict)
        self.assertEqual(False, defaults.get("vault_integration_enabled"))
        self.assertEqual("approle", defaults.get("vault_integration_auth_method"))
        self.assertEqual(["approle"], defaults.get("vault_integration_auth_method_allowlist"))
        self.assertEqual("https://vault.example.invalid", defaults.get("vault_integration_addr"))
        self.assertEqual(None, defaults.get("vault_integration_namespace"))
        self.assertEqual("approle", defaults.get("vault_integration_auth_mount"))
        self.assertEqual("secret", defaults.get("vault_integration_kv2_mount"))
        self.assertEqual(True, defaults.get("vault_integration_validate_certs"))
        self.assertNotIn("vault_integration_allowed_secret_prefixes", defaults)
        self.assertIn("lookup('ansible.builtin.env', 'CREDENTIALS_DIRECTORY')", defaults_text)
        self.assertNotIn("ansible_env.CREDENTIALS_DIRECTORY", defaults_text)

    def test_requirements_pin_hashi_vault_collection(self) -> None:
        requirements = load_yaml(REQUIREMENTS_YML)
        self.assertIsInstance(requirements, dict)
        collections = requirements.get("collections", [])
        self.assertIn({"name": "community.hashi_vault", "version": "7.1.0"}, collections)

    def test_role_main_wraps_sensitive_runtime_with_always_cleanup(self) -> None:
        main_tasks = load_task_documents(TASKS_ROOT / "main.yml")
        block_tasks = [task for task in main_tasks if "block" in task]
        self.assertEqual(1, len(block_tasks), "Vault runtime flow should be wrapped in one cleanup block")
        block_task = block_tasks[0]
        self.assertIn("always", block_task)
        always_tasks = block_task["always"]
        self.assertEqual(1, len(always_tasks))
        self.assertEqual("cleanup.yml", always_tasks[0]["ansible.builtin.include_tasks"])

    def test_role_tasks_validate_fail_closed_tls_mounts_namespace_and_boundaries(self) -> None:
        role_text = load_role_text()
        required_tokens = (
            "vault_integration_validate_certs | bool",
            "vault_integration_allowed_secret_prefixes is not defined",
            "vault_integration_namespace is none",
            "vault_integration_auth_mount is match",
            "vault_integration_kv2_mount is match",
            "vault_integration_controller_ca_cert_stat",
            "vault_integration_secret_ref_normalized.startswith(",
            "vault_integration_kv2_mount ~ '/local-ai/'",
            "vault_integration_secret_path_segments[2] in ['shared', 'hosts', 'clusters', 'services']",
            "vault_integration_secret_path_segments[3] == inventory_hostname",
            "cluster.enabled | default(false) | bool",
            "delegate_to: localhost",
            "no_log: true",
        )
        for token in required_tokens:
            with self.subTest(token=token):
                self.assertIn(token, role_text)
        self.assertNotIn("ignore_errors:", role_text)
        self.assertNotIn("cacheable: true", role_text)

    def test_role_uses_vault_modules_with_no_log(self) -> None:
        login_tasks = []
        kv_tasks = []
        for task in load_role_tasks():
            if "community.hashi_vault.vault_login" in task:
                login_tasks.append(task)
            if "community.hashi_vault.vault_kv2_get" in task:
                kv_tasks.append(task)
        self.assertEqual(1, len(login_tasks), "Expected one AppRole login task")
        self.assertEqual(1, len(kv_tasks), "Expected one KVv2 runtime retrieval task")
        self.assertTrue(login_tasks[0].get("no_log"), "Vault login must set no_log: true")
        self.assertTrue(kv_tasks[0].get("no_log"), "Vault KVv2 reads must set no_log: true")

    def test_bootstrap_and_site_wire_vault_role_with_explicit_tags(self) -> None:
        bootstrap_tasks = load_task_documents(BOOTSTRAP_PLAYBOOK)
        site_tasks = load_task_documents(SITE_PLAYBOOK)
        bootstrap_vault = [
            task
            for task in bootstrap_tasks[0].get("tasks", [])
            if task.get("ansible.builtin.include_role", {}).get("name") == "vault_integration"
        ]
        site_vault = [
            task
            for task in site_tasks[1].get("tasks", [])
            if task.get("ansible.builtin.include_role", {}).get("name") == "vault_integration"
        ]
        self.assertEqual(1, len(bootstrap_vault))
        self.assertEqual(1, len(site_vault))
        self.assertIn("bootstrap", bootstrap_vault[0].get("tags", []))
        self.assertIn("vault", bootstrap_vault[0].get("tags", []))
        self.assertIn("vault", site_vault[0].get("tags", []))
        self.assertIn("vault_preflight", site_vault[0].get("name", ""))

    def test_vault_docs_use_exact_variable_names_and_operator_recovery_contract(self) -> None:
        docs_text = load_text(DOCS_PATH)
        required_tokens = (
            "vault_integration_enabled",
            "vault_integration_bootstrap_validate_credentials",
            "vault_integration_bootstrap_configure_references",
            "vault_integration_auth_method",
            "vault_integration_addr",
            "vault_integration_namespace",
            "vault_integration_auth_mount",
            "vault_integration_kv2_mount",
            "vault_integration_ca_cert_path",
            "systemd-creds",
            "LoadCredential=",
            "wrapping token",
            "vault unwrap",
            "install -m 0400",
            "response wrapping",
            "rotation",
            "revocation",
            "TLS",
            "Vault health",
            "policy restore",
            "community.hashi_vault.vault_login",
            "community.hashi_vault.vault_kv2_get",
            "read only",
            "metadata list only if needed",
            "plaintext fallback",
            "Ansible Vault",
        )
        for token in required_tokens:
            with self.subTest(token=token):
                self.assertIn(token, docs_text)

    def test_role_uses_controller_credentials_directory_lookup_instead_of_remote_ansible_env(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aihost-vault-cred-source-") as tmpdir:
            temp_root = Path(tmpdir)
            credentials_dir = make_credentials(temp_root)
            result = run_probe_playbook(
                [
                    {
                        "hosts": "localhost",
                        "gather_facts": False,
                        "vars": {
                            "ansible_env": {"CREDENTIALS_DIRECTORY": "/remote/fake-path"},
                        },
                        "tasks": [
                            {
                                "name": "Run vault role using controller env credentials",
                                "ansible.builtin.include_role": {"name": "vault_integration"},
                                "vars": {
                                    "vault_integration_operation": "bootstrap",
                                    "vault_integration_credential_allowed_owners": [CURRENT_USER],
                                    "vault_integration_credential_allowed_groups": [CURRENT_GROUP],
                                },
                            }
                        ],
                    }
                ],
                extra_env={"CREDENTIALS_DIRECTORY": str(credentials_dir)},
            )
            self.assertEqual(0, result.returncode, f"{result.stdout}\n{result.stderr}")

    def test_role_cleanup_runs_after_injected_failures(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aihost-vault-cleanup-") as tmpdir:
            temp_root = Path(tmpdir)
            credentials_dir = make_credentials(temp_root)
            for failure_var, failure_value in (
                ("vault_integration_test_fail_after_credential_resolve", True),
                ("vault_integration_test_fail_after_login", True),
            ):
                with self.subTest(failure_var=failure_var):
                    role_vars: dict[str, object] = {
                        "vault_integration_enabled": True,
                        "vault_integration_operation": "preflight",
                        "vault_integration_credential_allowed_owners": [CURRENT_USER],
                        "vault_integration_credential_allowed_groups": [CURRENT_GROUP],
                        "vault_integration_test_simulated_login_result": simulated_login_result(),
                        failure_var: failure_value,
                    }
                    playbook = [
                        {
                            "hosts": "localhost",
                            "gather_facts": False,
                            "tasks": [
                                {
                                    "block": [
                                        {
                                            "name": "Run vault role and expect a controlled failure",
                                            "ansible.builtin.include_role": {"name": "vault_integration"},
                                            "vars": role_vars,
                                        }
                                    ],
                                    "rescue": [
                                        {
                                            "name": "Assert vault cleanup marker and cleared sensitive facts",
                                            "ansible.builtin.assert": {
                                                "that": [
                                                    "vault_integration_cleanup_marker | default(false) | bool",
                                                    "vault_integration_role_id is none",
                                                    "vault_integration_secret_id is none",
                                                    "vault_integration_role_id_file is none",
                                                    "vault_integration_secret_id_file is none",
                                                    "vault_integration_login_result is none",
                                                    "vault_integration_secret_result is none",
                                                ]
                                            },
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                    result = run_probe_playbook(
                        playbook,
                        extra_env={"CREDENTIALS_DIRECTORY": str(credentials_dir)},
                    )
                    self.assertEqual(0, result.returncode, f"{result.stdout}\n{result.stderr}")

    def test_role_rejects_fail_closed_input_defects(self) -> None:
        with tempfile.TemporaryDirectory(prefix="aihost-vault-invalid-") as tmpdir:
            temp_root = Path(tmpdir)
            credentials_dir = make_credentials(temp_root)
            invalid_cases = (
                ("tls_false", {"vault_integration_operation": "bootstrap", "vault_integration_validate_certs": False}),
                ("prefix_override", {"vault_integration_operation": "bootstrap", "vault_integration_allowed_secret_prefixes": ["secret/local-ai/shared/"]}),
                ("auth_mount_traversal", {"vault_integration_operation": "bootstrap", "vault_integration_auth_mount": "../approle"}),
                ("kv_mount_nested", {"vault_integration_operation": "bootstrap", "vault_integration_kv2_mount": "secret/nested"}),
                (
                    "wrong_host_secret",
                    {
                        "vault_integration_operation": "read",
                        "vault_integration_enabled": True,
                        "vault_integration_credential_allowed_owners": [CURRENT_USER],
                        "vault_integration_credential_allowed_groups": [CURRENT_GROUP],
                        "vault_integration_test_simulated_login_result": simulated_login_result(),
                        "vault_integration_secret_ref": "secret/local-ai/hosts/not-localhost/runtime",
                        "vault_integration_required_secret_keys": ["required"],
                    },
                ),
                (
                    "cluster_secret_without_membership",
                    {
                        "vault_integration_operation": "read",
                        "vault_integration_enabled": True,
                        "vault_integration_credential_allowed_owners": [CURRENT_USER],
                        "vault_integration_credential_allowed_groups": [CURRENT_GROUP],
                        "vault_integration_test_simulated_login_result": simulated_login_result(),
                        "vault_integration_secret_ref": "secret/local-ai/clusters/runtime",
                        "vault_integration_required_secret_keys": ["required"],
                    },
                ),
            )
            for label, role_vars in invalid_cases:
                with self.subTest(label=label):
                    playbook = [
                        {
                            "hosts": "localhost",
                            "gather_facts": False,
                            "tasks": [
                                {
                                    "name": f"Run invalid vault case {label}",
                                    "ansible.builtin.include_role": {"name": "vault_integration"},
                                    "vars": role_vars,
                                }
                            ],
                        }
                    ]
                    result = run_probe_playbook(
                        playbook,
                        extra_env={"CREDENTIALS_DIRECTORY": str(credentials_dir)},
                    )
                    self.assertNotEqual(0, result.returncode, f"{label} unexpectedly passed")


if __name__ == "__main__":
    unittest.main()
