# Local AI Configuration-as-Code Architecture

## 1. Principles and Core Operating Model

The repository implements strict configuration-as-code boundaries:
- **Git** is the authoritative desired state. Non-secret configuration, version pins, hardware profiles, and policies are version-controlled.
- **Ansible** orchestrates discovery, convergence, patching, lifecycle upgrades, and independent validation.
- **HashiCorp Vault** is the secret authority. No secrets or administrative tokens are committed to Git or stored in Ansible Vault.
- **Scheduled Runs** perform locked drift detection and convergence reconciliation using systemd timers.
- **Validation & Evidence** produce machine-readable JSON artifacts and human summaries without mutating state.

## 2. Infrastructure and Hardware Topology

The fleet is a two-node production group (`inventory/production/hosts.yml`), each node a dual-B65 inference host running the same enforced software stack:

**`ai-p620-01`** — Lenovo ThinkStation P620:
- **Model**: Lenovo ThinkStation P620 `30E1S7NJ00`
- **CPU**: AMD Ryzen Threadripper PRO 3945WX (12 cores / 24 threads)
- **Memory**: 48 GB ECC DDR4-3200 (expandable across 8 memory channels)
- **GPUs**: 2 × ASRock Intel Arc Pro B65 32 GB (Xe2 Battlemage architecture, 64 GB aggregate VRAM, PCIe Gen4 link negotiation)
- **Storage**: 1 TB NVMe SSD
- **PSU**: 1000 W Platinum internal power supply
- **Network**: 10 GbE onboard

**`ai-5820-01`** — Dell Precision 5820 Tower (`profiles/hardware/d5820_dual_b65.yml`):
- **CPU**: Intel Xeon W-2123 (4 cores / 8 threads)
- **Memory**: 32 GB ECC DDR4 today (8 DIMM slots; exact population captured at commissioning; Xeon W RDIMMs support up to 256 GB)
- **GPUs**: 2 × ASRock Intel Arc Pro B65 Creator 32 GB, PCIe Gen3 x16 link negotiation; host bridge reports Gen5 capability so link-speed warnings must be evaluated against the platform's real physical Gen3 topology
- **Storage**: 2 × NVMe M.2 (OS on #1, models/cache on #2 mounted via the `storage` role)
- **PSU**: 950 W internal (Dell 10-pin → dual 8-pin GPU harness required; each B65 draws via a single 12V-2×6 connector, 2×8-pin adapter included)
- **Network**: 1 GbE onboard

> **Aggregate VRAM caveat**: both nodes expose 64 GB aggregate VRAM as a *multi-device memory pool* (2 × 32 GB independent buffers). Tensor-parallel deployment (TP=2) spans a model across both GPUs; the pool is not a single transparent 64 GB device and per-device 32 GB limits govern model sizing.

Curated candidate models/quantizations with per-device TP sizing for this pool
are maintained in the [model catalog](model-catalog.md) (advisory; desired-state
pins live in the model registry role).

## 3. Inference Software Stack

Both nodes are converged to the same pinned stack:

- **OS**: Ubuntu 24.04 LTS (Noble Numbat)
- **Compute Driver**: Intel Compute Runtime + Level Zero loader/runtime (`libze-intel-gpu1`)
- **PyTorch**: PyTorch 2.12.1+xpu in pinned virtual environment
- **Primary Serving**: vLLM 0.7.3 with Intel XPU backend, OpenAI-compatible API, support for single-GPU (TP=1) and dual-GPU (TP=2)
- **Fallback Serving**: llama.cpp with SYCL acceleration, pinned to exact Git commit, supporting GGUF offload
- **Secret Management**: HashiCorp Vault AppRole integration, runtime secret retrieval
- **Runtime selection** is per-host: TP=2 is the primary serve path on both nodes; llama.cpp SYCL split is the fallback. `llama_cpp_sycl_dual_gpu_support_certified` remains `false` until dual-GPU SYCL split is proven on B65 (certification is a manual commissioning step).

## 4. Operational Boundaries and Future Integration

- **Clustering**: Standalone single-node initial topology designed with fleet-shaped inventory metadata for future Ray / distributed vLLM clusters.
- **CMDB Export**: Product-neutral Configuration Item (CI) export adhering to `schemas/cmdb.schema.json`.
- **ITSM Hooks**: Bounded change authorization envelope adhering to `schemas/itsm.schema.json`.
