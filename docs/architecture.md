# Local AI Configuration-as-Code Architecture

## 1. Principles and Core Operating Model

The repository implements strict configuration-as-code boundaries:
- **Git** is the authoritative desired state. Non-secret configuration, version pins, hardware profiles, and policies are version-controlled.
- **Ansible** orchestrates discovery, convergence, patching, lifecycle upgrades, and independent validation.
- **HashiCorp Vault** is the secret authority. No secrets or administrative tokens are committed to Git or stored in Ansible Vault.
- **Scheduled Runs** perform locked drift detection and convergence reconciliation using systemd timers.
- **Validation & Evidence** produce machine-readable JSON artifacts and human summaries without mutating state.

## 2. Infrastructure and Hardware Topology

- **Target Node**: Lenovo ThinkStation P620 (`ai-p620-01`), Model `30E1S7NJ00`
- **CPU**: AMD Ryzen Threadripper PRO 3945WX (12 cores / 24 threads)
- **Memory**: 48 GB ECC DDR4-3200 (expandable across 8 memory channels)
- **GPUs**: 2 × ASRock Intel Arc Pro B65 32 GB (Xe2 Battlemage architecture, 64 GB aggregate VRAM, PCIe Gen4 link negotiation)
- **Storage**: 1 TB NVMe SSD
- **PSU**: 1000 W Platinum internal power supply
- **Network**: 10 GbE onboard

## 3. Inference Software Stack

- **OS**: Ubuntu 24.04 LTS (Noble Numbat)
- **Compute Driver**: Intel Compute Runtime + Level Zero loader/runtime (`libze-intel-gpu1`)
- **PyTorch**: PyTorch 2.12.1+xpu in pinned virtual environment
- **Primary Serving**: vLLM 0.7.3 with Intel XPU backend, OpenAI-compatible API, support for single-GPU (TP=1) and dual-GPU (TP=2)
- **Fallback Serving**: llama.cpp with SYCL acceleration, pinned to exact Git commit, supporting GGUF offload
- **Secret Management**: HashiCorp Vault AppRole integration, runtime secret retrieval

## 4. Operational Boundaries and Future Integration

- **Clustering**: Standalone single-node initial topology designed with fleet-shaped inventory metadata for future Ray / distributed vLLM clusters.
- **CMDB Export**: Product-neutral Configuration Item (CI) export adhering to `schemas/cmdb.schema.json`.
- **ITSM Hooks**: Bounded change authorization envelope adhering to `schemas/itsm.schema.json`.
