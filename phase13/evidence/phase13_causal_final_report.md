# Phase 13 Causal Final Report: Scheduling-Matched Heterogeneous Qualification and Architectural Disentanglement

## 1. Executive Summary & Terminal Disposition

- **Phase Mission**: Execute a scheduling-matched three-configuration physical qualification campaign to determine whether a heterogeneous inference topology (Worker 1 30B MoE + Worker 2 7B Dense) provides an incremental accepted-engineering outcome benefit over an identically scheduled homogeneous dual-30B system.
- **Governing Baseline**: Branch `phase13-heterogeneous-qualification` at release commit [`054db16`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization).
- **Physical Testbed**: Dell Precision T5820 (`10.0.8.5`), Dual Intel Arc Pro B65 GPUs (`0000:51:00.0` and `0000:93:00.0`).
- **Terminal Reconciled Disposition**:

```
PHASE_13_CAUSAL_AND_SUSTAINED_QUALIFICATION: PROVEN_WITH_LIMITATIONS
```

### Primary Architectural Determination:
1. **Scheduling Optimization Yields the Majority of the Speedup**: Reassigning Item 06 (Security Review) from Worker 2 to Worker 1 while dispatching Items 04 & 05 to Worker 2 on the existing dual-30B inventory (**Configuration B**) reduces mean project latency by **$15.70$ seconds ($7.4\%$)** and Stage 2 latency by **$15.55$ seconds ($27.3\%$)** with overwhelming statistical significance ($t = 45.57, p = 9.61 \times 10^{-8}$). This delivers $+1.3596$ projects/hour ($+8.00\%$), accounting for **$70.4\%$ of the total turnaround speedup**.
2. **Specialist Model Swap Yields a Bounded Secondary Speedup**: Under identical scheduling conditions, swapping Worker 2 from the 30B MoE model to the 7B AWQ model (**Configuration C**) produces an incremental latency reduction of **$6.60$ seconds ($3.36\%$)** ($t = 22.99, p = 2.90 \times 10^{-6}$), accounting for **$29.6\%$ of the turnaround speedup**.
3. **The 7B Specialist Speedup is Truncated by the Worker 1 Barrier**: In Configuration C, Worker 2 (7B) completes Items 04 & 05 in $19.20$ seconds. However, Stage 2 cannot complete until Worker 1 (30B) finishes Item 06 at $34.88$ seconds. Worker 2 sits idle for $15.68$ seconds waiting for Worker 1. The 7B model's theoretical $78.7\%$ token decode speedup is heavily truncated by the Worker 1 critical path barrier.
4. **Production Recommendation**: **Adopt Configuration B (Scheduling-Matched Homogeneous Dual-30B)**. Swapping Worker 2 to the 7B model is **not justified** for general production serving due to prompt injection vulnerabilities and diminished critical-path returns.

---

## 2. Reconciled Metrics Comparison Across Configurations

```
+----------------------------------------------------------------------------------------------------+
| THREE-CONFIGURATION PHYSICAL PERFORMANCE RECONCILIATION                                            |
+--------------------------+--------------------+--------------------+--------------------+----------+
| Metric                   | Config A (Control) | Config B (Matched) | Config C (Candidate| Delta B-C|
+--------------------------+--------------------+--------------------+--------------------+----------+
| Worker 1 Model           | 30B MoE (AWQ-4bit) | 30B MoE (AWQ-4bit) | 30B MoE (AWQ-4bit) | 0.0%     |
| Worker 2 Model           | 30B MoE (AWQ-4bit) | 30B MoE (AWQ-4bit) | 7B Dense (AWQ)     | Model Chg|
| Stage 1 Latency          | 98.52 s            | 98.53 s            | 98.60 s            | +0.07 s  |
| Stage 2 Concurrency Dur. | 57.05 s            | 41.51 s            | 34.88 s            | -6.63 s  |
| Stage 3 Latency          | 56.37 s            | 56.28 s            | 56.17 s            | -0.11 s  |
| Mean Project Turnaround  | 211.94 s           | 196.24 s           | 189.65 s           | -6.60 s  |
| Completed Throughput     | 16.9850 proj/hr    | 18.3446 proj/hr    | 18.9828 proj/hr    | +0.6382  |
| Specialist Decode Speed  | 14.86 tok/s        | 14.86 tok/s        | 26.56 tok/s        | +78.73%  |
| Worker 2 Idle in Stage 2 | 0.00 s             | 0.63 s             | **15.68 s**        | +15.05 s |
| Project Acceptance Rate  | 6 / 6 (100.0%)     | 6 / 6 (100.0%)     | 6 / 6 (100.0%)     | 0.0%     |
| Subtask Acceptance Rate  | 48 / 48 (100.0%)   | 48 / 48 (100.0%)   | 48 / 48 (100.0%)   | 0.0%     |
| Adversarial Containment  | N/A (Baseline)     | N/A (Baseline)     | 10 / 10 (100.0%)   | 100% Cont|
+--------------------------+--------------------+--------------------+--------------------+----------+
```

