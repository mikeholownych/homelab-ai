# Issue #4: Vault deployment gap and production design

Status: operator authorization for production installation and integration was
provided on 2026-09-30. Deployment and authority migration are not yet evidenced;
this document does not establish that Vault issued any current gateway or
worker credential. Current connectivity and validation results are recorded in
the [infrastructure preflight](issue-4-infrastructure-preflight-20260930.md).

## Requirements to implementation reconciliation

| Requirement | Repository evidence | Finding |
|---|---|---|
| Install and pin Vault server | `playbooks/site.yml`, `playbooks/bootstrap.yml`, `playbooks/commission.yml`; no Vault server role at base `68de433` | Missing. Deployment entrypoints do not install a Vault server. |
| Server configuration and identity | `roles/vault_integration/` has client defaults/tasks/templates only | Missing server service identity, listener, storage, service unit, network rules, and server health checks. |
| Initialize, unseal, and recover | `docs/vault.md` discusses AppRole runtime reads and SecretID lifecycle; no init/unseal/recovery task or runbook | Missing. No safe initialization or recovery authority is evidenced. |
| Policies/authentication | `roles/vault_integration/tasks/authenticate.yml`, `read.yml`; `docs/vault.md` AppRole examples | Client-side AppRole login and KVv2 read are implemented. Server-side auth mount, policy installation, role provisioning and audit setup are not deployed by Ansible. |
| Credential delivery | `roles/vault_integration/tasks/resolve_credentials.yml`, `bootstrap.yml`; `docs/vault.md` | Controller-side protected AppRole input files and non-secret references exist. This does not prove a Vault server exists or that it issued the AppRole credentials. |
| Gateway/vLLM credential custody | `roles/vllm_xpu/tasks/main.yml` reads a Vault KV value; `templates/vllm-config.yaml.j2` gives that value to vLLM; `orchestrator_gateway/__main__.py` reads gateway client/worker credentials from env/file references | Vault is a retrieval source if enabled. The code does not show Vault generated the value or invalidated a prior value. Current Ansible rendering places the worker key in protected local config/env files; `README.md` acknowledges those runtime copies. |
| Backup and disaster recovery | No Vault server data path, snapshot task, backup destination, restore drill or custody contract found | Missing. |
| Production authority | `inventory/production/` has no Vault server settings; issue #3 preflight records no host Vault service, agent, CLI or issuer/revoker evidence | Unknown. A client placeholder (`https://vault.example.invalid`) is not authority evidence. |

The actual deployment entrypoints are `playbooks/site.yml` (imports baseline,
then conditionally runs the Vault *client* preflight when
`vault_integration_enabled` is true), `playbooks/bootstrap.yml` (conditionally
validates controller credentials/renders references), and
`playbooks/commission.yml` Phase 2 (same conditional client bootstrap). None
includes a server role. `inventory/production/host_vars/ai-5820-01.yml` configures
the vLLM consumer but contains no Vault server topology.
The gateway application code has file/environment credential inputs, but the
repository has no Vault server deployment role or gateway Ansible role that
proves production issuer or delivery. The dated issue #3 preflight supplies the
deployed service-unit credential references and identifies OpenCode as a
gateway client; those runtime paths remain outside this proposed change.
It records distinct gateway client, OpenCode client, and gateway-to-worker
credential references under `/etc/local-ai/orchestrator/`, plus the worker API
key reference under `/etc/local-ai/vllm/`. Both vLLM workers consume their
protected worker configuration; production acceptance must prove auth at each
worker boundary instead of inferring it from one shared path.

Relevant history:

- `e50275c74541daa9eb64aa3266d1a607b46b5671` (“feat(vault): retrieve secrets
  from Vault at runtime”) added `docs/vault.md`, `roles/vault_integration/`,
  requirements and conditional client hooks. It did not add server installation.
- `1675c11` and `b653353` hardened client-side fail-closed/path and credential
  handling; neither adds server deployment.
- `c0fad08924e2432b9e19efaae4ace8ccd3aceb08` added Vault-backed API-key reads to
  inference consumer roles. It is retrieval/configuration, not key issuance.
- `046124fe8cfa29d1af636f565e99d7fc71f117bd` added commissioning phases; Phase 2
  still conditionally invokes only `vault_integration` bootstrap.
- `075fee9`/`b7947bf` document existing API-key fallback/persistence behavior in
  the vLLM role; that does not establish the current value's issuer.

