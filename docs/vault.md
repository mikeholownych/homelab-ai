# Vault runtime integration

This repository treats HashiCorp Vault as the only secret authority. Do not use
Ansible Vault, committed plaintext, plaintext fallback, cached secret facts, or
a root token for automation.

## Required variables

- `vault_integration_enabled: true` before `playbooks/site.yml` runs secret
  dependent work.
- `vault_integration_bootstrap_validate_credentials: true` only when
  `playbooks/bootstrap.yml` should validate controller-visible credential
  posture.
- `vault_integration_bootstrap_configure_references: true` only when bootstrap
  should render the non-secret runtime reference file.
- `vault_integration_auth_method: approle`
- `vault_integration_addr: https://vault.example.invalid`
- `vault_integration_namespace: null` unless you explicitly use a safe
  namespace string.
- `vault_integration_auth_mount: approle`
- `vault_integration_kv2_mount: secret`
- `vault_integration_ca_cert_path: /etc/ssl/certs/ca-certificates.crt`

The controller resolves `vault_integration_credentials_directory` from
`CREDENTIALS_DIRECTORY` with `lookup('ansible.builtin.env', ...)`, so the role
uses controller credentials instead of remote `ansible_env` values. You may
still override `vault_integration_credentials_directory` explicitly when the
controller needs a different protected path.

## Protected AppRole credential contract

The scheduled runner should provide:

- `${CREDENTIALS_DIRECTORY}/vault-role-id`
- `${CREDENTIALS_DIRECTORY}/vault-secret-id`

If `LoadCredential=` is unavailable, point the role at protected fallback files
that were provisioned out of band. Do not create those files from inventory and
do not commit credential contents.

Each credential file must be:

- a regular file
- not a symlink
- readable only by the configured root or service account
- mode `0400` or `0440`
- non-empty
- size bounded

The role ID may be less sensitive than the SecretID, but this repository still
treats both as protected.

## AppRole setup and policy scope

Use `community.hashi_vault.vault_login` for the short-lived runtime token
exchange and `community.hashi_vault.vault_kv2_get` for task-time reads.

Prefer read only KV policies. Omit `list` unless you truly need metadata
enumeration; metadata list only if needed.

Example policy with read only access:

```hcl
path "secret/data/local-ai/shared/*" {
  capabilities = ["read"]
}

path "secret/data/local-ai/hosts/{{identity}}/*" {
  capabilities = ["read"]
}

path "secret/data/local-ai/clusters/*" {
  capabilities = ["read"]
}

path "secret/data/local-ai/services/*" {
  capabilities = ["read"]
}
```

If you need metadata enumeration, add the minimum metadata path `list`
capability separately instead of broadening data-path rights.

## Response-wrapped SecretID delivery

Deliver the initial SecretID with response wrapping and keep the wrapping token
out of band.

Example placeholder flow:

```bash
vault write -wrap-ttl=15m -f auth/approle/role/local-ai-runtime/secret-id
vault unwrap WRAPPING_TOKEN_FROM_OUT_OF_BAND_CHANNEL
systemd-creds encrypt --name=vault-secret-id /secure/input /secure/output
install -m 0400 -o root -g root /secure/output /etc/aihost/credentials/vault-secret-id
rm -f /secure/input /secure/output
```

Use the wrapping token only long enough to run `vault unwrap`, install the
SecretID with `systemd-creds` or `install -m 0400`, and delete transient files
immediately without printing the SecretID.

Do not use a root token for automation.

## Runtime path boundaries

Git stores only logical references. Runtime reads must stay under the validated
`vault_integration_kv2_mount` and the fixed `local-ai` categories:

- `secret/local-ai/shared/...`
- `secret/local-ai/hosts/{{inventory_hostname}}/...`
- `secret/local-ai/clusters/...`
- `secret/local-ai/services/...`

Host secrets must match the current `inventory_hostname`. Cluster secrets are
allowed only when cluster membership is configured for the current host.

## systemd scheduled runner example

```ini
[Service]
LoadCredential=vault-role-id:/etc/aihost/credentials/vault-role-id
LoadCredential=vault-secret-id:/etc/aihost/credentials/vault-secret-id
EnvironmentFile=/etc/aihost/vault-runtime.env
```

## rotation, revocation, and outage recovery

- Rotation: rotate the SecretID regularly and after any suspected exposure.
- Revocation: revoke the SecretID immediately when the runner is retired or
  compromised.
- Rebind the AppRole policy when access scope changes.

When runtime access fails, diagnose in this order:

1. TLS trust: confirm `vault_integration_ca_cert_path`, certificate chain, and
   hostname validation.
2. Vault health: confirm the Vault API is reachable and healthy.
3. Auth: confirm the AppRole mount, role ID, SecretID, TTL, and renewable token
   behavior.
4. Policy restore: confirm the read policy still covers the exact logical path.
5. Rerun the Ansible play once TLS, Vault health, auth, and policy restore are
   corrected.

The repository fails closed during outages. There is never a plaintext fallback
and never an Ansible Vault fallback.

## Replacing the auth method later

Only `approle` is implemented today. If you add another auth method, extend the
allowlist, implement the flow, and expand `tests/test_vault_contract.py` before
changing any consumer role.
