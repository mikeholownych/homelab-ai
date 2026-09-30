"""Contract tests for repeatable Vault post-initialization convergence."""
import importlib.machinery
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "roles/vault_post_init/files/vault-post-init.py"


def load_helper():
    loader = importlib.machinery.SourceFileLoader("vault_post_init_helper", str(SCRIPT))
    spec = importlib.util.spec_from_loader("vault_post_init_helper", loader)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ExistingVault:
    def __init__(self, helper):
        self.helper = helper
        self.writes = []

    def request(self, method, path, payload=None, allow_missing=False):
        helper = self.helper
        if method == "GET" and path == "sys/health":
            return 200, {"initialized": True, "sealed": False}
        if method == "GET" and path == "sys/mounts":
            return 200, {"data": {"secret/": {"type": "kv", "options": {"version": "2"}}}}
        if method == "GET" and path == "sys/auth":
            return 200, {"data": {"approle/": {"type": "approle"}}}
        if method == "GET" and path == "sys/audit":
            return 200, {"data": {"file/": {"type": "file", "options": {"file_path": helper.AUDIT_FILE}}}}
        if method == "GET" and path.startswith("sys/policies/acl/"):
            name = path.rsplit("/", 1)[-1]
            policy = helper.WORKLOAD_POLICY if name == "t5820-platform" else helper.SNAPSHOT_POLICY
            return 200, {"data": {"policy": policy}}
        if method == "GET" and path.startswith("auth/approle/role/") and path.endswith("/role-id"):
            return 200, {"data": {"role_id": "role-id-fixture"}}
        if method == "GET" and path.startswith("auth/approle/role/"):
            name = path.rsplit("/", 1)[-1]
            return 200, {"data": helper.APPROLES[name]}
        if method == "POST" and path == "auth/approle/login":
            return 200, {"auth": {"client_token": "synthetic-token", "lease_duration": 60}}
        if method == "GET" and path.startswith("secret/data/"):
            return 200, {"data": {}}
        if method in ("POST", "PUT"):
            self.writes.append((method, path, payload))
            return 200, {"data": {}}
        if allow_missing:
            return 404, {}
        raise AssertionError(f"Unexpected Vault API request: {method} {path}")


class FreshVault:
    def __init__(self, helper):
        self.helper = helper
        self.mounts = {}
        self.auth = {}
        self.audit = {}
        self.policies = {}
        self.roles = {}
        self.secrets = {}
        self.role_ids = {}
        self.secret_ids = {}
        self.writes = []

    def request(self, method, path, payload=None, allow_missing=False):
        if method == "GET" and path == "sys/health":
            return 200, {"initialized": True, "sealed": False}
        if method == "GET" and path == "sys/mounts":
            return 200, {"data": self.mounts}
        if method == "GET" and path == "sys/auth":
            return 200, {"data": self.auth}
        if method == "GET" and path == "sys/audit":
            return 200, {"data": self.audit}
        if method == "GET" and path.startswith("sys/policies/acl/"):
            name = path.rsplit("/", 1)[-1]
            if name not in self.policies:
                return 404, {}
            return 200, {"data": {"policy": self.policies[name]}}
        if method == "PUT" and path == "sys/audit/file":
            self.audit["file/"] = {"type": payload["type"], "options": payload["options"]}
        elif method in ("POST", "PUT") and path.startswith("sys/mounts/"):
            name = path.split("/", 2)[-1] + "/"
            self.mounts[name] = {"type": payload["type"], "options": payload.get("options", {})}
        elif method == "POST" and path == "sys/auth/approle":
            self.auth["approle/"] = {"type": "approle"}
        elif method == "PUT" and path.startswith("sys/policies/acl/"):
            self.policies[path.rsplit("/", 1)[-1]] = payload["policy"]
        elif method == "POST" and path.startswith("auth/approle/role/") and path.endswith("/secret-id"):
            name = path.split("/")[3]
            secret_id = f"new-{name}-secret-id"
            self.secret_ids[name] = secret_id
            self.writes.append(path)
            return 200, {"data": {"secret_id": secret_id}}
        elif method == "POST" and path.startswith("auth/approle/role/"):
            name = path.rsplit("/", 1)[-1]
            self.roles[name] = payload
            self.role_ids.setdefault(name, f"new-{name}-role-id")
        elif method == "GET" and path.startswith("auth/approle/role/") and path.endswith("/role-id"):
            name = path.split("/")[3]
            return 200, {"data": {"role_id": self.role_ids.get(name, f"new-{name}-role-id")}}
        elif method == "GET" and path.startswith("auth/approle/role/"):
            name = path.rsplit("/", 1)[-1]
            if name not in self.roles:
                return 404, {}
            return 200, {"data": self.roles[name]}
        elif method == "POST" and path == "auth/approle/login":
            for name, secret_id in self.secret_ids.items():
                if payload.get("secret_id") == secret_id and payload.get("role_id") == self.role_ids[name]:
                    return 200, {"auth": {"client_token": "synthetic-token"}}
            raise self.helper.VaultError("Vault API operation failed with HTTP 400")
        elif method == "GET" and path.startswith("secret/data/"):
            secret_path = path.removeprefix("secret/data/")
            if secret_path not in self.secrets:
                return 404, {}
            return 200, {"data": {}}
        elif method == "POST" and path.startswith("secret/data/"):
            secret_path = path.removeprefix("secret/data/")
            self.secrets[secret_path] = payload["data"]
        else:
            if allow_missing:
                return 404, {}
            raise AssertionError(f"Unexpected Vault API request: {method} {path}")
        self.writes.append(path)
        return 200, {"data": {}}


