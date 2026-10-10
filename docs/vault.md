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

## Reproducible post-initialization configuration

`playbooks/vault-post-init.yml` is the idempotent post-init entrypoint for the
live homelab topology. Its policy, mount, audit and AppRole settings match the
currently deployed Vault 2.1.1 state:

- file audit device `file/` writing to `/var/log/vault/audit.log`;
- KVv2 at `secret/` and AppRole auth at `approle/`;
- `t5820-platform` can read only the five gateway, OpenCode, compatibility and
  worker KV records listed below, with a 10 minute token TTL and 60 minute
  maximum;
- `vault-snapshot-export` has only `read` and `sudo` on
  `sys/storage/raft/snapshot`, with a 5 minute token TTL and 10 minute maximum.

The root token and unseal share are read from protected files. They are never
Ansible variables or command arguments. The helper accepts Vault's HTTP 503
health response only when its body confirms an initialized, sealed Vault. It
submits the share to the verified TLS API, then requires HTTP 200 health with
Vault unsealed before continuing. It never initializes or resets Vault.
Existing mounts with conflicting types,
audit destinations, or KV versions fail closed. Existing workload KV records
are preserved; only missing records are seeded from the currently active,
protected T5820 credential files fetched over SSH into controller tmpfs. The
source files are removed from tmpfs after the run. Existing valid AppRole
handoff IDs remain unchanged; if a freshly initialized Vault has new AppRole
identities, fresh RoleID/SecretID values are written directly to the protected
handoff files without printing them.

### One-time initialization on a genuinely fresh Vault

Create or use a private handoff directory with mode `0700`, install the
Vault server and TLS material, then run the guarded initialization helper once:

```sh
python3 roles/vault_post_init/files/vault-init-handoff.py \
  --vault-addr https://10.0.8.254:8200 \
  --ca-cert /home/mike/.local/share/vault-issue4/vault-root-ca.crt \
  --handoff-dir /home/mike/.local/share/vault-issue4
```

It verifies Vault is not initialized and that the handoff directory is a
mode-`0700` directory owned by the executing operator. Before invoking the
pinned Vault CLI, it writes, fsyncs, atomically renames and removes a protected
preflight file on that filesystem. It then initializes with one Shamir share
and threshold one, captures the CLI response without printing it, and saves
the response, root token and unseal share as mode `0400` files. It refuses an
already-initialized Vault or existing recovery material. If file
extraction is interrupted after the response is saved, rerun with
`--resume-record` and the same address/CA/handoff arguments; this reads the
protected saved response and does not contact or reinitialize Vault.

After initialization, unseal and converge the observed post-init state while
converging T5820 credentials in the same run:

```sh
ansible-playbook \
  -i inventory/production/hosts.yml \
  --limit 'localhost,ai-5820-01' \
  playbooks/vault-post-init.yml \
  -e vault_post_init_enabled=true \
  -e vault_post_init_vault_addr=https://10.0.8.254:8200 \
  -e vault_post_init_ca_source=/home/mike/.local/share/vault-issue4/vault-root-ca.crt \
  -e vault_post_init_root_token_source=/home/mike/.local/share/vault-issue4/vault-root-token \
  -e vault_post_init_unseal_key_source=/home/mike/.local/share/vault-issue4/vault-unseal.key \
  -e vault_post_init_handoff_dir=/home/mike/.local/share/vault-issue4
```

Only paths and non-secret settings appear in the command. If the Vault server
was freshly initialized but the T5820 is still running, the five active API
credentials seed the empty KV records before the workload AppRole is used. The
playbook then installs the protected AppRole pair and runs the normal live
boundary checks. A newly issued snapshot AppRole pair also refreshes the
controller backup timer and verifies an encrypted snapshot.

## T5820 workload credential convergence

The dedicated `playbooks/vault-platform-credentials.yml` entrypoint converges
the authenticated gateway client, OpenCode client, shared compatibility key,
and separate worker 1 and worker 2 API keys from the `t5820-platform` AppRole.
It is scoped to `ai-5820-01`; use `--limit ai-5820-01` and explicitly set
`vault_platform_credentials_enabled=true`. Provide the CA certificate and
protected RoleID/SecretID file paths as extra-vars. These inputs are paths only;
never pass secret values on the command line or in inventory.

Set `vault_platform_credentials_opencode_env_path` to the operator's protected
OpenCode environment file (for this controller,
`/home/mike/.config/opencode/t5820-vault.env`). The controller-side helper
retrieves that one KV record directly from Vault without storing it in Ansible
facts. OpenCode's provider config uses `{env:T5820_CLIENT_TOKEN}` and the
operator's local zsh setup sources this file. The file is mode `0600` and should
remain outside Git.

