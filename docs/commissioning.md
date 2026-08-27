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
    - **Gate notice**: the Intel Arc Pro B65 stack remains in `unresolved_vendor_support_conflict` (Ubuntu Server 24.04 without the Desktop/6.17-HWE closure). The role fails closed *before mutation*; this runbook cannot bypass it. Commissioning can proceed through the storage/baseline portions, but `gpu,runtime` completion requires Intel's coherent B65 host-support statement (see `docs/intel-gpu.md`).

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
