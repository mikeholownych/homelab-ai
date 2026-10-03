"""Static tests for the gated Vault server role; never contact production."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_vault_server_is_separate_from_production_entrypoints():
    site = read("playbooks/site.yml")
    bootstrap = read("playbooks/bootstrap.yml")
    commission = read("playbooks/commission.yml")
    server_playbook = read("playbooks/vault-server.yml")

    assert "vault_server" not in site
    assert "vault_server" not in bootstrap
    assert "vault_server" not in commission
    assert "hosts: vault_servers" in server_playbook
    assert "roles:\n    - vault_server" in server_playbook
    fixture_inventory = read("tests/fixtures/issue4/inventory.ini")
    assert "[vault_servers]\nlocalhost ansible_connection=local" in fixture_inventory
    assert "10.0.8.254" not in fixture_inventory
    assert "192.168.1.124" not in fixture_inventory


def test_server_role_is_explicitly_gated_and_pinned():
    defaults = read("roles/vault_server/defaults/main.yml")
    tasks = read("roles/vault_server/tasks/main.yml")

    assert "vault_server_manage: false" in defaults
    assert 'vault_server_service_started: false' in defaults
    assert "vault_server_manage | bool" in tasks
    assert "vault_server_version == '2.1.1'" in tasks
    assert "checksum: \"sha256:{{ vault_server_archive_sha256 }}\"" in tasks
    assert "vault_server_listener_address not in ['0.0.0.0:8200'" in tasks
    assert "Require sufficient local block-backed storage for Raft" in tasks
    assert "vault_server_min_free_bytes | int > 0" in tasks
    assert "when: not ansible_check_mode" in tasks
    assert "check_mode: false" in tasks


def test_no_initialization_or_secret_provisioning_is_automated():
    role_text = "\n".join(
        read(path.relative_to(ROOT).as_posix())
        for path in (ROOT / "roles/vault_server").rglob("*")
        if path.is_file()
    )

    assert "operator init" not in role_text
    assert "operator unseal" not in role_text
    assert "root_token" not in role_text
    assert "secret_id" not in role_text


def test_server_configuration_requires_tls_and_raft():
    defaults = read("roles/vault_server/defaults/main.yml")
    hcl = read("roles/vault_server/templates/vault.hcl.j2")
    tasks = read("roles/vault_server/tasks/main.yml")

    assert 'vault_server_tls_cert_file: ""' in defaults
    assert 'vault_server_tls_key_file: ""' in defaults
    assert 'vault_server_tls_ca_file: ""' in defaults
    assert 'storage "raft"' in hcl
    assert 'tls_disable = false' in hcl
    assert "vault_server_tls_stats.results" in tasks
    assert "Verify externally issued Vault TLS certificate chain" in tasks


def test_role_does_not_enable_or_start_vault_by_default():
    defaults = read("roles/vault_server/defaults/main.yml")
    tasks = read("roles/vault_server/tasks/main.yml")

    assert "vault_server_service_enabled: false" in defaults
    assert "vault_server_service_started: false" in defaults
    assert "Enable Vault at boot only when explicitly requested" in tasks
    assert "Start Vault only when explicitly requested" in tasks
    assert "state: stopped" not in tasks
