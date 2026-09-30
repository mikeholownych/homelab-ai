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


if __name__ == "__main__":
    unittest.main()
