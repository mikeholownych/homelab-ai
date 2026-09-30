"""Offline contract checks for direct Vault to T5820 credential delivery."""
import importlib.util
import importlib.machinery
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
FILES = ROOT / "roles" / "vault_platform_credentials" / "files"


def load_script(name: str, module_name: str):
    loader = importlib.machinery.SourceFileLoader(module_name, str(FILES / name))
    spec = importlib.util.spec_from_loader(module_name, loader)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class VaultPlatformCredentialContractTests(unittest.TestCase):
    def test_secret_paths_are_exact_and_limited_to_t5820_consumers(self):
        helper = load_script("aihost-vault-apply-credentials.py", "vault_platform_apply")
        self.assertEqual(
            helper.SECRETS,
            {
                "gateway_client": ("local-ai/services/orchestrator-gateway/client-token", "token"),
                "opencode_client": ("local-ai/hosts/ai-5820-01/opencode-client-token", "token"),
                "vllm_compat": ("local-ai/services/vllm/api-key", "key"),
                "worker1": ("local-ai/services/vllm/worker1-api-key", "key"),
                "worker2": ("local-ai/services/vllm/worker2-api-key", "key"),
            },
        )

    def test_atomic_write_is_content_idempotent_and_keeps_permissions(self):
        helper = load_script("aihost-vault-apply-credentials.py", "vault_platform_apply_atomic")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credential"
            path.write_text("fixture-secret\n")
            path.chmod(0o400)
            self.assertFalse(helper.atomic_write(path, "fixture-secret\n"))
            self.assertTrue(helper.atomic_write(path, "replacement-fixture\n"))
            self.assertEqual(path.read_text(), "replacement-fixture\n")
            self.assertEqual(path.stat().st_mode & 0o777, 0o400)

    def test_gateway_readiness_uses_per_worker_file_and_endpoint(self):
        readiness = load_script("aihost-gateway-readiness", "vault_gateway_readiness")
        with tempfile.TemporaryDirectory() as directory:
            token_file = Path(directory) / "worker-api-key"
            token_file.write_text("fixture-worker-token\n")
            captured = {}

            class Response:
                status = 200

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    return False

            def fake_urlopen(request, timeout):
                captured["url"] = request.full_url
                captured["authorization"] = request.get_header("Authorization")
                captured["timeout"] = timeout
                return Response()

            with patch.object(readiness.urllib.request, "urlopen", side_effect=fake_urlopen):
                self.assertTrue(readiness.ready({"token_file": str(token_file), "endpoint": "http://127.0.0.1:8001"}))
            self.assertEqual(captured["url"], "http://127.0.0.1:8001/v1/models")
            self.assertEqual(captured["authorization"], "Bearer fixture-worker-token")
            self.assertEqual(captured["timeout"], 5)

    def test_operator_sync_helper_does_not_emit_secret_contents(self):
        helper = load_script("update-opencode-vault-credential.py", "vault_opencode_refresh")
        self.assertIn("local-ai/hosts/ai-5820-01/opencode-client-token", (FILES / "update-opencode-vault-credential.py").read_text())
        self.assertIn('"changed": True', (FILES / "update-opencode-vault-credential.py").read_text())
        self.assertTrue(callable(helper.main))

    def test_snapshot_export_uses_a_scoped_approle_and_client_side_encryption(self):
        path = ROOT / "roles" / "vault_snapshot_backup" / "files" / "vault-encrypted-raft-backup.py"
        source = path.read_text()
        self.assertIn("auth/approle/login", source)
        self.assertIn("sys/storage/raft/snapshot", source)
        self.assertIn('"--symmetric"', source)
        self.assertIn('"AES256"', source)
        self.assertIn("downloaded.gpg", source)
        self.assertNotIn("VAULT_BACKUP_ROOT_TOKEN", source)

    def test_partial_restart_failure_restores_files_and_reconciles_all_services(self):
        helper = load_script("aihost-vault-apply-credentials.py", "vault_platform_transaction")
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "worker1-key"
            second = Path(directory) / "worker2-key"
            first.write_text("previous-worker1\n")
            second.write_text("previous-worker2\n")
            first.chmod(0o400)
            second.chmod(0o400)
            restarts = []
            failure_once = {"done": False}

            def restart(unit):
                restarts.append(unit)
                if unit == "worker2" and not failure_once["done"]:
                    failure_once["done"] = True
                    raise RuntimeError("injected restart failure")

            with self.assertRaisesRegex(RuntimeError, "previous state restored"):
                helper.apply_transaction(
                    [(first, "replacement-worker1\n", None, None), (second, "replacement-worker2\n", None, None)],
                    ["worker1", "worker2", "gateway"],
                    restart,
                    lambda: None,
                    lambda: self.assertEqual((first.read_text(), second.read_text()), ("previous-worker1\n", "previous-worker2\n")),
                )
            self.assertEqual(first.read_text(), "previous-worker1\n")
            self.assertEqual(second.read_text(), "previous-worker2\n")
            self.assertEqual(restarts, ["worker1", "worker2", "worker1", "worker2", "gateway"])
            self.assertEqual(first.stat().st_mode & 0o777, 0o400)
            self.assertEqual(second.stat().st_mode & 0o777, 0o400)

    def test_rollback_verification_failure_is_reported_explicitly(self):
        helper = load_script("aihost-vault-apply-credentials.py", "vault_platform_transaction_failure")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "credential"
            target.write_text("previous-private-value\n")
            target.chmod(0o400)

            def fail_restart(_unit):
                raise RuntimeError("injected restart failure")

            with self.assertRaisesRegex(RuntimeError, "rollback could not restore") as error:
                helper.apply_transaction(
                    [(target, "replacement-private-value\n", None, None)],
                    ["gateway"],
                    fail_restart,
                    lambda: None,
                    lambda: (_ for _ in ()).throw(RuntimeError("injected boundary failure")),
                )
            self.assertNotIn("previous-private-value", str(error.exception))
            self.assertNotIn("replacement-private-value", str(error.exception))
            self.assertEqual(target.read_text(), "previous-private-value\n")

    def test_partial_file_promotion_restores_every_promoted_target(self):
        helper = load_script("aihost-vault-apply-credentials.py", "vault_platform_transaction_promotion")
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "worker1-key"
            second = Path(directory) / "worker2-key"
            first.write_text("previous-worker1\n")
            second.write_text("previous-worker2\n")
            first.chmod(0o400)
            second.chmod(0o400)
            real_replace = helper.os.replace
            fail_once = {"done": False}

            def failing_replace(source, destination):
                if Path(destination) == second and not fail_once["done"]:
                    fail_once["done"] = True
                    raise OSError("injected promotion failure")
                return real_replace(source, destination)

            restarted = []
            with patch.object(helper.os, "replace", side_effect=failing_replace):
                with self.assertRaisesRegex(RuntimeError, "previous state restored"):
                    helper.apply_transaction(
                        [(first, "replacement-worker1\n", None, None), (second, "replacement-worker2\n", None, None)],
                        ["worker1", "gateway"],
                        restarted.append,
                        lambda: None,
                        lambda: self.assertEqual((first.read_text(), second.read_text()), ("previous-worker1\n", "previous-worker2\n")),
                    )
            self.assertEqual(first.read_text(), "previous-worker1\n")
            self.assertEqual(second.read_text(), "previous-worker2\n")
            self.assertEqual(restarted, ["worker1", "gateway"])

    def test_staging_failure_leaves_active_files_untouched_without_reconciliation(self):
        helper = load_script("aihost-vault-apply-credentials.py", "vault_platform_transaction_stage_failure")
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "worker1-key"
            second = Path(directory) / "worker2-key"
            first.write_text("previous-worker1\n")
            second.write_text("previous-worker2\n")
            first.chmod(0o400)
            second.chmod(0o400)
            restarts = []
            with patch.object(helper, "_stage_file", side_effect=OSError("injected staging failure")):
                with self.assertRaisesRegex(RuntimeError, "before promotion"):
                    helper.apply_transaction(
                        [(first, "replacement-worker1\n", None, None), (second, "replacement-worker2\n", None, None)],
                        ["worker1", "worker2", "gateway"],
                        restarts.append,
                        lambda: None,
                        lambda: None,
                    )
            self.assertEqual((first.read_text(), second.read_text()), ("previous-worker1\n", "previous-worker2\n"))
            self.assertEqual(restarts, [])

    def test_replacement_validation_failure_restores_and_reconciles_previous_state(self):
        helper = load_script("aihost-vault-apply-credentials.py", "vault_platform_transaction_validation_failure")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "gateway-key"
            target.write_text("previous-gateway-key\n")
            target.chmod(0o400)
            restarts = []
            old_verified = []

            def verify_new():
                self.assertEqual(target.read_text(), "replacement-gateway-key\n")
                raise RuntimeError("injected replacement authentication/health validation failure")

            def verify_old():
                self.assertEqual(target.read_text(), "previous-gateway-key\n")
                old_verified.append(True)

            with self.assertRaisesRegex(RuntimeError, "previous state restored"):
                helper.apply_transaction(
                    [(target, "replacement-gateway-key\n", None, None)],
                    ["gateway"],
                    restarts.append,
                    verify_new,
                    verify_old,
                )
            self.assertEqual(target.read_text(), "previous-gateway-key\n")
            self.assertEqual(restarts, ["gateway", "gateway"])
            self.assertEqual(old_verified, [True])

    def test_opencode_local_credential_can_be_restored_without_emitting_value(self):
        helper = load_script("update-opencode-vault-credential.py", "vault_opencode_backup")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "opencode.env"
            backup = root / "tmpfs" / "previous"
            target.write_text("export T5820_CLIENT_TOKEN='prior-fixture'\n")
            target.chmod(0o600)
            helper.backup_output(target, backup)
            target.write_text("export T5820_CLIENT_TOKEN='new-fixture'\n")
            helper.restore_output(target, backup)
            self.assertEqual(target.read_text(), "export T5820_CLIENT_TOKEN='prior-fixture'\n")
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)

            missing = root / "missing.env"
            missing_backup = root / "tmpfs" / "missing"
            helper.backup_output(missing, missing_backup)
            missing.write_text("temporary\n")
            helper.restore_output(missing, missing_backup)
            self.assertFalse(missing.exists())


if __name__ == "__main__":
    unittest.main()
