# Vault runtime integration

This repository treats HashiCorp Vault as the only secret authority. Do not use
Ansible Vault, committed plaintext, plaintext fallback, cached secret facts, a
root token, or a long-lived administrative token.

## What the runtime expects

- `vault_integration_enabled: true` before `playbooks/site.yml` performs Vault
  preflight.
- `vault_bootstrap_validate_credentials: true` only when you want
  `playbooks/bootstrap.yml` to validate the local credential posture.
- `vault_bootstrap_configure_references: true` only when you want bootstrap to
  render a non-secret runtime reference file.
- `vault_auth_method: approle`. Future method names are rejected until an
  implementation is added and tested.
- `vault_addr` must remain an `https://` URL.
- `vault_namespace` is optional.
- `vault_auth_mount` defaults to `approle`.
- `vault_kv2_mount` defaults to `secret`.
- `vault_ca_cert_path` must point at the CA bundle that validates Vault TLS.

## Protected AppRole credential contract

The scheduled runner contract prefers systemd `LoadCredential=` files exposed
through `CREDENTIALS_DIRECTORY`. The role looks for:

- `${CREDENTIALS_DIRECTORY}/vault-role-id`
- `${CREDENTIALS_DIRECTORY}/vault-secret-id`

If systemd credentials are not in use, point the role at protected fallback
paths provisioned out of band. Do not commit those files and do not create them
 from inventory data.

Every credential file must be:

- a regular file, not a symlink
- owned by the configured root or service account/group
- mode `0400` or `0440`
- non-empty
- size-bounded

The role ID may be less sensitive than the SecretID, but this repository still
treats it as protected credential material.

## AppRole setup and SecretID delivery

Example least-privilege policy paths use list and read only:

```hcl
path "secret/data/local-ai/shared/*" {
  capabilities = ["read", "list"]
}

path "secret/data/local-ai/hosts/{{identity}}/*" {
  capabilities = ["read", "list"]
}

path "secret/data/local-ai/clusters/*" {
  capabilities = ["read", "list"]
}

path "secret/data/local-ai/services/*" {
  capabilities = ["read", "list"]
}
```

Create an AppRole out of band, bind the policy above, keep the token TTL short,
and require renewable short-lived tokens. Deliver the initial SecretID with
response wrapping and install it on the runner out of band.

Example commands with placeholders only:

```bash
vault auth enable approle
vault policy write local-ai-runtime /path/to/local-ai-runtime-policy.hcl
vault write auth/approle/role/local-ai-runtime \
  token_policies=local-ai-runtime \
  token_ttl=15m \
  token_max_ttl=1h \
  secret_id_num_uses=8 \
  secret_id_ttl=24h
vault write -wrap-ttl=15m -f auth/approle/role/local-ai-runtime/secret-id
```

Do not use a root token for automation.

## Runtime access pattern

`community.hashi_vault.vault_login` exchanges the AppRole credentials for a
short-lived token at runtime. The role validates TTL, renewability, and rejects
the root policy when Vault returns policy metadata.

`community.hashi_vault.vault_kv2_get` retrieves KVv2 data at task runtime. The
secret path must be a normalized logical reference stored in Git and must stay
within the approved `shared`, `hosts/{{identity}}`, `clusters`, or `services`
trees. Missing auth, TLS, path, or required keys stop dependent work.

The role returns only non-secret access metadata such as the path reference and
secret version. `no_log: true` protects the login and lookup tasks from logging
secret or token material.

## systemd scheduled runner example

The runtime contract for later scheduled execution is:

```ini
[Service]
LoadCredential=vault-role-id:/etc/aihost/credentials/vault-role-id
LoadCredential=vault-secret-id:/etc/aihost/credentials/vault-secret-id
EnvironmentFile=/etc/aihost/vault-runtime.env
```

Provision `/etc/aihost/credentials/vault-role-id` and
`/etc/aihost/credentials/vault-secret-id` out of band as root-readable files
when systemd credentials are unavailable.

## rotation, revocation, and outage behavior

- Rotation: rotate the SecretID on a regular schedule and after any suspected
  exposure.
- Revocation: revoke the SecretID immediately if the runner is decommissioned or
  compromised.
- Rotate the AppRole or attached policy when access scope changes.
- If Vault is unavailable or TLS validation fails, the repository fails closed.
- There is no plaintext fallback and no Ansible Vault fallback.

## Replacing the auth method later

Only `approle` is implemented today. To replace it with another auth method,
add the new method to the allowlist, implement the runtime flow, and extend
`tests/test_vault_contract.py` before changing any consumer role.
