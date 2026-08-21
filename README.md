# Local AI Workstation Configuration-as-Code

Production-quality Configuration-as-Code (CaC) repository using Ansible for managing a local AI workstation fleet, initially targeting a Lenovo ThinkStation P620 with dual Intel Arc Pro B65 32 GB GPUs running Ubuntu 24.04 LTS.

---

## 1. Prerequisites

- Operator machine with Python 3.12+ and `venv`
- Target host network connectivity via SSH
- HashiCorp Vault server accessible via HTTPS
- Valid Vault AppRole credentials (or machine secret provisioned out-of-band)
- Base Python packages and Ansible collections installed:
  ```bash
  python3 -m venv .venv
  .venv/bin/pip install --require-hashes -r requirements.txt
  .venv/bin/ansible-galaxy collection install -r requirements.yml
  ```

---

## 2. Supported Host Profile

The initial primary target host is the Lenovo ThinkStation P620 configured as:
- **Model**: Lenovo ThinkStation P620 `30E1S7NJ00`
- **CPU**: AMD Ryzen Threadripper PRO 3945WX (12C / 24T)
- **RAM**: 48 GB ECC DDR4-3200
- **Storage**: 1 TB NVMe SSD
- **PSU**: 1000 W internal power supply
- **Network**: 10 GbE onboard NIC
- **GPUs**: 2 × ASRock Intel Arc Pro B65 (32 GB VRAM each, 64 GB aggregate VRAM, PCIe Gen4 link negotiation on P620 WRX80 platform)
- **Hardware Profile**: `profiles/hardware/p620_dual_b65.yml`

---

## 3. Initial Ubuntu Install Assumptions

- Base OS: **Ubuntu 24.04 LTS (Server or Minimal Desktop)**
- Standard partition layout with ext4/XFS on root NVMe
- Initial administrative user with `sudo` permissions
- Basic network connectivity and SSH server active
- BIOS settings configured:
  - Above 4G Decoding: **Enabled**
  - Resizable BAR (ReBAR): **Enabled**
  - IOMMU (AMD-Vi): **Enabled**

---

## 4. How to Configure Inventory

Inventory files reside under `inventory/production/` and `inventory/lab/`:
- `inventory/production/hosts.yml`: Node list and cluster group hierarchy.
- `inventory/production/group_vars/`:
  - `all.yml`: Environment-wide baseline policies and directories.
  - `inference.yml`: Inference model selection and secret paths.
  - `gpu.yml`: GPU driver and runtime configuration.
  - `cluster.yml`: Fleet clustering metadata.
  - `monitoring.yml`: Telemetry and logging configuration.
- `inventory/production/host_vars/ai-p620-01.yml`: Host-specific overrides (e.g. `ansible_host`).

---

## 5. How to Authenticate to HashiCorp Vault

HashiCorp Vault is the sole authority for secrets. Plaintext secrets and Ansible Vault are not used.

1. Provision AppRole RoleID and SecretID to `/etc/vault/role-id` and `/etc/vault/secret-id` on the target host (permissions `0600` root-owned).
2. During playbook execution, `roles/vault_integration` authenticates via AppRole to obtain a short-lived token.
3. Vault path structure:
   - `secret/local-ai/shared/`: Shared fleet secrets
   - `secret/local-ai/hosts/<hostname>/`: Host-specific secrets
   - `secret/local-ai/services/`: Service API keys and certificates

See `docs/vault.md` for full credential lifecycle instructions.

---

## 6. How to Bootstrap the Host

To perform initial bootstrapping from clean Ubuntu 24.04 install:
```bash
ansible-playbook playbooks/bootstrap.yml --limit ai-p620-01 --ask-become-pass --tags bootstrap,vault
```
This installs core Python packages, operator SSH public keys, sudo rules, and sets up Vault preflight checks.

---

## 7. How to Run Full Convergence

Execute the authoritative site playbook to converge the host to the complete desired state:
```bash
ansible-playbook playbooks/site.yml --limit ai-p620-01
```

---

## 8. How Scheduled Reconciliation Works

