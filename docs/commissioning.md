# Hardware Commissioning Runbooks

Two production nodes share the same software stack but are physically distinct.
The sections below are the authoritative acceptance sequences for each host.

## Lenovo ThinkStation P620 (`ai-p620-01`) — Dual Arc Pro B65

## Acceptance Sequence

When the physical Lenovo ThinkStation P620 workstation arrives, follow this authoritative 18-step commissioning runbook to achieve accepted baseline state:

1. **Capture Factory State**
   - Record factory serial numbers, asset tags, carton seals, and initial hardware inventory before booting.

2. **Verify Model/Serial/PSU**
   - Confirm machine model `30E1S7NJ00`, AMD Threadripper PRO 3945WX CPU, and 1000 W PSU rating.

3. **Verify Memory/Storage**
   - Verify initial 48 GB ECC RAM across channels and 1 TB NVMe storage device.

4. **Update Approved Firmware If Required**
   - Flash vetted Lenovo system BIOS and device firmware if required by security or hardware policy.

5. **Verify BIOS Prerequisites**
   - Ensure Above 4G Decoding is **Enabled**.
   - Ensure Resizable BAR (ReBAR) is **Enabled**.
   - Ensure IOMMU / AMD-Vi is **Enabled**.
   - Ensure PCIe configuration matches Gen4 link negotiation.

6. **Install/Configure First B65**
   - Seat the primary ASRock Intel Arc Pro B65 32 GB card in PCIe Slot 1 (x16 physical and electrical).

7. **Validate First GPU**
   - Run `ansible-playbook playbooks/validate.yml --limit ai-p620-01` to verify device enumeration, Gen4 link, 32 GB VRAM, and Level Zero visibility.

8. **Install/Configure Second B65**
   - Seat the secondary ASRock Intel Arc Pro B65 32 GB card in PCIe Slot 3 (x16 physical).

9. **Validate Both GPUs**
   - Execute discovery to verify both B65 GPUs enumerate with aggregate 64 GB VRAM and verified PCIe slot topology:
     ```bash
     ansible-playbook playbooks/validate.yml --limit ai-p620-01
     ```

10. **Deploy XPU Stack**
    - Apply Intel GPU compute driver and PyTorch XPU environment:
      ```bash
      ansible-playbook playbooks/site.yml --limit ai-p620-01 --tags gpu,runtime
      ```

11. **Deploy Inference Runtime**
    - Deploy vLLM XPU and llama.cpp SYCL services:
      ```bash
      ansible-playbook playbooks/site.yml --limit ai-p620-01 --tags inference
      ```

12. **Run Single-GPU Test**
    - Run single-GPU inference benchmark profile:
      ```bash
      ansible-playbook playbooks/benchmark.yml --limit ai-p620-01 -e "benchmark_profile=small"
      ```

13. **Run Dual-GPU Test**
    - Run dual-GPU tensor-parallel inference benchmark profile:
      ```bash
      ansible-playbook playbooks/benchmark.yml --limit ai-p620-01 -e "benchmark_profile=large_70b"
      ```

14. **Run Sustained Load Test**
    - Execute the sustained load and thermal stability benchmark:
      ```bash
      ansible-playbook playbooks/benchmark.yml --limit ai-p620-01 -e "benchmark_profile=sustained_load"
      ```

15. **Reboot**
    - Perform controlled system reboot to verify automatic service initialization:
      ```bash
      sudo reboot
      ```

16. **Rerun Convergence**
    - Execute authoritative site convergence:
      ```bash
      ansible-playbook playbooks/site.yml --limit ai-p620-01
      ```

17. **Verify Idempotency**
    - Re-run site convergence and drift check to ensure `changed=0`:
      ```bash
      ansible-playbook playbooks/drift-check.yml --limit ai-p620-01 --check
      ```

18. **Capture Accepted Baseline**
    - Archive the generated evidence directory under `evidence/ai-p620-01/<timestamp>/` as the authoritative commissioning baseline evidence.

---

## Dell Precision 5820 Tower (`ai-5820-01`) — Dual Arc Pro B65

Profile: `profiles/hardware/d5820_dual_b65.yml`. When the physical Precision 5820 arrives, follow this 19-step runbook:

1. **Capture Factory State**
   - Record serial numbers, asset tag, shipping seals, and initial inventory before booting.

2. **Verify Model/CPU/PSU**
   - Confirm Dell Precision 5820 Tower, Intel Xeon W-2123, and a 950 W internal PSU rating (verify physical sticker).

3. **Verify Memory/Storage**
   - Verify 32 GB ECC DDR4 (8 DIMM slots — record which positions are populated); confirm both NVMe M.2 devices present. **Capture and record both NVMe UUIDs** (`lsblk -f`, `blkid`); they are required before enabling `storage_mounts` in `inventory/production/host_vars/ai-5820-01.yml` (kept commented until then).

