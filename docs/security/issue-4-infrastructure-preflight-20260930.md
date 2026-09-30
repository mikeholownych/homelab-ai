# Issue #4 infrastructure preflight — 2026-09-30

This record contains no credentials. Operator-reported observations are kept
separate from checks run in this execution environment.

## Operator evidence from issue #4 comments

| Item | Reported observation | Evidence limit |
|---|---|---|
| Hypervisor VM | Proxmox VM 109 `vault`, node `pve2`, running at `10.0.8.254`; 2 vCPU, 8 GiB RAM, 100 GiB boot disk | Reported from operator screenshots in issue comment `5901730476`; not independently checked in Proxmox or in the guest. |
| NAS | TerraMaster F4-210, device `TNAS-19A7`, TOS `4.2.41-2203011629`, address `192.168.1.124`, 1,024 MB RAM, about 10.66 TB free | Reported from operator screenshots in issue comment `5901730476`; not independently checked against NAS status/configuration. |
| Administrative account | SSH user `mike` on the Vault VM | Operator-provided; credentials/fingerprint and successful SSH authentication were not established here. |

## Checks attempted in this execution

- A read-only SSH discovery command to `mike@10.0.8.254` failed before host
  authentication: `error: Q_PARENT env variable not set`, followed by
  `socket: Operation not permitted` and `ssh: connect ... failure`. No remote
  command ran. Guest hostname/host keys, OS/kernel, CPU and memory available,
  disk/filesystem layout and free space, routes/interfaces, Vault binary/state,
  service/configuration, and SSH/Ansible reachability therefore remain unknown.
- Local `findmnt -rn -t nfs,nfs4,cifs` returned no mounts. The local environment
  does not have `showmount`, `rpcinfo`, or `nfsstat`. The NAS was not contacted;
  existence of an export, export client allowlist, root mapping, UID/GID policy,
  NFS version, read/write behavior, filesystem semantics, retention, and
  deletion controls remain unverified.
- The execution sandbox denied SSH socket access. No alternate network path was
  used. No production or NAS state was changed.

## Public product documentation (capability only, not current configuration)

TerraMaster's F4-210 **1 GB** specification lists NFS, NFS Kerberos
authentication, shared-folder AES encryption, and firewall support. The same
specification marks both shared-folder snapshots and WORM unsupported. This
matches the operator-reported RAM class, but does not prove which exact unit
configuration is active or that TOS exposes all features identically at the
reported firmware. Do not rely on NAS-native immutability or NAS shared-folder
encryption as a substitute for client-side backup encryption.

