# Phase 14 Experiment 02: Frozen Configuration B Control Verification

- **Date:** 2026-09-29
- **Control Cohort:** `regime2_config_b`
- **Canonical Repository:** `mikeholownych/homelab-ai`
- **Source Commit:** [`a8c3b6a1a4c27f391f28ebdf5a74c1bfd1d148ce`](file:///home/mike/Projects/aihost)
- **Control Evidence Source:** [`phase14/evidence/phase14_sustained_config_b_results.json`](file:///home/mike/Projects/aihost/phase14/evidence/phase14_sustained_config_b_results.json)
- **Preserved SHA256:** `ec48e5ceba0a475d4001cbf5f089679f22569fa12df0ca84f72db771804d9c79`

---

## 1. Frozen Control Integrity & Configuration Verification

Before comparing candidate Configuration B+ against the control baseline, the candidate frozen control was verified across all physical and architectural dimensions:

| Dimension | Frozen B Control Specification | Verification Status |
|---|---|---|
| **Scheduler Mode** | `SchedulingMode.CONFIGURATION_B` | Verified (Item 01 assigned to Worker 1) |
| **Worker 1 Model** | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` (rev: `4bd30395b72e`) | Verified on GPU 0 (Intel Arc A770, BDF `0000:03:00.0`) |
| **Worker 2 Model** | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` (rev: `4bd30395b72e`) | Verified on GPU 1 (Intel Arc A770, BDF `0000:04:00.0`) |
| **Workload Corpus** | 6 standardized capacity-stress project archetypes | Verified (API, Security, Schema, Worker, DB, Observability) |
| **Project Order** | Sequential (API $\rightarrow$ Security $\rightarrow$ Schema $\rightarrow$ Worker $\rightarrow$ DB $\rightarrow$ Obs) | Verified identical to B+ rerun order |
| **Arrival Schedule** | Offered $\lambda = 19.5\text{ proj/hr}$ ($T_{\text{arr}} = 184.6154\text{s}$) | Verified |
| **Acceptance Standard** | Independent 4-gate verification via [`ExternalAuthorityBoundary`](file:///home/mike/Projects/aihost/phase14/src/autonomous_engineering/pipeline_rebalancing/sustained_queue_runner.py) | Verified 6/6 projects accepted (100%) |
| **Forensic Isolation** | 0 concurrent outside requests during window (`06:26:21Z` to `06:48:39Z`) | Reconstructed from vLLM journals; 100% isolated |

---

## 2. Independent Raw Trace Recalculation

All metrics for the frozen control were recomputed directly from the raw project traces in [`phase14_sustained_config_b_results.json`](file:///home/mike/Projects/aihost/phase14/evidence/phase14_sustained_config_b_results.json) without relying on report summaries:

- **Total Admitted Projects:** 6
- **Total Accepted Projects:** 6 (100% acceptance rate)
- **First Arrival Sim Time:** $0.00\text{ s}$
- **Last Project Completion Sim Time:** $1,337.59\text{ s}$
- **Total Campaign Duration:** $1,337.59\text{ s}$ ($22.29\text{ minutes}$)
- **Accepted Throughput:** $\frac{6}{1337.59} \times 3600 = \mathbf{16.1484\text{ projects/hour}}$
- **Mean Queue Wait:** $\mathbf{93.68\text{ seconds}}$
- **P95 Queue Wait:** $\mathbf{189.67\text{ seconds}}$
- **Mean End-to-End Latency:** $\mathbf{316.61\text{ seconds}}$
- **P95 End-to-End Latency:** $\mathbf{414.51\text{ seconds}}$ (Reported p95: $404.45\text{s}$)
- **Mean Project Turnaround:** $\mathbf{222.93\text{ seconds}}$
- **Worker 1 Mean Service Demand:** $\mathbf{194.42\text{ seconds}}$
- **Worker 2 Mean Service Demand:** $\mathbf{68.69\text{ seconds}}$

### Project-by-Project Raw Trace Progression

| Project ID | Archetype | Arrival (s) | Dispatch (s) | Queue Wait (s) | Turnaround (s) | Completion (s) | W1 Demand (s) | W2 Demand (s) | Accepted |
|---|---|---|---|---|---|---|---|---|---|
| `sust-config_b-proj-api-01` | API Refactoring | 0.00 | 0.00 | 0.00 | 223.83 | 223.83 | 196.53 | 69.31 | True |
| `sust-config_b-proj-sec-02` | Security Remediation | 184.62 | 223.83 | 39.17 | 217.07 | 440.90 | 182.59 | 66.02 | True |
| `sust-config_b-proj-schema-03` | Schema Contract | 369.23 | 440.90 | 71.67 | 224.08 | 664.98 | 196.79 | 69.21 | True |
| `sust-config_b-proj-worker-04` | Async Worker | 553.85 | 664.98 | 111.19 | 223.83 | 888.87 | 196.38 | 69.21 | True |
| `sust-config_b-proj-db-05` | Database Migration | 738.46 | 888.87 | 150.39 | 223.93 | 1,112.80 | 196.81 | 69.09 | True |
| `sust-config_b-proj-obs-06` | Observability Gateway | 923.08 | 1,112.80 | 189.67 | 224.79 | 1,337.59 | 197.42 | 69.31 | True |

### Structural Saturation Dynamics
Under Configuration B, Worker 1 service demand averaged **$194.42\text{ seconds}$**, which strictly exceeds the inter-arrival spacing of **$184.62\text{ seconds}$** ($\rho_1 = 1.053 > 1.0$). Consequently, queue wait grew strictly monotonically by **$+39.3\text{ seconds per project}$** ($0\text{s} \rightarrow 39.2\text{s} \rightarrow 71.7\text{s} \rightarrow 111.2\text{s} \rightarrow 150.4\text{s} \rightarrow 189.7\text{s}$).

**Conclusion:** The frozen Configuration B control is mathematically and empirically valid, reproducible, and confirmed to have operated in complete physical isolation. It serves as an authoritative control baseline.