- Native systemd service and timer units (`aihost-reconcile.service` / `aihost-reconcile.timer`) run periodically.
- Scheduled runs invoke `scripts/run-ansible-snapshot site.yml` from a deployed snapshot.
- Execution uses `flock` to guarantee single-instance execution.
- No `git pull` or network mutations occur during unattended reconciliation.
- Logs are preserved under `/var/log/local-ai/reconciliation/`.

---

## 9. How Patching Works

- Routine patches are separated from high-risk GPU/runtime components.
- Run patch assessment (dry run):
  ```bash
  ansible-playbook playbooks/patch.yml --limit ai-p620-01
  ```
- Apply routine patches and reboot if required:
  ```bash
  ansible-playbook playbooks/patch.yml --limit ai-p620-01 -e "patch_apply=true"
  ```
- See `docs/patching.md` for complete patching policy details.

---

## 10. How Upgrades Work

- High-risk components (vLLM, PyTorch XPU, Level Zero, Intel driver, Kernel) use explicit Git version pins.
- Tracked lifecycle versions: `current`, `candidate`, and `previous_known_good`.
- Execute candidate upgrade:
  ```bash
  ansible-playbook playbooks/upgrade.yml --limit ai-p620-01 -e "upgrade_component=vllm upgrade_version=0.7.3"
  ```
- See `docs/upgrades.md`.

---

## 11. How Validation Works

Independent validation probes execute read-only checks across hardware, drivers, runtimes, and services:
```bash
ansible-playbook playbooks/validate.yml --limit ai-p620-01
```
Results are aggregated into `validation.json` validating against `schemas/validation.schema.json`.

---

## 12. How Benchmarks Work

Run reproducible performance benchmarks across 5 predefined profiles:
```bash
ansible-playbook playbooks/benchmark.yml --limit ai-p620-01 -e "benchmark_profile=small"
ansible-playbook playbooks/benchmark.yml --limit ai-p620-01 -e "benchmark_profile=large_70b"
```
Profiles include: `small`, `medium_32b`, `large_70b`, `low_precision_moe`, and `sustained_load`.

---

## 13. How to Interpret Evidence

Every major lifecycle run writes an evidence bundle under `evidence/<hostname>/<timestamp>/` (or `/var/lib/aihost/evidence/` on target):
- `manifest.json`: Run metadata, Git SHA, and recap counts
- `hardware.json` & `pci.json`: Discovered topology and link status
- `validation.json`: Independent validation results
- `benchmark.json`: Performance and telemetry data
- `SHA256SUMS`: Cryptographic checksums of all run artifacts

---

## 14. How to Add Future Hosts

1. Add node definition in `inventory/production/hosts.yml`.
2. Create host variables file in `inventory/production/host_vars/<hostname>.yml`.
3. Assign applicable hardware profile in `profiles/hardware/`.
4. Provision SSH keys and Vault AppRole credentials.
5. Execute bootstrap and site convergence.

---

## 15. How Clustering is Enabled

- Future multi-node clustering (Ray / distributed vLLM) is configured via inventory variables:
  ```yaml
  features:
    clustering: true
  cluster:
    name: "ai-cluster-01"
    enabled: true
  ```
- See `docs/clustering.md`.

---

## 16. Future CMDB Integration Boundary

- `playbooks/facts-export.yml` and `roles/cmdb_export` emit standardized Configuration Item JSON conforming to `schemas/cmdb.schema.json`.
- Neutral export adapter supports integration with ServiceNow, Jira Assets, Device42, or NetBox.
- See `docs/cmdb.md`.

---

## 17. Future ITSM Integration Boundary

- `roles/itsm_hooks` validates change tickets conforming to `schemas/itsm.schema.json`.
- Strict type-safe authorization checks ensure execution only within approved maintenance windows for permitted actions.
- No free-form ticket text is executed.
- See `docs/itsm.md`.

---

## 18. Rollback Procedure

To roll back a component following a failed upgrade or regression:
```bash
ansible-playbook playbooks/upgrade.yml --limit ai-p620-01 -e "upgrade_component=vllm upgrade_mode=rollback"
```
Or revert the Git commit and re-converge:
```bash
git revert <commit-sha>
ansible-playbook playbooks/site.yml --limit ai-p620-01
```
See `docs/rollback.md` for full rollback runbook.