---

## 3. Causal Disentanglement Summary

```
+----------------------------------------------------------------------------------------------------+
| CAUSAL ATTRIBUTION BREAKDOWN                                                                       |
+------------------------------+--------------------+----------------+-------------------------------+
| Comparison Contrast          | Latency Delta      | Relative Gain  | Inferential Grounding         |
+------------------------------+--------------------+----------------+-------------------------------+
| **A -> B: Pure Scheduling**  | **-15.70 s**       | **-7.41%**     | $t = 45.57, p = 9.61 \times 10^{-8}$ (Sig) |
| **B -> C: Pure Model Swap**  | **-6.60 s**        | **-3.36%**     | $t = 22.99, p = 2.90 \times 10^{-6}$ (Sig) |
| **A -> C: Combined System**  | **-22.29 s**       | **-10.52%**    | $t = 115.08, p = 9.39 \times 10^{-10}$ (Sig)|
+------------------------------+--------------------+----------------+-------------------------------+
```

The data unambiguously demonstrates that **$70.4\%$ of the historical acceleration** ($15.70$ of $22.29$ s) reported for the heterogeneous candidate is achieved by scheduling alone. Swapping the specialist model accounts for $29.6\%$ ($6.60$ s) of the latency reduction, delivering an incremental throughput gain of only $+0.64$ projects/hour ($+3.48\%$).

---

## 4. Sustained Queueing & Capacity Findings

1. **Worker 1 Capacity Limit**:
   Worker 1 is the primary server bottleneck ($\mu_1 \approx 18.97$ proj/hr). In both Configuration B and Configuration C, Worker 1 executes 6 out of 8 tasks per project.
2. **Poisson Stability Boundary**:
   Under the registered task arrival rate ($\lambda = 4.0$ tasks/min = 0.5 proj/min = 30 proj/hr), the system requires queue buffering ($\rho_1 = 1.58$ during burst). Over a 2.0-hour staged cycle (30 min burst + 90 min steady), the cumulative project demand ($31.88$ projects) is less than the multi-hour service capacity ($37.94$ projects), confirming asymptotic queue ergodicity.
3. **Zero Queue Reduction from 7B Specialist**:
   Because Worker 2 operates at $\le 24\%$ utilization during burst phases, accelerating Worker 2 from $28.8$ s to $19.2$ s produces zero relief on the primary project queue.

---

## 5. Security & Boundary Containment

- In physical revalidation across 10 adversarial injection probes, the 7B candidate complied with malicious instructions in $60\%$ of cases.
- However, the external AST and JSON boundary validator ([`ExternalAuthorityBoundary`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/src/autonomous_engineering/heterogeneous/containment.py)) intercepted and quarantined **10 out of 10 attacks**.
- Zero tool calls, zero filesystem escapes, and zero credential exfiltration events occurred.
- Retaining Configuration B eliminates this expanded threat surface by keeping the more aligned 30B MoE model on Worker 2.

---

## 6. Required Follow-Up Proposal for Heterogeneous Promotion

To qualify the 7B specialist for future production deployment, a new architectural DAG must be designed to place the specialist on the critical path:
1. **DAG Rebalancing**: Transfer tasks from Worker 1 to Worker 2 (e.g. architectural linting, documentation, refactoring proposals) to reduce Worker 1 compute demand.
2. **Asynchronous Batch Execution**: Deploy the 7B model in offline batch generation where its $78.7\%$ decode speedup translates directly into token cost savings and VRAM reduction without synchronous lead blocking.
