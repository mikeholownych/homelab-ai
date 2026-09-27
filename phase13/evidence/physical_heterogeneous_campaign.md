# Physical Heterogeneous Campaign & Execution Boundaries Report

## 1. Executive Summary & Governance Determination

In accordance with Phase 13 Workstream G, Section 11, and Gate G9, this report documents the physical status, execution boundaries, and empirical data regarding heterogeneous multi-worker inference on the Dell Precision T5820 (`10.0.8.5`).

### Authoritative Governance Determination:
1. **Separation of Authorizations**: The maintenance authorization granted in Phase 12 (`MAINT-PROP-CAND-QWEN2.5-7B-AWQ-GPU1`) was strictly bounded to that qualification run and was followed by a complete deterministic rollback restoring both workers to `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`.
2. **Boundary Enforcement**: In strict compliance with Section 2 and Section 11, **authorization for another physical model replacement is NOT inferred**.
3. **No Unapproved Modifications**: Maintenance proposal [`MAINT-PROP-PHASE13-HETERO-GPU1`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/proposals/maint_prop_phase13_hetero_gpu1.md) has been prepared and placed in `STOPPED_PENDING_EXPLICIT_HUMAN_AUTHORIZATION` status.
4. **No Simulation Substitution**: In strict accordance with Section 16, simulation is **never substituted** for physical qualification.
5. **Gate Disposition**: Because physical candidate replacement on Worker 2 cannot proceed without explicit administrative authorization, **Gate G9 and Gate G10 are recorded as BLOCKED**.

---

## 2. Pinned Candidate Identity & Cryptographic Verification

The candidate specialist model discovered on host disk remains pinned and cryptographically verified:
- **Model Name**: `Qwen/Qwen2.5-7B-Instruct-AWQ`
- **Pinned Revision**: `b25037543e9394b818fdfca67ab2a00ecc7dd641`
- **Host Location**: `/var/lib/local-ai/models/hub/models--Qwen--Qwen2.5-7B-Instruct-AWQ/snapshots/b25037543e9394b818fdfca67ab2a00ecc7dd641`
- **Weight Footprint**: 5.19 GiB (5,314 MiB)
- **Architecture**: Qwen2 dense transformer (7.61B parameters)
- **Quantization**: AWQ 4-bit (GEMM)
- **Max Context**: 32,768 tokens

---

## 3. Physical Benchmark Telemetry (Retained from Authorized Window)

During the authorized Phase 12 continuation window, simultaneous heterogeneous inference was benchmarked directly on the hardware:
- **Worker 1 (GPU 0, 30B MoE)**: 34.741s elapsed, 14.74 tps.
- **Worker 2 (GPU 1, 7B Dense)**: 19.122s elapsed, 26.78 tps.
- **Simultaneous Pipeline Elapsed**: **34.741 seconds** (vs 53.863s serial sum, a **35.5% wall-clock latency reduction**).
- **Cross-Device Interconnect Contention**: Zero PCIe bus contention observed between independent root complex ports (`0000:4e:00.0` and `0000:90:00.0`).
- **Thermal Behavior**: Both GPUs operated $\le 62^\circ\text{C}$ with zero power throttling.

---

## 4. Current Cluster Operating State

The Dell Precision T5820 inference cluster remains in its protected, dual-resident baseline:
- `vllm-xpu-tp1-worker1` (GPU 0, port 8000): serving `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`.
- `vllm-xpu-tp1-worker2` (GPU 1, port 8001): serving `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`.
- `orchestrator_gateway` (port 8010): serving `engineering/b0` via round-robin.

No physical replacement will occur until the human operator reviews and authorizes proposal `MAINT-PROP-PHASE13-HETERO-GPU1`.
