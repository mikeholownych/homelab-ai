# Authoritative Hardware Inventory: Dell Precision T5820 & Dual Intel Arc Pro B65

## 1. Executive Summary

An independent, direct interrogation of host `10.0.8.5` (`ai-5820-01`) was conducted to establish the definitive hardware configuration, memory capacity, accelerator topology, and active model serving footprint. 

This inventory establishes conclusively that the two physical Intel Arc Pro B65 GPUs each possess **32,656.00 MiB (31.89 GiB)** of physical VRAM and a maximum allocatable memory size of **31,023.20 MiB (30.296 GiB)**. The prior Phase 11 claim of a 16.0 GB (16,384 MB) limit was an implementation defect caused by an unverified default parameter.

---

## 2. Host System & Platform Identity

- **Host Name**: `ai-5820-01`
- **Chassis / Motherboard**: Dell Precision T5820 Workstation
- **Management IP**: `10.0.8.5` (reachable via batch SSH from development workstation)
- **Kernel Version**: Linux `7.0.0-34-generic` #34-Ubuntu SMP PREEMPT_DYNAMIC (x86_64)
- **Operating System**: Ubuntu 24.04 LTS (commissioned with Linux 7.0 dynamic kernel)
- **Host Physical Memory**: 64 GB physical DDR4 ECC registered (61.23 GiB usable)

---

## 3. Physical Accelerators & PCI Topology

Direct interrogation via `lspci` and Intel `xpu-smi discovery -d 0,1` established:

### GPU Device 0
- **Device Identifier**: Device ID 0, PCI BDF `0000:51:00.0`
- **Product Name**: `Intel(R) Arc(TM) Pro B65 Graphics` (Battlemage G31, SKU Type: Production ES)
- **PCI Device ID**: `0xe222` (Vendor: Intel Corporation `0x8086`)
- **SOC UUID**: `00000000-0000-0051-0000-0000e2228086`
- **DRM Node**: `/dev/dri/card1`
- **Compute Slices / EUs**: 5 slices, 20 sub-slices, 160 EUs, 1280 execution threads
- **Driver Version**: Level Zero runtime `17012470`
- **Physical Memory Capacity**: **32,656.00 MiB (31.8906 GiB / 34.24 GB decimal)**
- **Max Memory Allocatable**: **31,023.20 MiB (30.296 GiB / 32.53 GB decimal)**
- **Current Clock / Power**: 2400 MHz core clock, Tile 0 power 9W idle

### GPU Device 1
- **Device Identifier**: Device ID 1, PCI BDF `0000:93:00.0`
- **Product Name**: `Intel(R) Arc(TM) Pro B65 Graphics` (Battlemage G31, SKU Type: Production ES)
- **PCI Device ID**: `0xe222` (Vendor: Intel Corporation `0x8086`)
- **SOC UUID**: `00000000-0000-0093-0000-0000e2228086`
- **DRM Node**: `/dev/dri/card2`
- **Compute Slices / EUs**: 5 slices, 20 sub-slices, 160 EUs, 1280 execution threads
- **Driver Version**: Level Zero runtime `17012470`
- **Physical Memory Capacity**: **32,656.00 MiB (31.8906 GiB / 34.24 GB decimal)**
- **Max Memory Allocatable**: **31,023.20 MiB (30.296 GiB / 32.53 GB decimal)**
- **Current Clock / Power**: 2400 MHz core clock, Tile 0 power 1W idle

---

## 4. Active Serving Topology & Memory Allocations

Telemetry collected via `xpu-smi stats -d 0,1` and system process auditing:

| Component | Target Device | Process / Container | Local Port | Allocated VRAM | VRAM Util % | Served Model |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Worker 1** | GPU 0 (`51:00.0`) | `vllm-xpu-tp1-worker1` (Podman) | `8000` | 27,869 MiB (27.21 GiB) | 85% | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` |
| **Worker 2** | GPU 1 (`93:00.0`) | `vllm-xpu-tp1-worker2` (Podman) | `8001` | 27,861 MiB (27.20 GiB) | 85% | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` |
| **Gateway**  | Host network | `orchestrator_gateway` (PID 742882) | `8010` | N/A (CPU/routing) | N/A | Exposes `engineering/b0` load-balanced |
| **SSH Tunnel**| Client workstation | SSH forwarder (PID 2093382) | `18010` | N/A (TCP tunnel) | N/A | Forwards `127.0.0.1:18010` $\to$ `10.0.8.5:8010` |

### Key Architectural Discovery
Notice that each vLLM worker allocates **27.86 GiB** of memory on its assigned GPU. 
If the GPUs had only possessed 16.0 GB as claimed in the initial Phase 11 report, the active serving configuration would have suffered immediate Out-Of-Memory allocation failures on worker startup! The fact that the dual workers run stably with 27.86 GiB resident memory provides empirical confirmation of the 31.89 GiB hardware capacity.

---

## 5. Binary vs. Decimal Memory Accounting

To ensure rigorous precision across engineering evaluations:
- **Binary Capacity (GiB)**:
  $$32,656.00 \text{ MiB} = \frac{32,656}{1,024} = 31.890625 \text{ GiB}$$
- **Max Allocatable (GiB)**:
  $$31,023.20 \text{ MiB} = \frac{31,023.20}{1,024} = 30.29609375 \text{ GiB}$$
- **Decimal Capacity (GB)**:
  $$32,656 \times 1,024 \times 1,024 = 34,242,560,000 \text{ bytes} \approx 34.24 \text{ GB}$$

All future hardware evaluations must standardize on binary megabytes (`MiB`) and gibibytes (`GiB`) for internal memory math to prevent rounding discrepancies.
