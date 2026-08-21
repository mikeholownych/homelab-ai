# Hardware Commissioning Runbook: Lenovo ThinkStation P620 Dual Arc Pro B65

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