class VaultPostInitTests(unittest.TestCase):
    def test_fresh_init_configuration_is_seeded_then_idempotent(self):
        helper = load_helper()
        fake = FreshVault(helper)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            handoff = root / "handoff"
            seed = root / "seed"
            handoff.mkdir(mode=0o700)
            seed.mkdir(mode=0o700)
            for name in helper.SEEDS:
                source = seed / name
                source.write_text(f"synthetic-{name}-credential\n")
                source.chmod(0o400)
            with patch.object(helper, "VaultAPI", return_value=fake):
                result = helper.converge("https://vault.invalid:8200", Path("ca"), Path("token"), handoff, seed)
                self.assertTrue(result["changed"])
                self.assertEqual(set(result["seeded_records"]), set(helper.SEEDS))
                self.assertTrue(result["workload_handoff_changed"])
                self.assertTrue(result["snapshot_handoff_changed"])
                first_write_count = len(fake.writes)
                result = helper.converge("https://vault.invalid:8200", Path("ca"), Path("token"), handoff, seed)
            self.assertFalse(result["changed"])
            self.assertEqual(len(fake.writes), first_write_count)
            self.assertEqual((handoff / "approle/secret-id").stat().st_mode & 0o777, 0o400)

    def test_converges_existing_configuration_without_writes_or_secret_rotation(self):
        helper = load_helper()
        fake = ExistingVault(helper)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            handoff = root / "handoff"
            seed = root / "seed"
            handoff.mkdir(mode=0o700)
            seed.mkdir(mode=0o700)
            for subdir in ("approle", "snapshot-approle"):
                (handoff / subdir).mkdir(mode=0o700)
                (handoff / subdir / "role-id").write_text("role-id-fixture\n")
                (handoff / subdir / "secret-id").write_text("secret-id-fixture\n")
                for path in (handoff / subdir).iterdir():
                    path.chmod(0o400)
            for name in helper.SEEDS:
                source = seed / name
                source.write_text("synthetic-bootstrap-value\n")
                source.chmod(0o400)
            with patch.object(helper, "VaultAPI", return_value=fake):
                result = helper.converge("https://vault.invalid:8200", Path("ca"), Path("token"), handoff, seed)
            self.assertFalse(result["changed"])
            self.assertFalse(result["workload_handoff_changed"])
            self.assertFalse(result["snapshot_handoff_changed"])
            self.assertEqual(fake.writes, [])
            self.assertEqual((handoff / "approle/secret-id").read_text(), "secret-id-fixture\n")

    def test_sealed_vault_is_unsealed_only_from_protected_file(self):
        helper = load_helper()

        class SealedVault:
            def __init__(self):
                self.sealed = True
                self.calls = []

            def request(self, method, path, payload=None, allow_missing=False):
                self.calls.append((method, path))
                if path == "sys/unseal":
                    self.sealed = False
                    return 200, {"sealed": False}
                return 200, {"initialized": True, "sealed": self.sealed}

        fake = SealedVault()
        with tempfile.TemporaryDirectory() as directory:
            key_file = Path(directory) / "share"
            key_file.write_text("fixture-unseal-share\n")
            key_file.chmod(0o400)
            result = helper.unseal_if_needed(fake, {"initialized": True, "sealed": True}, key_file)
            self.assertFalse(result["sealed"])
            self.assertEqual(fake.calls, [("POST", "sys/unseal")])


