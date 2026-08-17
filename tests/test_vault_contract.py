from __future__ import annotations

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


def load_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


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
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(TASKS_ROOT.glob("*.yml")))


class VaultContractTests(unittest.TestCase):
    def test_defaults_define_fail_closed_vault_interface(self) -> None:
        defaults = load_yaml(DEFAULTS_PATH)
        self.assertIsInstance(defaults, dict)
        self.assertEqual(False, defaults.get("vault_integration_enabled"))
        self.assertEqual("approle", defaults.get("vault_integration_auth_method"))
        self.assertEqual(["approle"], defaults.get("vault_integration_auth_method_allowlist"))
        self.assertEqual("https://vault.example.invalid", defaults.get("vault_integration_addr"))
        self.assertEqual("approle", defaults.get("vault_integration_auth_mount"))
        self.assertEqual("secret", defaults.get("vault_integration_kv2_mount"))
        self.assertEqual(True, defaults.get("vault_integration_validate_certs"))
        self.assertEqual(False, defaults.get("vault_integration_bootstrap_validate_credentials"))
        self.assertEqual(False, defaults.get("vault_integration_bootstrap_configure_references"))
        self.assertEqual(
            [
                "secret/local-ai/shared/",
                "secret/local-ai/hosts/",
                "secret/local-ai/clusters/",
                "secret/local-ai/services/",
            ],
            defaults.get("vault_integration_allowed_secret_prefixes"),
        )

    def test_requirements_pin_hashi_vault_collection(self) -> None:
        requirements = load_yaml(REQUIREMENTS_YML)
        self.assertIsInstance(requirements, dict)
        collections = requirements.get("collections", [])
        self.assertIn(
            {"name": "community.hashi_vault", "version": "7.1.0"},
            collections,
        )

    def test_role_tasks_validate_https_and_auth_method_allowlist(self) -> None:
        role_text = load_role_text()
        self.assertIn("vault_integration_auth_method_allowlist", role_text)
        self.assertIn("vault_integration_auth_method == 'approle'", role_text)
        self.assertIn("vault_integration_addr is match('^https://')", role_text)
        self.assertIn("vault_integration_operation in ['bootstrap', 'preflight', 'read']", role_text)

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

    def test_role_tasks_validate_credential_files_and_bound_modes(self) -> None:
        role_text = load_role_text()
        self.assertIn("ansible.builtin.stat", role_text)
        self.assertIn("follow: false", role_text)
        self.assertIn("isreg", role_text)
        self.assertIn("islnk", role_text)
        self.assertIn("vault_integration_credential_max_size_bytes", role_text)
        self.assertIn("vault_integration_allowed_credential_modes", role_text)
        self.assertIn("vault_integration_role_id_credential_path", role_text)
        self.assertIn("vault_integration_secret_id_credential_path", role_text)

    def test_role_tasks_reject_path_traversal_and_cacheable_secret_facts(self) -> None:
        role_text = load_role_text()
        self.assertIn("vault_integration_secret_ref_normalized", role_text)
        self.assertIn("..", role_text)
        self.assertIn("vault_integration_allowed_secret_prefixes", role_text)
        self.assertNotIn("cacheable: true", role_text)
        self.assertNotIn("ignore_errors:", role_text)
        self.assertNotIn("ansible.builtin.debug", role_text)

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

        self.assertEqual(1, len(bootstrap_vault), "Bootstrap must integrate vault_integration once")
        self.assertEqual(1, len(site_vault), "Site must integrate vault_integration once")
        self.assertIn("bootstrap", bootstrap_vault[0].get("tags", []))
        self.assertIn("vault", bootstrap_vault[0].get("tags", []))
        self.assertIn("vault", site_vault[0].get("tags", []))
        self.assertIn("vault_preflight", site_vault[0].get("name", ""))
        self.assertIn("vault_integration_bootstrap_validate_credentials", str(bootstrap_vault[0].get("when", "")))

    def test_vault_docs_cover_operator_contract_and_prohibitions(self) -> None:
        self.assertTrue(DOCS_PATH.exists(), "Expected docs/vault.md to exist")
        docs_text = DOCS_PATH.read_text(encoding="utf-8")
        required_tokens = (
            "AppRole",
            "community.hashi_vault.vault_login",
            "community.hashi_vault.vault_kv2_get",
            "LoadCredential=",
            "response wrapping",
            "rotation",
            "revocation",
            "root token",
            "Ansible Vault",
            "plaintext fallback",
            "https://",
            "secret/data/local-ai/shared",
            "secret/data/local-ai/hosts/{{identity}}",
            "secret/data/local-ai/clusters",
            "secret/data/local-ai/services",
        )
        for token in required_tokens:
            with self.subTest(token=token):
                self.assertIn(token, docs_text)


if __name__ == "__main__":
    unittest.main()
