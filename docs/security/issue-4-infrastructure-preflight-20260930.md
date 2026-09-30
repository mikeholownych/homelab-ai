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

Therefore the guest OS/state, Vault installation or initialization, TLS and
network configuration, NAS export, credential migration/revocation, service
health, OpenCode behavior, and Configuration B+ health remain unverified. The
Ansible server role is a committed local implementation foundation only until
those live checks can be performed.