4. **Update Approved Firmware If Required**
   - Flash vetted Dell system BIOS and device firmware per security/hardware policy.

5. **Verify BIOS Prerequisites**
   - Enable **Above 4G Decoding** and **Resizable BAR (ReBAR)**. These states are reported from Linux sysfs when visible; until then the profile records `undiscoverable_status: not_tested`. Enable **Intel VT-d/IOMMU**.

6. **Verify GPU Power Harness**
   - The Dell 10-pin motherboard power header → dual 8-pin PCIe GPU harness is mandatory for two B65 cards. Each B65 draws via a single 12V-2×6 connector (2×8-pin adapter included); verify the harness/PSU delivers sustained dual-GPU load before ever powering both cards (PSU budget gates: `benchmarking_psu_capacity_watts: 950`, `benchmarking_gpu_tdp_watts: 200`).

7. **Remove Interim GPU**
   - If the machine carries an interim NVIDIA P4000 (or any non-approved GPU), remove it before acceptance. An unexpected device surfaces as a **warning** (`unexpected_gpu_devices`) — never blocking an approved dual-B65 result — but it must be gone for the accepted baseline.

8. **Install/Configure First B65**
   - Seat the primary ASRock Intel Arc Pro B65 Creator 32 GB card in a physical x16 slot (expect Gen3 x16 negotiation; `expected_negotiated_generation: 3`, `allow_slot_limited_width: true`).

9. **Validate First GPU**
   - Run `ansible-playbook playbooks/validate.yml --limit ai-5820-01` to verify device enumeration, Gen3 x16 link, 32 GB VRAM, and Level Zero visibility.

10. **Install/Configure Second B65**
    - Seat the secondary B65 in the second physical x16 slot.

11. **Validate Both GPUs**
    - Re-run discovery; expect both B65 GPUs, 64 GB **aggregate** VRAM (per-device 32 GB), and verified PCIe slot topology:
      ```bash
      ansible-playbook playbooks/validate.yml --limit ai-5820-01
      ```

12. **Deploy XPU Stack**
    - Apply Intel GPU compute driver and PyTorch XPU environment:
      ```bash
      ansible-playbook playbooks/site.yml --limit ai-5820-01 --tags gpu,runtime
      ```
    - **Gate notice**: the Intel Arc Pro B65 stack is researched and documented (state `pre_verification_fail_closed`; see `docs/intel-gpu.md`). Installation is blocked until the in-place verifiable checklist passes: Ubuntu 24.04.4+ `base-files`, kernel >= 6.17 HWE (`linux-generic-hwe-24.04`), both `8086:e222` devices correlated by PCI BDF, and a non-simulated BDF-correlated classification PASS. The role fails closed *before mutation*; this runbook cannot bypass it. Commissioning can proceed through the storage/baseline portions, but `gpu,runtime` completion requires the checklist to pass in place.

13. **Deploy Inference Runtime**
    - Deploy vLLM XPU and llama.cpp SYCL services:
      ```bash
      ansible-playbook playbooks/site.yml --limit ai-5820-01 --tags inference
      ```

14. **Run Single-GPU Test**
    - ```bash
      ansible-playbook playbooks/benchmark.yml --limit ai-5820-01 -e "benchmark_profile=small"
      ```

15. **Run Dual-GPU Test**
    - TP=2 profile; recall per-device 32 GB / aggregate-pool semantics when sizing:
      ```bash
      ansible-playbook playbooks/benchmark.yml --limit ai-5820-01 -e "benchmark_profile=large_70b"
      ```

16. **Run Sustained Load / Thermal Test**
    - The thermal gate reads **both** GPU devices (per-device peak temp; hwmon sampling covers each card):
      ```bash
      ansible-playbook playbooks/benchmark.yml --limit ai-5820-01 -e "benchmark_profile=sustained_load"
      ```

17. **Reboot**
    - `sudo reboot`; verify automatic service initialization.

18. **Rerun Convergence + Idempotency**
    - ```bash
      ansible-playbook playbooks/site.yml --limit ai-5820-01
      ansible-playbook playbooks/drift-check.yml --limit ai-5820-01 --check
      ```
    - Re-run must be byte-stable (`changed=0`).

19. **Capture Accepted Baseline**
    - Archive `evidence/ai-5820-01/<timestamp>/` as the authoritative commissioning baseline evidence.

**Aggregate VRAM caveat**: 64 GB is a multi-device memory pool (2 × 32 GB device-local memory spaces), not a single transparent 64 GB device. TP=2 spans a model across both GPUs; whether a single request can address memory on both devices depends on the runtime's model-parallel implementation, so sizing defaults to per-device 32 GB.