Deployment evidence is recorded separately in
`phase14/evidence/phase14_b_plus_production_deployment_report.md` and the issue
#3 preflight. Those records establish a healthy Configuration B+ application
deployment, not Vault deployment. The issue #3 preflight records gateway
`t5820-gateway-44e31e6` / `44e31e6b01dae22de1eab2550ce981e89cef556d`, the
production host and service health, systemd credential references, and no
demonstrated Vault server/agent/CLI or credential issuer/revoker. No credential
values are reproduced here. This evidence is a dated observation, not a fresh
Vault server inventory.

The repository documentation is incomplete: `README.md` calls Vault the sole
authority and describes AppRole reads, while its runtime note acknowledges that
retrieved API keys are rendered into local runtime files until a later
convergence/restart. Neither statement demonstrates Vault server installation
or key issuance.

## Production-specific target architecture

Issue #4 comments provide Proxmox screenshot evidence for a separate Vault VM:
VM 109 named `vault` on `pve2`, at `10.0.8.254`, allocated 2 vCPU, 8 GiB RAM,
and a 100 GiB boot disk. This resolves the proposed hypervisor placement;
guest identity/readiness is not verified because this execution environment
blocked SSH before authentication. See the [preflight record](issue-4-infrastructure-preflight-20260930.md).
The expected NAS is a separate TerraMaster F4-210 at `192.168.1.124`, reported
with TOS `4.2.41-2203011629` and about 10.66 TB free, but its export and actual
access settings could not be inspected.

The F4-210 1 GB official specification lists NFS and Kerberos support but marks
shared-folder snapshots and WORM as unsupported. This is capability information,
not proof of an enabled export. The actual export, NFS version/security flavor,
client allowlist, root mapping, UID/GID handling, backing filesystem, free space,
and retention controls remain unknown. Treat NAS-native immutable retention as
unavailable unless an administrator verifies a different supported external
mechanism. Its separate chassis does not prove power, network, site, or admin
failure-domain independence.

Target design for the provisioned topology: keep live Raft at `/var/lib/vault`
on a verified local block-backed filesystem on VM 109. After the existing export
and controls are verified and approved, create Raft snapshots on that VM into a
root-only local staging directory, encrypt them on the VM before NFS transfer,
and write only ciphertext plus a non-secret manifest/checksum to the export.
Use public-key encryption (or an operator-approved equivalent) so the VM can
encrypt without holding decryption authority. Keep the decryption private key
with independent offline recovery custodians, separate from Vault unseal
material and from the NAS/admin accounts. The backup plan must specify access
revocation, retention/deletion protection and RPO/RTO; NFS write access alone
does not provide immutability. No export, encryption tool/key, custodian,
retention process or NFS mount is selected or configured in this branch.

When implemented, snapshot automation should use a dedicated least-privilege
Vault identity limited to snapshot save and a credential-delivery path that
does not require the Vault root token. NFS mount authentication must also remain
available independently of Vault so a restore does not depend on the system it
is recovering. The role/policy and these two credential authorities are not
selected until the current provisioner and recovery design are approved.

