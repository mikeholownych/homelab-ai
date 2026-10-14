# Technical Specification: SPEC-02 - Fleet Topology Decoupling & Inventory Scoping

- **Specification ID**: `SPEC-02`
- **Related Findings**: `F-04` (Uncommissioned `ai-p620-01` in production inventory), `F-05` (Missing `vault_servers` group in inventory)
- **Related Requirements**: `REQ-PROV-05` (Hardware Scope Decoupling), `REQ-OPS-05`
- **Target Milestone**: `M1` (Fleet Topology & Hardware Scope Decoupling)
- **Status**: Ready for Implementation

---

## 1. Problem Statement & Evidence
1. **Uncommissioned Node in Production**: `inventory/production/hosts.yml` places `ai-p620-01` inside the `production`, `inference`, `gpu`, and `monitoring` groups. However, `inventory/production/host_vars/ai-p620-01.yml` contains `ansible_host: CHANGE_ME`. The host has no DNS record, no IP connectivity, and has never been commissioned. Running any playbook against `production` or `ai_hosts` without `--limit ai-5820-01` fails with SSH unreachable errors.
2. **Missing Vault Servers Inventory Group**: `playbooks/vault-server.yml` targets `hosts: vault_servers`, but `inventory/production/hosts.yml` contains no `vault_servers` group. This triggers an Ansible warning during `make syntax` (`[WARNING]: Could not match supplied host pattern, ignoring: vault_servers`).

---

## 2. Desired Behavior & Scope
- **Scope**:
  - Reorganize `inventory/production/hosts.yml` so that active production groups (`production`, `inference`, `gpu`, `monitoring`, `cluster`) contain strictly the commissioned node: `ai-5820-01`.
  - Create a new top-level group `uncommissioned_hosts` containing `ai-p620-01` with explicit documentation that it represents an uncommissioned future profile.
  - Define a `vault_servers` group in `inventory/production/hosts.yml` mapped to the declared Vault VM (`10.0.8.109` or `localhost` connection mode), eliminating the syntax check warning.
  - Ensure that running `ansible-playbook -i inventory/production/hosts.yml --list-hosts production` returns only `ai-5820-01`.
- **Non-Goals**:
  - Deleting the `ai-p620-01.yml` hardware profile or host variable definitions.
  - Physically provisioning the Lenovo P620 workstation.

---

## 3. Configuration & Schema Details
- **`inventory/production/hosts.yml` Revision**:
```yaml
all:
  children:
    ai_hosts:
      children:
        production: {}
        inference: {}
        gpu: {}
        cluster: {}
        monitoring: {}
    observability:
      hosts:
        grafana: {}
    vault_servers:
      hosts:
        # Vault VM control plane boundary (unmanaged in routine site convergence)
        vault-vm:
          ansible_host: 10.0.8.109
          ansible_connection: ssh
    production:
      hosts:
        ai-5820-01: {}
    inference:
      hosts:
        ai-5820-01: {}
    gpu:
      hosts:
        ai-5820-01: {}
    cluster:
      hosts:
        ai-5820-01: {}
    monitoring:
      hosts:
        ai-5820-01: {}
    uncommissioned_hosts:
      hosts:
        ai-p620-01: {}
```

---

## 4. Operational & Compatibility Implications
- **Safety**: Prevents operator errors where running `ansible-playbook playbooks/site.yml` attempts to connect to `CHANGE_ME`.
- **Reproducibility**: Eliminates mandatory `--limit ai-5820-01` flags in daily operator workflows.
- **Contract Compatibility**: `tests/test_inventory.py` must be verified and updated if assertions assume `ai-p620-01` is in `production`.

---

## 5. Acceptance Criteria
1. `ansible-playbook -i inventory/production/hosts.yml --list-hosts production` outputs exactly `ai-5820-01`.
2. `make syntax` completes across all 17 playbooks with zero warnings.
3. `pytest tests/test_inventory.py` passes completely.