The role copies the AppRole files to root-only `/etc/aihost/credentials/` as a
recoverable pair, then runs a root-owned helper on the T5820. The helper reads Vault directly over
verified TLS, keeps its short-lived token and returned values in process memory,
and writes each service credential atomically to its protected consumer file.
It does not publish secrets as Ansible facts or print them. The gateway worker
roster points worker 1 and worker 2 at distinct credential files, and each
worker's API config and environment use that same worker-specific key. Changed
worker credentials restart their worker before the gateway; unchanged runs
perform live authenticated checks without restarting services.

Before restarting any service, the helper verifies that the deployed previous
client and worker keys are accepted before any active file changes. The helper
stages and checks every replacement file, then promotes the set and restarts
changed workers before the gateway. It validates the Vault replacements at the
actual boundaries, health and Configuration B+. If any promotion, restart or
check fails, it restores the exact pre-run consumer files, reconciles affected
services, and confirms the previously working credentials still pass. The
rollback values come only from the current T5820 consumer files that passed the
pre-change boundary check; the helper does not consult historical or retired
credential backups. OpenCode's local environment file is backed up in tmpfs and
restored if the T5820 transaction cannot be reconciled. Every run verifies the
current Vault keys, all three health endpoints, and Configuration B+.

The Vault policy grants read access only to these five KVv2 records:

- `secret/local-ai/services/orchestrator-gateway/client-token`
- `secret/local-ai/hosts/ai-5820-01/opencode-client-token`
- `secret/local-ai/services/vllm/api-key`
- `secret/local-ai/services/inference/worker1-api-key`
- `secret/local-ai/services/inference/worker2-api-key`

Worker keys moved from `secret/local-ai/services/vllm/worker{1,2}-api-key` to the engine-neutral
`services/inference/` paths in `6a11f6c`; the old paths are retired and the AppRole policy no longer reads them.

Live verification (2026-10-09, from the appliance with its own client config): the `t5820-platform` AppRole logs in
over verified TLS, and all five consumer files match their Vault records by digest (gateway client token v1,
OpenCode client token v2, compatibility key v1, worker 1 and worker 2 keys v2 from 2026-10-03). The validation role
repeats the login as its `vault_access` check.

Not yet covered: the gateway's per-client registry (R6, 2026-10-07) generates the `operator`, `qualification` and
`ansible-admin` tokens with Ansible on the appliance (`/etc/local-ai/orchestrator/clients/`); they are not Vault
records. Bringing them under this lifecycle needs new KV records and policy entries (vault-post-init) plus helper
targets; until then they rotate with `orchestrator_gateway_rotate_client_tokens`.

## Encrypted Raft snapshot backup

The controller backup role uses a separate `vault-snapshot-export` AppRole. Its
five-minute token has only `read` and `sudo` on
`sys/storage/raft/snapshot`; it cannot read workload secrets. A daily systemd
timer on the Ansible controller fetches the Raft snapshot over verified TLS,
encrypts it with GPG AES-256, uploads it to the dedicated TerraMaster SMB folder,
downloads it again, and verifies decryption against the source snapshot hash.
Only ciphertext is written to the NAS. The share is guest accessible, so the
backup passphrase must remain protected and snapshots must not be exported
unencrypted.

Configure or reproduce the controller timer with:

```sh
ansible-playbook -i localhost, -c local playbooks/vault-backup-controller.yml \
  -e vault_snapshot_backup_enabled=true \
  -e vault_snapshot_backup_ca_source=/home/mike/.local/share/vault-issue4/vault-root-ca.crt \
  -e vault_snapshot_backup_role_id_source=/home/mike/.local/share/vault-issue4/snapshot-approle/role-id \
  -e vault_snapshot_backup_secret_id_source=/home/mike/.local/share/vault-issue4/snapshot-approle/secret-id \
  -e vault_snapshot_backup_passphrase_source=/home/mike/.local/share/vault-issue4/vault-backup-passphrase
```

The AppRole and GPG passphrase source files live only in the protected operator
handoff directory. The playbook copies them to root-only controller files; it
does not use the Vault root token. Keep the `vault-backup-passphrase` file with
the operator recovery material. Decrypt a downloaded snapshot with
`gpg --batch --pinentry-mode loopback --passphrase-file
/home/mike/.local/share/vault-issue4/vault-backup-passphrase --decrypt
vault-raft-YYYYMMDD.snap.gpg > vault-raft-YYYYMMDD.snap`.

Vault uses one Shamir share with a threshold of one. After a Vault service
restart, use the protected `vault-unseal.key` from the operator handoff to
unseal through the verified HTTPS API or the Vault CLI. Keep the protected root
token for manual administration and recovery only. The Vault instance remains
single node; the NAS export is a convenience for rebuilding and does not claim
automatic failover or immutable storage.

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
