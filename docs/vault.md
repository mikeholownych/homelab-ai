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

When `vault_integration_operation: read` succeeds, the role publishes a minimal
caller interface:

- `vault_integration_secret` contains only the explicitly requested secret keys
- `vault_integration_secret_access_metadata` contains non-secret access
  metadata such as the logical path reference and KV version

The role still guarantees cleanup of transient credential, token, login, and
raw read result variables. Callers should consume `vault_integration_secret`
immediately in the next dependent task and then clear it with a `no_log: true`
`ansible.builtin.set_fact` once it is no longer needed.

## Protected AppRole credential contract

The scheduled runner should provide:

- `$CREDENTIALS_DIRECTORY/vault-role-id`
- `$CREDENTIALS_DIRECTORY/vault-secret-id`

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

Install the AppRole RoleID as a protected root-owned file even though it is not
secret:

```bash
umask 077
install -d -m 0700 -o root -g root /run/aihost-vault
vault read -field=role_id auth/approle/role/local-ai-runtime/role-id \
  > /run/aihost-vault/vault-role-id.tmp
install -m 0400 -o root -g root /run/aihost-vault/vault-role-id.tmp /etc/aihost/credentials/vault-role-id
rm -f /run/aihost-vault/vault-role-id.tmp
```

Redirect the RoleID straight into the protected temporary file so nothing is
printed to stdout during installation.

## AppRole setup and policy scope

Use `community.hashi_vault.vault_login` for the short-lived runtime token
exchange and `community.hashi_vault.vault_kv2_get` for task-time reads.

Both read-only tasks set `check_mode: false`. Ansible check mode would
otherwise simulate Vault access and skip the real short-lived token exchange or
KV read, which breaks meaningful preflight validation. The explicit check mode
override keeps check mode functional by performing the same read-only Vault
authentication and secret retrieval that normal runtime validation requires.

Prefer read only KV policies. Omit `list` unless you truly need metadata
enumeration; metadata list only if needed.

Example AppRole provisioning flow:

```bash
vault policy write local-ai-runtime /path/to/local-ai-runtime-policy.hcl
vault auth enable -path=approle approle
vault write auth/approle/role/local-ai-runtime \
  token_policies=local-ai-runtime \
  token_ttl=15m \
  token_max_ttl=30m \
  secret_id_ttl=168h \
  secret_id_num_uses=0 \
  bind_secret_id=true
```

This combination supports scheduled machine auth without a one-shot second-run
failure. The SecretID can be reused during its bounded 168h lifetime, while the
Vault tokens issued from it remain short-lived and never stored.

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
install -d -m 0700 -o root -g root /run/aihost-vault
vault write -format=json -wrap-ttl=15m -f auth/approle/role/local-ai-runtime/secret-id \
  > /run/aihost-vault/wrapped-secret-id.json
VAULT_TOKEN=WRAPPING_TOKEN_FROM_OUT_OF_BAND_CHANNEL \
  vault unwrap -format=json > /run/aihost-vault/unwrapped-secret-id.json
python3 -c "import json, pathlib; data=json.loads(pathlib.Path('/run/aihost-vault/unwrapped-secret-id.json').read_text(encoding='utf-8')); pathlib.Path('/run/aihost-vault/vault-secret-id.tmp').write_text(data['data']['secret_id'] + '\n', encoding='utf-8')"
install -m 0400 -o root -g root /run/aihost-vault/vault-secret-id.tmp /etc/aihost/credentials/vault-secret-id
rm -f /run/aihost-vault/wrapped-secret-id.json /run/aihost-vault/unwrapped-secret-id.json /run/aihost-vault/vault-secret-id.tmp
```

The JSON capture keeps the wrapped response and the unwrapped `.data.secret_id`
out of stdout while a root-only tmpfs file is converted into the protected
runtime credential file. Delete the wrapper JSON and every transient file
immediately after install.

This contract uses plain root-owned `0400` files with `LoadCredential=` only.
Never point `LoadCredential=` at ciphertext or encrypted credential blobs.

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
Logical refs must be exact ASCII paths with no whitespace, control characters,
backslashes, `%`, `?`, `#`, empty segments, `.`, `..`, or double slashes.

## systemd scheduled runner example

```ini
[Service]
LoadCredential=vault-role-id:/etc/aihost/credentials/vault-role-id
LoadCredential=vault-secret-id:/etc/aihost/credentials/vault-secret-id
EnvironmentFile=/etc/aihost/vault-runtime.env
```

The role then reads `$CREDENTIALS_DIRECTORY/vault-role-id` and
`$CREDENTIALS_DIRECTORY/vault-secret-id` on the controller at runtime.

## rotation, revocation, and outage recovery

- Rotation: rotate the SecretID before the bounded 168h TTL expires and after
  any suspected exposure.
- Revocation: revoke the SecretID immediately when the runner is retired or
  compromised.
- Revoke orphaned wrapped SecretIDs or stale AppRole SecretIDs before issuing a
  replacement.
- Rebind the AppRole policy when access scope changes.

Concrete scheduled rotation procedure:

1. Generate a new wrapped SecretID before the current SecretID TTL expires.
2. Unwrap it into a protected temporary file exactly as shown above.
3. atomically replace the credential file at
   `/etc/aihost/credentials/vault-secret-id`.
4. run the Vault preflight so the next scheduled run proves the new credential
   works.
5. revoke the old SecretID accessor only after a successful run with the new
   credential.

This avoids a one-shot second-run failure while still keeping runtime tokens
short-lived and never stored.

When runtime access fails, diagnose in this order:

1. TLS trust: confirm `vault_integration_ca_cert_path`, certificate chain, and
   hostname validation.
2. Vault health: confirm the Vault API is reachable and healthy.
3. Auth: confirm the AppRole mount, role ID, SecretID, TTL, and renewable token
   behavior.
4. Policy restore: confirm the read policy still covers the exact logical path.
5. If a rotated credential is suspect, reinstall the protected RoleID file,
   generate a new wrapped SecretID, atomically replace the SecretID file, run
   the Vault preflight, and then rerun the Ansible play once TLS, Vault health,
   auth, and policy restore are corrected.

The repository fails closed during outages. There is never a plaintext fallback
and never an Ansible Vault fallback.

## Replacing the auth method later

Only `approle` is implemented today. If you add another auth method, extend the
allowlist, implement the flow, and expand `tests/test_vault_contract.py` before
changing any consumer role.
