# Implementation Plan: PLAN-02 - Fleet Topology Decoupling & Inventory Scoping

- **Plan ID**: `PLAN-02`
- **Specification Ref**: `SPEC-02`
- **Milestone**: `M1`
- **Target Components**: `inventory/production/hosts.yml`, `tests/test_inventory.py`
- **Estimated Effort**: 2-4 hours (Infrastructure Architect)

---

## 1. Concrete Tasks & Execution Sequence

### Task 2.1: Update `inventory/production/hosts.yml` Structure
- **File**: `inventory/production/hosts.yml`
- **Action**:
  - Remove `ai-p620-01: {}` from `production`, `inference`, `gpu`, `cluster`, and `monitoring`.
  - Add `uncommissioned_hosts: { hosts: { ai-p620-01: {} } }`.
  - Add `vault_servers: { hosts: { vault-vm: { ansible_host: 10.0.8.109, ansible_connection: ssh } } }`.
- **Validation**:
  ```bash
  .venv/bin/ansible-inventory -i inventory/production/hosts.yml --list
  ```

### Task 2.2: Verify Inventory Host Resolution
- **Command**:
  ```bash
  .venv/bin/ansible-playbook -i inventory/production/hosts.yml --list-hosts playbooks/site.yml
  ```
- **Expected Output**: Resolves exactly `ai-5820-01` under `ai_hosts`.

### Task 2.3: Reconcile Inventory Contract Test Suite
- **File**: `tests/test_inventory.py`
- **Action**:
  - Review `test_production_inventory_parses_and_keeps_host_metadata_authoritative` and related tests.
  - Ensure assertions recognize `ai-5820-01` as the active production host while `ai-p620-01` is classified under `uncommissioned_hosts`.
- **Validation**:
  ```bash
  .venv/bin/pytest tests/test_inventory.py -v
  ```

### Task 2.4: Playbook Syntax Verification Across All 17 Playbooks
- **Command**:
  ```bash
  make syntax
  ```
- **Success Criteria**: 0 syntax errors, 0 host pattern warnings.

---

## 2. Rollback & Precautionary Steps
- If playbook host selection is broken, revert `inventory/production/hosts.yml` using `git checkout -- inventory/production/hosts.yml`.
