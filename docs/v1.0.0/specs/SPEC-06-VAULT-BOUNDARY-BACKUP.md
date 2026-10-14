# Technical Specification: SPEC-06 - Vault Authority Boundary & Disaster Recovery

- **Specification ID**: `SPEC-06`
- **Related Finding**: `F-05` (Missing Vault control plane boundary in inventory)
- **Related Requirements**: `REQ-SEC-02`, `REQ-OPS-05`
- **Target Milestone**: `M4` (Observability, Operational Hardening & Vault Control Plane)
- **Status**: Ready for Implementation

---

## 1. Problem Statement & Evidence
- **Undefined Vault Server Boundary**: Vault is the single secret authority for the platform. However, while client AppRole integration (`roles/vault_integration`) and credential synchronization (`roles/vault_platform_credentials`) are heavily tested and operational, the management, backup, unsealing, and disaster recovery of the Vault server itself (running on VM 109) are not represented in version-controlled inventory.
- **Syntax Warning**: `playbooks/vault-server.yml` targets `hosts: vault_servers`, which is unmapped in `inventory/production/hosts.yml`.
- **Operational Risk**: If the Vault server VM suffers an unrecoverable failure or crash (as observed in historical incident records), the platform cannot retrieve client tokens, worker API keys, or Hugging Face credentials upon restart.

---

## 2. Desired Behavior & Scope
- **Scope**:
  - Define the `vault_servers` group in `inventory/production/hosts.yml` with host parameters matching the external Vault VM (`10.0.8.109`), scoped to maintenance and disaster recovery execution.
  - Document the explicit separation between **Vault client consumption** (automated via AppRole in `playbooks/site.yml`) and **Vault server lifecycle management** (isolated manual/operator-gated execution via `playbooks/vault-server.yml` and `playbooks/vault-backup-controller.yml`).
  - Publish an authoritative disaster recovery and unsealing runbook in `docs/vault.md`.
  - Validate client token rotation using `playbooks/vault-platform-credentials.yml` with a staging client token, confirming that the old token returns HTTP 401 and the new token returns HTTP 200.
- **Non-Goals**:
  - Automatically storing unseal keys or root tokens in the repository.

---

## 3. Disaster Recovery & Unsealing Runbook Structure
- **Unsealing Protocol**:
  - Vault server restart initiates in a sealed state (HTTP 503 on `/v1/sys/health`).
  - Unsealing executed strictly via out-of-band operator shamir keys or dedicated unseal keys stored in protected controller paths (`/etc/aihost/vault/unseal.keys`).
  - Verification via `curl -s https://vault.local:8200/v1/sys/health` asserting `sealed: false`.
- **Snapshot Backup Protocol**:
  - `playbooks/vault-backup-controller.yml` takes periodic encrypted Raft snapshots.
  - Snapshots encrypted client-side using age/GPG public key and persisted under `/var/backups/aihost/vault/`.

---

## 4. Acceptance Criteria
1. `make syntax` passes without `vault_servers` warnings.
2. `pytest tests/test_vault_contract.py` and `pytest tests/test_vault_platform_credentials.py` pass 100%.
3. `docs/vault.md` includes the authoritative emergency unseal and disaster recovery procedures.
