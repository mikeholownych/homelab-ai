# Phase 14 Experiment 02: Concurrent Workload Forensic Authority and Scope

- **Date:** 2026-09-29
- **Forensic Investigation ID:** `PHASE_14_EXP02_FORENSIC_RECONCILIATION`
- **Canonical Repository:** `mikeholownych/homelab-ai`
- **Canonical Remote Target:** `origin/main` (`a8c3b6a1a4c27f391f28ebdf5a74c1bfd1d148ce`)
- **Investigation Scope:** Dell Precision T5820 (`10.0.8.5`) and local host (`10.0.8.95`) activity during Phase 14 Experiment 02 campaign window (`2026-09-29T05:48:38Z` to `2026-09-29T06:48:39Z`).

---

## 1. Operator Notification and Mission Mandate

New operator intelligence established that an autonomous agent operating on the OpenCode workstream was actively dispatching inference requests to the dual Intel Arc A770 physical inference acceleration infrastructure on the Dell Precision T5820 (`10.0.8.5`) during the Phase 14 Experiment 02 sustained queue qualification campaign.

This concurrent workload was not declared in the original experimental design protocol and constitutes an unmodeled potential confounder for:
1. Observed queue wait dynamics.
2. Tail end-to-end latencies.
3. Queue backlog stability assertions.
4. Throughput attribution between Configuration B and Configuration B+.

The operator authorized a bounded forensic investigation to:
1. Reconstruct all OpenCode inference requests, routing paths, tokens, and timestamps.
2. Reconcile cross-host timestamps and build an authoritative unified campaign timeline.
3. Determine the physical resource contention mechanism between OpenCode and experimental workloads.
4. Recalculate Configuration B vs. Configuration B+ metrics and reassess queue stability claims.
5. Preserve independently established architectural, safety, and acceptance findings.
6. Evaluate rerun feasibility under verified non-interference conditions.

---

## 2. Invariant Operational Boundaries

The investigation strictly enforced the following non-negotiable system boundaries:

| Boundary | Invariant Status | Verification Mechanism |
|---|---|---|
| **Production Mode** | `SchedulingMode.CONFIGURATION_B` | Explicitly preserved; zero unauthorized promotion of B+ |
| **Model Inventory** | Homogeneous dual-30B MoE | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` on GPU 0 and GPU 1 |
| **Gateway Service** | `aihost-orchestrator-gateway.service` | Running on PID 3542340 (port 8010), token authentication intact |
| **Hermes Gateway** | Local PID 986 | Undisturbed, active on `127.0.0.1:8000` |
| **SSH Tunnels** | PIDs 1269920 (`18000`), 2093382 (`18010`) | Actively preserved without termination or interruption |
| **Evidence Immutability** | Original Experiment 02 evidence preserved | Original 32 evidence artifacts remain unmodified |
| **Active Workstreams** | Zero process disruption | No termination of concurrent OpenCode or Hermes processes |

---

## 3. Investigation Methodology

The forensic audit gathered irrefutable evidence across four independent observation planes:
1. **Physical Container Access Logs:** Systemd journal logs for `aihost-vllm-worker1.service` (Podman container `vllm-xpu-tp1-worker1`) and `aihost-vllm-worker2.service` (Podman container `vllm-xpu-tp1-worker2`) on `10.0.8.5`.
2. **Gateway Event Audits:** Cryptographic event stream records from `/var/lib/local-ai/evidence/t5820-v128-control-cooperative-generation-003/gateway-evidence.jsonl` and `...-generation-004/gateway-evidence.jsonl`.
3. **vLLM Engine Internals:** Periodic 10-second engine logs reporting active requests, prompt throughput, generation throughput, and GPU KV-cache allocation.
4. **Experimental Runner Telemetry:** High-resolution per-item and per-project timestamps from [`sustained_queue_runner.py`](file:///home/mike/Projects/aihost/phase14/src/autonomous_engineering/pipeline_rebalancing/sustained_queue_runner.py).
