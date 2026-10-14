# Implementation Plan: PLAN-06 - Vault Authority Boundary & Disaster Recovery Drill

- **Plan ID**: `PLAN-06`
- **Specification Ref**: `SPEC-06`
- **Milestone**: `M4`
- **Target Components**: `roles/vault_platform_credentials/`, `docs/vault.md`, `playbooks/vault-backup-controller.yml`
- **Estimated Effort**: 4-6 hours (Platform Engineer)

---

## 1. Concrete Tasks & Execution Sequence

### Task 6.1: Inventory & Playbook Mapping
- In `inventory/production/hosts.yml`:
  - Ensure `vault_servers` group maps cleanly to `vault-vm` (`10.0.8.109`).
- Execute syntax check:
  ```bash
  .venv/bin/ansible-playbook -i inventory/production/hosts.yml --syntax-check playbooks/vault-server.yml
  ```
- Confirm zero warnings.

### Task 6.2: Staging Client Token Rotation Drill
- Execute credential rotation test using the staging `qualification` client token:
  ```bash
  ansible-playbook -i inventory/production/hosts.yml playbooks/vault-platform-credentials.yml \
                   -e vault_rotate_client_id=qualification
  ```
- Verify:
  - Gateway restarts cleanly.
  - Old token returns HTTP 401.
  - Newly generated token stored in Vault returns HTTP 200.

### Task 6.3: Publish Vault Unseal & DR Runbook
- In `docs/vault.md`:
  - Detail step-by-step operator commands for recovering from a Vault VM reboot.
  - Document Shamir key retrieval from out-of-band secure storage.
  - Provide test command:
    ```bash
    vault operator unseal <key1>
    vault operator unseal <key2>
    vault operator unseal <key3>
    curl -s https://vault.local:8200/v1/sys/health | jq .
    ```

### Task 6.4: Execute Vault Contract Tests
- **Command**:
  ```bash
  .venv/bin/pytest tests/test_vault_contract.py tests/test_vault_platform_credentials.py tests/test_vault_post_init.py -v
  ```
- **Success Criteria**: 100% pass across all tests and subtests.

---

## 2. Acceptance Criteria
1. `make syntax` passes without `vault_servers` warnings.
2. Token rotation drill executes without service disruption.
3. Emergency unsealing runbook verified by secondary operator.