The [F4-210 specification](https://www.terra-master.com/fr/pages/f4-210-specification)
and [TOS 4.2.41 ARM release note](https://forum.terra-master.com/en/viewtopic.php?t=4117)
support the model/firmware capability context only. TOS 6 help pages are not
treated as evidence for this TOS 4.2.41 device.

## Ansible development environment

The repository's local development virtual environment provides Ansible Core
2.21.3, ansible-lint 26.8.0, and yamllint 1.38.0. Ansible initially tried to
create its temporary controller directory under the sandbox-read-only
`/home/mike/.ansible/tmp`; the issue #4 fixture config redirects Ansible temp
files into `/tmp/issue4-ansible-tmp` instead. Its inventory contains only
`localhost` with the local connection plugin. The commands and results were:

- `ansible-playbook --syntax-check -i tests/fixtures/issue4/inventory.ini playbooks/vault-server.yml` — passed.
- `ansible-playbook --list-hosts ...` — listed only `localhost`.
- `ansible-lint roles/vault_server playbooks/vault-server.yml` — passed with
  zero failures/warnings (ansible-lint emitted only its PATH-adjustment notice).
- `yamllint` on the four new YAML files — passed.
- `pytest -q tests/test_vault_server_contract.py` — 5 passed.
- Expected fail-closed execution with `--check`, localhost inventory and
  `vault_server_manage=false` — **blocked before play execution**: Ansible
  reported `Local RPC server did not start` in this restricted runner. It did
  not reach the assertion, so this is not a passing execution test.

These checks do not establish connectivity to the Vault VM.

## Required follow-up before infra acceptance

The execution environment needs an approved network path that permits
read-only SSH to `mike@10.0.8.254` and read-only inspection access to the NAS
administration interface or an authorized read-only NAS account. If command-line
NFS probes are required, install/enable tools only in a disposable test client,
not on the Vault VM. An operator must supply the SSH host-key fingerprint or
another trusted host identity source before accepting guest identity evidence.

## Follow-up in the current execution context (2026-09-30)

The current shell has the repository development virtual environment and can
run Ansible's localhost execution path. This supersedes the earlier local RPC
restriction observation for this session only; it does not establish VM access.

- Ansible Core 2.21.3 syntax-check passed for
  `playbooks/vault-server.yml`; the fixture inventory listed only `localhost`.
- `ansible-lint roles/vault_server playbooks/vault-server.yml` passed with
  zero failures and warnings.
- `yamllint` passed on the four YAML files added for issue #4. Jinja templates
  are excluded because they are not standalone YAML documents.
- `pytest -q tests/test_vault_server_contract.py tests/test_vault_contract.py
  tests/test_no_secrets.py` passed: 29 passed, 11 skipped, 65 subtests passed.
- Check-mode execution against the localhost-only fixture gathered local facts
  and stopped at the intended `vault_server_manage=false` assertion (exit 2).
  This confirms the fail-closed guard executes; it does not exercise role
  mutation or a server deployment.
- SSH to `mike@10.0.8.254` did not authenticate. The guest key is not present
  in this runner's trusted `known_hosts`; no keyscan was accepted as identity
  proof, and no remote command ran. A trusted SHA256 host-key fingerprint, SSH
  host CA key, or execution host already configured to trust the guest is still
  required before production inspection or configuration.

## Live execution result (2026-09-30)

The operator accepted the VM's presented host key. The task-specific known-hosts
entry fingerprint is `SHA256:jOVqARHOUrsGwBBRDAH2Tz2b7MwjF/XDksarJXHzt5A`; SSH
then verified the guest as `vault`, Ubuntu 24.04, 2 vCPU, 7.8 GiB RAM and a
100 GiB `/dev/vda1` ext4 root filesystem with more than 100 GB free. Before
deployment, the guest had no Vault package/binary, service, configuration or
data directory. This resolves the earlier read-only preflight.

Ansible then applied the repository role to that single host: 51 tasks succeeded,
18 changed resources and none failed. Vault 2.1.1 is installed and the systemd
service is enabled and running. It uses local Raft storage at `/var/lib/vault`,
the dedicated `vault` account, IP-SAN TLS verified by the operator host, and a
host firewall allowing SSH and the Vault API only from `10.0.8.95` and T5820
`10.0.8.5`. Port 8201 is not allowed inbound. The configured local free-space
reserve is 20 GiB. The Vault audit log directory/file exist, but the Vault audit
device was not enabled.

Vault initialization **did occur**, but the one-time initializer expected the
wrong JSON field for the unseal share and stopped before writing the share or
initial root token into the protected handoff. The successful CLI output was
consumed by that helper and not retained or printed. Live TLS `/sys/seal-status`
confirms `initialized=true`, `sealed=true`. `/var/lib/vault` now contains the
new Raft state; this store was created in this execution and has no workload KV
records or configured policies/authentication because the helper stopped
before its first API configuration request. The handoff directory currently
contains TLS CA material only, **not** a Vault unseal key or administrative
token. Vault cannot be unsealed or used in this state.

Do not run initialization again against this store. Recovery requires the
operator to explicitly authorize the specific destructive action of stopping
`vault.service` and deleting the contents of `/var/lib/vault` on VM 109, then
rerunning initialization with a helper that recognizes the actual JSON schema.
That action is not performed here. NAS access and export remain unverified;
no backup was configured. T5820 credentials/services were not changed and no
credential invalidation or live application acceptance is claimed.

## Final deployed result (2026-09-30)

The operator subsequently authorized resetting `/var/lib/vault`. Before the
reset, the sealed Raft directory was archived on the Vault VM at
`/root/vault-reset-backup-20260930.tar`; the archive compared successfully,
contained seven entries, and was mode `0600` root-owned. Only
`/var/lib/vault` was removed and recreated as `vault:vault` mode `0700`. The
Vault Ansible role then reran successfully.

Vault 2.1.1 is initialized on local Raft storage, enabled and active under the
dedicated `vault` service identity. Its TLS certificate is verified against the
operator-held CA, the firewall permits only the operator controller and T5820
to the API, and the file audit device, KVv2 mount and AppRole auth mount are
enabled. Initialization uses one Shamir share and threshold one. A service
restart sealed Vault as expected; the protected handoff share unsealed it, and
AppRole authentication succeeded after restart. The verified handoff is in
`/home/mike/.local/share/vault-issue4`; it contains the unseal key, manual
administrative token, CA custody, workload AppRole files, backup AppRole files,
and the snapshot encryption passphrase. Secret contents are not recorded here.

The T5820 now has separate Vault-issued gateway, OpenCode, worker 1 and worker 2
credentials. The worker roster points at separate protected key files; worker
configuration and environment values were converged from KVv2. The controller
Ansible role authenticates from protected AppRole files, fetches secrets on the
T5820 without publishing Ansible facts, writes them atomically, and verifies
live authentication. A repeat Ansible run completed with zero changes.

Authentication boundary evidence: before migration, the currently deployed
gateway/OpenCode client credentials and both worker credentials returned HTTP
200. After migration, a historical T5820 client credential from the
pre-migration provider configuration returned HTTP 401 at the gateway. Prior
worker keys recovered from the worker configuration/environment backups
returned HTTP 401 at both worker APIs; those backup values were then scrubbed
to prevent reuse. The historical client config was scrubbed after its boundary
check. The Vault replacement gateway and OpenCode client credentials and both
worker keys returned HTTP 200. No token
values or hashes are included in this record.

A fresh OpenCode CLI run on 2026-09-30 returned the requested marker with exit
status zero. In the same 26-second window, gateway evidence records matched
request `c71f3af7-bc2e-4154-876a-a7a9784f1b52`: `worker_selected` for
`b0-live-tp1-worker2` at 02:53:05 UTC and `response_validated` at 02:53:19 UTC.
The gateway and both workers are active, all three health endpoints return
HTTP 200, and `ORCHESTRATOR_SCHEDULING_MODE=CONFIGURATION_B_PLUS` remains set.

The TerraMaster `public` SMB share accepted creation of the dedicated
`homelab-ai-vault-issue4` folder. A separate snapshot-only AppRole has a
five-minute token with only `read` and `sudo` on `sys/storage/raft/snapshot`;
it cannot read workload secrets. A root-run daily controller timer fetches a
snapshot over verified TLS, encrypts it with GPG AES-256, uploads it, downloads
it, decrypts it in `/run`, and confirms its hash matches the source. The first
verified ciphertext was `vault-raft-20260930.snap.gpg` (41,993 bytes). The
timer is active and the one-shot service completed successfully. The NAS share
is guest accessible, so only client-side encrypted snapshots are stored there.

Checks completed for the final implementation:

- Both Vault and credential playbooks pass Ansible syntax checks.
- Ansible lint passed with zero failures or warnings; yamllint passed.
- The Vault contract and platform credential tests passed: 18 passed, 11
  skipped, 65 subtests passed.
- The Vault server deployment role and T5820 credential role both ran against
  their real hosts; the credential role reran idempotently.

The recovery handoff and reproducible commands are documented in
[`docs/vault.md`](../vault.md). This section supersedes the earlier failed
initialization and unverified-NAS statements above; those statements remain as
the accurate history of the first attempt.
