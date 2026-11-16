"""The observability Vault setup script generates three distinct secrets and a least-privilege read-only policy."""
import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("vault_observability_setup",
                                              Path(__file__).resolve().parents[1] / "scripts/vault-observability-setup.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_secrets_are_distinct_non_empty_and_sized():
    values = module.new_secrets()
    assert set(values) == {"password", "secret_key", "renderer_token"}
    assert len(set(values.values())) == 3
    assert all(len(values[name]) == length for name, length in module.FIELDS.items())


def test_policy_is_read_only_on_the_observability_path():
    assert module.POLICY.count("path ") == 1
    assert 'capabilities = ["read"]' in module.POLICY and "secret/data/local-ai/observability/*" in module.POLICY
    assert module.ROLE["token_ttl"] <= 3600 and module.ROLE["bind_secret_id"] is True