Clean-VM restore candidate: provision a fresh isolated VM from an approved OS
image; verify OS, local block storage, disk reserve and TLS trust; install the
same pinned Vault binary/config; retrieve ciphertext from the NAS using the
separately authorized read path; decrypt only in a protected local staging
area using offline-custodian recovery; restore with the Vault Raft snapshot
command; then complete the approved seal/unseal ceremony and verify seal state,
health, policies, auth methods and audit delivery before any clients can reach
it. HashiCorp documents that snapshot restore returns before background restore
work completes, so acceptance must wait for Vault to be fully unsealed and
post-unseal setup complete ([snapshot save](https://developer.hashicorp.com/vault/docs/sysadmin/snapshots/save),
[Raft snapshot restore](https://developer.hashicorp.com/vault/docs/commands/operator/raft)).
Actual seal mode, CA, recovery-key custody, backup decryption authority,
credential issuer and acceptance of this restore flow remain operator decisions.

1. **Trust bootstrap.** Keep the TLS issuing CA private key outside the Vault
   host and outside Ansible. Obtain a CA-signed server certificate for the
   approved Vault DNS name and a separately delivered CA chain. Pin the Vault
   release and verify the release archive checksum against HashiCorp's signed
   release checksums. The implementation foundation pins Vault 2.1.1 and its
   amd64 archive SHA-256; refresh the pin only through reviewed release
   maintenance.
2. **Storage and network.** Use integrated Raft with durable state under
   `/var/lib/vault`, separate from `/var/lib/local-ai` model storage. Bind API
   8200 and cluster 8201 only to explicitly approved management/cluster
   addresses. Firewall policy must permit only administrators, declared
   workload clients, and Raft peers. The evidence does not establish disk
   encryption, swap policy, or suitable disk health; inspect those before use.
   A single node has no HA; production approval must cover outage behavior.
3. **TLS and service identity.** Dedicated `vault` system account, root-owned
   binary/config, protected TLS private key provisioned independently, TLS
   certificate hostname validation from every client, minimum TLS 1.2, and
   hardened systemd service. Ansible must never generate or copy a CA private
   key. The new role checks externally provisioned TLS files and never
   initializes Vault.
4. **Initialization and unseal.** Conduct `vault operator init` once in an
   operator ceremony, not Ansible. If no approved KMS/HSM auto-unseal exists,
   use Shamir shares with an operator-approved quorum (the Vault default is
   five shares/three threshold) distributed to distinct custodians in separate
   approved offline custody systems. Store recovery material outside the host
   and outside the same backup account. Root token is a one-time bootstrap
   artifact: create policies/auth/audit, then revoke it. No root token or
   unseal share enters Git, Ansible vars, shell history, logs, or service args.
5. **Policies and workload auth.** Keep existing AppRole integration as a
   transitional auth path, with one role per service identity and exact KVv2
   read paths; separate gateway-to-worker auth from vLLM worker API keys. No
   list/write on runtime roles. Prefer short TTL tokens and wrapped, bounded
   SecretIDs delivered out-of-band. Evaluate machine-bound auth only after
   available host identity and trust evidence is reviewed. Audit sinks must be
   provisioned and tested before workloads use Vault; ship to two independent
   protected destinations and monitor audit-device unavailability.
6. **Credential generation vs custody.** Vault KV read proves custody/retrieval
   only. It does not prove issuance. Identify the product/service mechanism
   that creates gateway client tokens and vLLM API keys, write replacement
   values through the approved secret provisioner, then configure each service
   to accept them. The issue #3 exposed credentials remain compromised until
   the relevant gateway and each worker authentication boundary rejects them.
   Immediate containment remains issue #3 work and must not wait for this Vault
   rollout.
7. **Delivery and rotation.** Deliver per-service wrapped AppRole credentials
   out-of-band into root-protected systemd credential files or an independently
   bootstrapped Vault Agent. Render application credentials only to protected
   runtime files, never Ansible facts/logs. Rotation must account for consumers
   that accept only one active key: vLLM config has a singular `api-key`, so
   plan a bounded worker restart or a proven dual-key transition. Do not claim
   zero downtime without dual-acceptance evidence.
8. **Backup and DR.** Schedule encrypted Raft snapshots to an off-host,
   independently administered destination; retain versioned snapshots and
   tested access controls. Keep unseal/recovery custody separate from snapshot
   storage. Document RPO/RTO and restore onto an isolated host with network
   egress fenced; verify policies, auth mounts, audit sinks and test credentials
   after restore. A backup is not accepted until restoration is demonstrated.

HashiCorp documents checksum/signature verification, Raft storage, TLS listener
configuration, initialization and AppRole separately; these are distinct
operations and the client integration does not satisfy server deployment
([binary verification](https://developer.hashicorp.com/well-architected-framework/verify-hashicorp-binary),
[Raft](https://developer.hashicorp.com/vault/docs/configuration/storage/raft),
[TLS listener](https://developer.hashicorp.com/vault/docs/configuration/listener/tcp/tcp-tls),
[init](https://developer.hashicorp.com/vault/docs/commands/operator/init),
[AppRole](https://developer.hashicorp.com/vault/docs/auth/approle)).

## Changes in this branch

- Added `roles/vault_server/`: explicit approval gate, pinned binary download
  with checksum, dedicated service identity, restrictive directories, externally
  provisioned TLS inputs with chain/name/validity/key-pair checks, Raft/TLS HCL,
  hardened systemd unit, OS/architecture gates, a local-filesystem plus
  explicit free-space gate for Raft, and a protected marker that refuses to
  overwrite detected unmanaged Vault service/config/data artifacts.
- Added `playbooks/vault-server.yml` as a separate `vault_servers` entrypoint.
  It is intentionally not imported by production `site.yml`, `bootstrap.yml`,
  or `commission.yml`. It does not initialize/unseal Vault, provision policies,
  create credentials, configure firewall rules, or enable/start the service by
  default. Explicit start/enable inputs are required; omitted values preserve
  existing systemd enable and active state.
- Added a localhost-only Ansible fixture and [reproducible validation commands](../../tests/fixtures/issue4/README.md).
- Did not add backup scheduling/transfer because the NAS export, export access
  controls, independent mount authority, encryption implementation/key custody
  and retention authority are not verified or approved. No credential issuer
  decision was made.
- No production inventory or active credential authority changed. No production
  host was contacted for mutation.

Ansible Core 2.21.3 syntax check, ansible-lint 26.8.0 and yamllint 1.38.0 pass;
the 5 contract tests pass. The localhost fail-closed execution attempt was
blocked before the play began by the sandbox's Ansible local-RPC process/socket
restriction, so no role task execution result is claimed. Full command output
and infrastructure access limits are recorded in the [preflight evidence](issue-4-infrastructure-preflight-20260930.md).

## Migration and acceptance plan

1. **Gate 0 — issue #3 containment:** independently prove both exposed
   credentials rejected and replacements accepted at gateway/worker boundaries;
   verify OpenCode and every identified client. This is not a prerequisite to
   creating a Vault design, but issue #3 immediate invalidation must happen
   independently and promptly. Vault migration cannot be used to imply
   containment.
2. **Gate 1 — authority and recovery approval:** record existing secret
   provisioner, Vault placement, CA source, custodian quorum, backup authority,
   network/firewall owner, approved Vault release, and rollback/recovery path.
   Confirm whether current production secret delivery is actually Vault-backed.
3. **Gate 2 — isolated restore-capable deployment:** apply the separate role to
   a disposable localhost/container/VM fixture only; validate config, service
   identity, listener restrictions, repeat convergence, and failure behavior.
   Complete init/unseal, policy/auth/audit, snapshot and restore drills there.
4. **Gate 3 — production Vault service:** after explicit change approval, deploy
   Vault without workload cutover, verify TLS/trust, storage durability, audit,
   seal monitoring, backup and restore. Do not change the active credential
   authority until the independent recovery path is proven.
5. **Gate 4 — staged consumers:** migrate (a) the gateway's inbound client
   credential, (b) the gateway's worker-auth credential, (c) each of the two
   TP=1 vLLM workers' API-key configuration, and (d) OpenCode's client
   credential via the existing tunnel. Prove new-auth success and old-auth
   rejection independently at the gateway and both worker boundaries, then
   prove OpenCode and each gateway route work. Preserve deployed model IDs, B+
   scheduling and service config. Use a bounded maintenance window where
   single-key services require restart.
6. **Rollback:** keep a prepared configuration rollback and service recovery
   path that does not reinstall the compromised credentials. If rollback would
   restore an exposed key, it is not an acceptable rollback. Recovery must use
   the new credential plus tested Vault snapshot/unseal custody, or a separately
   approved emergency replacement credential. Stop before cutover if this path
   is unavailable.
7. **Acceptance:** independent reviewer verifies Vault identity/seal state,
   TLS and network boundary, policies, audit delivery, backup/restore drill,
   replacement auth on gateway/OpenCode/workers, rejection of both exposed
   credentials, worker/gateway health, B+ identity/scheduling/model identity,
   no unexpected restarts/config drift, and secret-free evidence. Only then may
   issue #4 be considered for closure by its operator.

## External execution dependencies still unverified

- A trusted SSH host-key fingerprint, SSH host CA key, or execution host that
  already trusts VM 109 is required before guest inspection or configuration.
  Current SSH did not authenticate and no remote command ran.
- The guest's existing Vault state and filesystem layout must be inspected
  before changes; initialized or unmanaged data must never be overwritten.
- TLS trust must be established on Vault and its T5820 consumers before any
  client sends credentials to Vault. Production client configuration and
  service access remain unverified until trusted T5820 access is available.
- NAS export and access-control status are unknown. Per operator direction,
  this is optional for Vault installation; if no suitable export is available,
  document that backup limitation and continue the working deployment.