class VaultInitHandoffTests(unittest.TestCase):
    def test_init_response_schema_is_saved_without_exposing_values(self):
        path = ROOT / "roles/vault_post_init/files/vault-init-handoff.py"
        loader = importlib.machinery.SourceFileLoader("vault_init_handoff", str(path))
        spec = importlib.util.spec_from_loader("vault_init_handoff", loader)
        helper = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(helper)
        with tempfile.TemporaryDirectory() as directory:
            handoff = Path(directory) / "handoff"
            handoff.mkdir(mode=0o700)
            with patch.object(helper, "read_health", return_value={"initialized": False, "sealed": True}):
                result = helper.initialize(
                    "https://vault.invalid:8200",
                    Path("ca"),
                    "vault",
                    handoff,
                    run=lambda *_args, **_kwargs: type("Result", (), {"stdout": '{"unseal_keys_b64":["fixture-share"],"root_token":"fixture-root"}'})(),
                )
            self.assertTrue(result["recovery_material_saved"])
            self.assertEqual((handoff / "vault-unseal.key").read_text(), "fixture-share\n")
            self.assertEqual((handoff / "vault-root-token").read_text(), "fixture-root\n")
            self.assertEqual((handoff / "vault-init-record.json").stat().st_mode & 0o777, 0o400)

    def test_init_refuses_an_already_initialized_vault_before_running_cli(self):
        path = ROOT / "roles/vault_post_init/files/vault-init-handoff.py"
        loader = importlib.machinery.SourceFileLoader("vault_init_guard", str(path))
        spec = importlib.util.spec_from_loader("vault_init_guard", loader)
        helper = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(helper)
        with tempfile.TemporaryDirectory() as directory:
            handoff = Path(directory) / "handoff"
            handoff.mkdir(mode=0o700)
            with patch.object(helper, "read_health", return_value={"initialized": True, "sealed": False}):
                with self.assertRaisesRegex(helper.InitError, "already initialized"):
                    helper.initialize("https://vault.invalid:8200", Path("ca"), "vault", handoff, run=lambda *_args, **_kwargs: self.fail("init CLI must not run"))

    def test_refuses_to_initialize_or_mutate_a_sealed_vault(self):
        helper = load_helper()

        class SealedVault(ExistingVault):
            def request(self, method, path, payload=None, allow_missing=False):
                if method == "GET" and path == "sys/health":
                    return 200, {"initialized": True, "sealed": True}
                return super().request(method, path, payload, allow_missing)

        fake = SealedVault(helper)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            handoff = root / "handoff"
            seed = root / "seed"
            handoff.mkdir()
            seed.mkdir()
            with patch.object(helper, "VaultAPI", return_value=fake):
                with self.assertRaisesRegex(helper.VaultError, "must already be initialized and unsealed"):
                    helper.converge("https://vault.invalid:8200", Path("ca"), Path("token"), handoff, seed)
            self.assertEqual(fake.writes, [])


if __name__ == "__main__":
    unittest.main()
