# Local AI Configuration-as-Code Architecture

## 1. Principles and Core Operating Model

The repository implements strict configuration-as-code boundaries:
- **Git** is the authoritative desired state. Non-secret configuration, version pins, hardware profiles, and policies are version-controlled.
- **Ansible** orchestrates discovery, convergence, patching, lifecycle upgrades, and independent validation.
- **HashiCorp Vault** is the secret authority. No secrets or administrative tokens are committed to Git or stored in Ansible Vault.
- **Scheduled Runs** perform locked drift detection and convergence reconciliation using systemd timers.
- **Validation & Evidence** produce machine-readable JSON artifacts and human summaries without mutating state.

## 2. Infrastructure and Hardware Topology

The v1.0.0 production deployment targets the **Dell Precision 5820 Tower** (`ai-5820-01`) as the primary qualified dual-B65 appliance. The Lenovo ThinkStation P620 (`ai-p620-01`) is maintained as an uncommissioned future profile in the `uncommissioned_hosts` inventory group.

**`ai-5820-01`** — Dell Precision 5820 Tower (`profiles/hardware/d5820_dual_b65.yml` — Active Production Appliance):
- **CPU**: Intel Xeon W-2123 (4 cores / 8 threads)
- **Memory**: 32 GB ECC DDR4 (8 DIMM slots; Xeon W RDIMMs support up to 256 GB)
- **GPUs**: 2 × ASRock Intel Arc Pro B65 Creator 32 GB (Xe2 Battlemage architecture, Level Zero backend), PCIe Gen3 x16 link negotiation on Intel C422 platform
- **Storage**: 2 × NVMe M.2 (OS on #1, models/cache on #2 mounted via linear LVM at `/var/lib/local-ai`)
- **PSU**: 950 W internal (Dell 10-pin → dual 8-pin GPU harness; each B65 draws via a single 12V-2×6 connector)
- **Network**: 1 GbE onboard (`10.0.8.5`)

**`ai-p620-01`** — Lenovo ThinkStation P620 (`profiles/hardware/p620_dual_b65.yml` — Uncommissioned Future Profile):
- **Model**: Lenovo ThinkStation P620 `30E1S7NJ00`
- **CPU**: AMD Ryzen Threadripper PRO 3945WX (12 cores / 24 threads)
- **Memory**: 48 GB ECC DDR4-3200 (expandable across 8 memory channels)
- **GPUs**: 2 × ASRock Intel Arc Pro B65 32 GB (Xe2 Battlemage architecture, 64 GB aggregate VRAM, PCIe Gen4 link negotiation)
- **Storage**: 1 TB NVMe SSD
- **PSU**: 1000 W Platinum internal power supply
- **Network**: 10 GbE onboard

> **Aggregate VRAM caveat**: Both nodes expose 64 GB aggregate VRAM as a *multi-device memory pool* (2 × 32 GB independent buffers). In our serving architecture, each GPU runs an independent model worker with dedicated VRAM, maximizing concurrent throughput without cross-device synchronization overhead. Default model sizing respects per-device 32 GB limits.

Curated candidate models/quantizations with per-device sizing for this pool
are maintained in the [model catalog](model-catalog.md) (advisory; desired-state
pins live in the model registry role).

## 3. Inference Software Stack

The production appliance is converged to a release-aware pinned serving stack:

- **OS Platforms**:
  - **Ubuntu 26.04 LTS (Resolute Raccoon)**: Production release with kernel >= 7.0 (used on `ai-5820-01`).
  - **Ubuntu 24.04 LTS (Noble Numbat)**: Baseline qualified release with kernel >= 6.17 HWE (target for `ai-p620-01`).
- **Compute Driver**:
  - On Ubuntu 26.04: Official upstream Intel OMIX 0.3.0 unified stack (`intel-omix=0.3.0-9~26.04`, `intel-omix-dev=0.3.0-9~26.04`) from `https://repositories.intel.com/gpu/ubuntu` suite `resolute/intel-omix/0.3.0` signed with key `E0258B57D9C442D5DB1855C271740E4DE392BFE3`.
  - On Ubuntu 24.04: Intel Compute Runtime + Level Zero loader/runtime (`libze-intel-gpu1`), fail-closed before mutation.
- **Primary Serving Architecture**:
  - Two independent containerized `llama.cpp` SYCL instances running via rootless Podman (Level Zero backend), pinned to Git commit `b11347-5fc4f3c8c`.
  - **Worker 1 (Lead Pool, GPU 0)**: `Qwen3.6-35B-A3B-UD-Q4_K_M` serving general reasoning and tool-calling on port 8000.
  - **Worker 2 (Deep Pool, GPU 1)**: `Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M` serving fast deep reasoning on port 8001.
- **Orchestration Gateway**:
  - Authenticated reverse proxy (`orchestrator_gateway`) running as a systemd service (`aihost-orchestrator-gateway.service`) on port 8443 with TLS encryption.
  - Features include: bearer token client authentication, per-pool routing, reasoning budget enforcement, circuit breakers, semantic caching, request queueing, and W3C distributed tracing (`traceparent`).
- **Serving Engine Selection**:
  - `vLLM` with Intel XPU backend was evaluated and retired on this platform; empirical qualification established that `llama.cpp` SYCL delivers over 4x higher throughput and significantly reduced memory overhead on the Intel Xe2 Battlemage architecture.
- **Secret Management**: HashiCorp Vault AppRole integration, runtime secret retrieval.

## 4. Operational Boundaries and Future Integration

- **Clustering**: Standalone single-node initial topology designed with fleet-shaped inventory metadata for future Ray / distributed vLLM clusters.
- **CMDB Export**: Product-neutral Configuration Item (CI) export adhering to `schemas/cmdb.schema.json`.
- **ITSM Hooks**: Bounded change authorization envelope adhering to `schemas/itsm.schema.json`.
- **Observability**: Continuous ingestion via the `observability` role (Grafana Alloy -> VictoriaMetrics + vmalert recording rules -> Grafana, logs -> Loki), hash-pinned and fail-closed until the commissioning checklist in `docs/observability.md` passes; telemetry feeds every evidence and benchmarking run.
