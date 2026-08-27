# Local AI Workstation Configuration-as-Code

Production-quality Configuration-as-Code (CaC) repository using Ansible for managing a local AI workstation fleet, targeting a Lenovo ThinkStation P620 and a Dell Precision 5820 Tower with dual Intel Arc Pro B65 32 GB GPUs running Ubuntu 24.04 LTS.

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

The fleet consists of two production nodes, both running the dual-B65 inference stack:

**Lenovo ThinkStation P620** (`ai-p620-01`):
- **Model**: Lenovo ThinkStation P620 `30E1S7NJ00`
- **CPU**: AMD Ryzen Threadripper PRO 3945WX (12C / 24T)
- **RAM**: 48 GB ECC DDR4-3200
- **Storage**: 1 TB NVMe SSD
- **PSU**: 1000 W internal power supply
- **Network**: 10 GbE onboard NIC
- **GPUs**: 2 × ASRock Intel Arc Pro B65 (32 GB VRAM each, 64 GB aggregate VRAM, PCIe Gen4 link negotiation on P620 WRX80 platform)
- **Hardware Profile**: `profiles/hardware/p620_dual_b65.yml`

**Dell Precision 5820 Tower** (`ai-5820-01`):
- **Model**: Dell Precision 5820 Tower
- **CPU**: Intel Xeon W-2123 (4C / 8T)
- **RAM**: 32 GB ECC DDR4 (8 DIMM slots; Xeon W RDIMMs support up to 256 GB; exact DIMM population recorded at commissioning)
- **Storage**: 2 × NVMe M.2 (OS on #1, models/cache on #2 via `storage` role) — `storage_mounts` scaffolded commented until identity capture
- **PSU**: 950 W internal (Dell 10-pin → dual 8-pin GPU harness required; each B65 draws via a single 12V-2×6 connector, 2×8-pin adapter included)
- **Network**: 1 GbE onboard
- **GPUs**: 2 × ASRock Intel Arc Pro B65 Creator (32 GB VRAM each), PCIe Gen3 x16 link negotiation on the Intel C422 (LGA2066) Dell Precision 5820 platform
- **Hardware Profile**: `profiles/hardware/d5820_dual_b65.yml`

> **Aggregate VRAM caveat**: 64 GB is a *multi-device memory pool* (two independent 32 GB device-local memory spaces), not a single transparent 64 GB device. Whether a single inference request or model execution can address memory on both devices depends on the runtime's model-parallel implementation; TP=2 exists precisely to span a single model across both GPUs. Default model sizing respects per-device 32 GB limits.

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

**Credential placement depends on the execution model:**

- **Initial operator workflow (remote controller):** `roles/vault_integration` reads AppRole credentials on the *Ansible controller* from protected local paths (see `docs/vault.md`); lookups are delegated to localhost and never logged.
- **Scheduled self-runs (post-commissioning):** the deployed snapshot executes on the host itself, and credentials are provisioned at `/etc/vault/role-id` and `/etc/vault/secret-id` (`0600`, root-owned), ideally delivered via systemd `LoadCredential=`.

1. Provision AppRole credentials to whichever location matches your execution model.
2. During playbook execution, `roles/vault_integration` authenticates via AppRole to obtain a short-lived token.
3. Vault path structure:
   - `secret/local-ai/shared/`: Shared fleet secrets
   - `secret/local-ai/hosts/<hostname>/`: Host-specific secrets
   - `secret/local-ai/services/`: Service API keys and certificates

**Secret-at-rest note:** service API keys retrieved at convergence are rendered into root-readable runtime env files (`0600`). This means Vault is not the only live copy between reconciliations; revocation takes effect at next convergence or service restart. Moving key delivery fully to systemd credentials refreshed at unit start is the planned refinement.

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

## 14. How to Add Further Hosts

The current two-node fleet (`ai-p620-01`, `ai-5820-01`) was onboarded via this exact workflow; repeat it for any future host:
1. Add node definition in `inventory/production/hosts.yml`.
2. Create host variables file in `inventory/production/host_vars/<hostname>.yml`.
3. Assign an applicable hardware profile in `profiles/hardware/`, or create one matching the new platform.
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

---

## 19. OS Tuning Framework

OS tuning is evidence-driven and versioned. The authoritative profile is
`os_tuning_profile: baseline`, which manages nothing until benchmark evidence
justifies a change:

- Profiles live in `profiles/tuning/` and validate against
  `schemas/os-tuning.schema.json`.
- Workflow: baseline -> benchmark -> one controlled candidate -> benchmark ->
  compare -> retain or reject (`docs/tuning.md`).
- Promotion criteria and thresholds: `policies/tuning.yml`.
- NUMA, PCIe, IRQ, CPU-power, memory, hugepages, I/O, and kernel telemetry are
  collected into every evidence run (`numa.json`, `cpu-power.json`,
  `interrupts.json`, `memory-policy.json`, `hugepages.json`, `io.json`,
  `kernel.json`, `tuning-profile.json`).
- Custom kernels remain disabled scaffolding (`kernel/`, `docs/custom-kernel.md`);
  supported Ubuntu kernels are always tried first.