---

## Phase-Gated Host Commissioning (`playbooks/commission.yml`)

The primary entrypoint for complete host commissioning is `playbooks/commission.yml`. It targets `ai_hosts`, enforces `any_errors_fatal: true`, and progresses through eight ordered phases with structured evidence checkpoints persisted under `/var/lib/local-ai/evidence/checkpoints/`.

Because the playbook targets `ai_hosts`, the `--limit` flag is mandatory in production:
```bash
--limit ai-5820-01
```

### Commissioning Principles

1. **Evidence-Based Acceptance**:
   Ubuntu Server acceptance is evidence-based and linear LVM is not redundant. Official Intel OMIX documentation qualifies Ubuntu Desktop 24.04.4 while Ubuntu Server 26.04 operates under qualification caveats; acceptance requires recorded, schema-valid evidence at every stage rather than assumption.
2. **Storage Architecture**:
   The linear LVM configuration concatenates physical partitions (`/dev/nvme0n1p3` and `/dev/nvme1n1p1`) into a single 550 GiB continuous filesystem mounted by UUID at `/var/lib/local-ai`. Linear LVM is not redundant: it maximizes space for model weights and caches without RAID overhead, while disaster recovery is handled via configuration management and model re-download.
3. **Controlled Operator Checkpoints**:
   Reboots are never performed automatically within `playbooks/commission.yml`. If the OMIX driver installation flags a pending reboot (`/var/run/reboot-required`), the `omix` phase records `reboot_required: true` and halts. The operator executes `playbooks/reboot-verify.yml` before proceeding.

### Ordered Phase Commands

Execute the commissioning runbook through the following sequence:

#### 1. Dry Preflight
Assert platform compatibility, kernel version, NVMe PV topology, and target GPU BDFs without mutating host state:
```bash
ansible-playbook -i inventory/production/hosts.yml playbooks/commission.yml --limit ai-5820-01 --tags preflight --diff
```

#### 2. Bootstrap Phase
Install minimal Python prerequisites, configure initial access, and verify raw platform identity:
```bash
ansible-playbook -i inventory/production/hosts.yml playbooks/commission.yml --limit ai-5820-01 --tags bootstrap
```

#### 3. Baseline Idempotency Phase
Apply base OS hardening, time sync, users, SSH configuration, and verify convergence:
```bash
ansible-playbook -i inventory/production/hosts.yml playbooks/commission.yml --limit ai-5820-01 --tags baseline_idempotency
```

#### 4. Storage Management Phase
Verify NVMe physical volume prerequisites, allocate the 550 GiB logical volume on `ubuntu-vg`, format with XFS, and mount by UUID:
```bash
ansible-playbook -i inventory/production/hosts.yml playbooks/commission.yml --limit ai-5820-01 --tags storage
```

#### 5. Pinned OMIX Stack Phase
Install the pinned Intel OMIX repository keyring, deb822 sources, and exact user-space packages:
```bash
ansible-playbook -i inventory/production/hosts.yml playbooks/commission.yml --limit ai-5820-01 --tags omix
```

#### Operator Checkpoint: Reboot Verification (if required)
If OMIX installation requires a kernel driver reload or system reboot:
```bash
ansible-playbook -i inventory/production/hosts.yml playbooks/reboot-verify.yml --limit ai-5820-01
```

#### 6. GPU Validation Phase
Run hardware inventory collection and strict classification. Requires bijective correlation across both BDFs, both DRM cards, both render nodes, and distinct Level Zero UUIDs:
```bash
ansible-playbook -i inventory/production/hosts.yml playbooks/commission.yml --limit ai-5820-01 --tags gpu_validation
```

#### 7. PyTorch XPU Validation Phase
Run isolated per-device probes on `xpu:0` and `xpu:1`, followed by dual-visible verification (`torch.xpu.device_count() == 2`), before promoting the virtual environment:
```bash
ansible-playbook -i inventory/production/hosts.yml playbooks/commission.yml --limit ai-5820-01 --tags pytorch_xpu
```

#### 8. Inference Runtime Qualification Phase
Validate and enable inference profiles (vLLM XPU tensor-parallel and llama.cpp SYCL) according to host capabilities:
```bash
ansible-playbook -i inventory/production/hosts.yml playbooks/commission.yml --limit ai-5820-01 --tags inference
```

#### Complete Rerun Command
Once all checkpoints pass, full idempotent convergence may be executed end-to-end:
```bash
ansible-playbook -i inventory/production/hosts.yml playbooks/commission.yml --limit ai-5820-01
```

