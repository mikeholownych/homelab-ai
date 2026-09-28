# Phase 13 Sustained Contract Reconciliation: Workload Feasibility, Queueing Dynamics, and Measurement Regimes

## 1. Governing Reference & Audit Objective

This document resolves the outstanding qualification contract established in [`expanded_operational_qualification_plan.md`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/evidence/expanded_operational_qualification_plan.md) and audited in [`phase13_preregistration_and_authorization_audit.md`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/evidence/phase13_preregistration_and_authorization_audit.md).

The prior reconciliation established that the Expanded Physical Campaign (`fa65f04`) completed six projects per configuration under saturated synchronous dispatch in ~19.0 to 21.2 minutes, failing to execute the preregistered continuous observation window ($\ge 2.0$ hours) or the Poisson arrival process ($\lambda = 4.0$ requests/minute).

This document establishes the exact mathematical feasibility of the registered arrival rates, reconciles the workload unit definitions, formalizes overload criteria, and freezes the measurement regimes for the causal qualification campaign.

---

## 2. Workload Unit Analysis & System Capacity Feasibility

The preregistered plan (`expanded_operational_qualification_plan.md`, Section 2.2) specified:
$$\text{Staged Poisson arrival process with burst phases } (\lambda = 4.0\text{ requests/min}) \text{ and steady phases } (\lambda = 1.5\text{ requests/min})$$

To prevent silent reinterpretation of the workload unit, we analyze both possible interpretations against measured physical service times:

### A. Interpretation 1: "Request" = Complete Engineering Project
- If the arrival rate specifies complete repository-scale projects:
  $$\lambda_{\text{burst}} = 4.0\text{ projects/min} = 240.0\text{ projects/hour}$$
  $$\lambda_{\text{steady}} = 1.5\text{ projects/min} = 90.0\text{ projects/hour}$$

- **Physical System Service Capacity**:
  Each project executes an 8-item dependency DAG across three sequential stages:
  - Stage 1 (Items 01, 02, 03): Executed on Worker 1 (30B MoE). Measured duration: $\approx 35.2$ seconds.
  - Stage 2 (Items 04, 05, 06): In Configuration B & C, Items 04 & 05 execute on Worker 2 while Item 06 executes concurrently on Worker 1. Worker 1 execution time: $\approx 34.9$ seconds.
  - Stage 3 (Items 07, 08): Executed on Worker 1 (30B MoE). Measured duration: $\approx 34.8$ seconds.
  - Total Worker 1 cumulative compute per project:
    $$T_{\text{worker1}} = 35.2 + 34.9 + 34.8 \approx 104.9\text{ seconds/project}$$

- **Maximum Single-Server Capacity**:
  Since Worker 1 is a single physical GPU (`0000:51:00.0`, port 8000), its theoretical maximum project processing capacity under 100% saturation (zero queue wait, zero idle time) is:
  $$\mu_{\text{max}} = \frac{3,600\text{ s}}{104.9\text{ s/project}} \approx 34.32\text{ projects/hour}$$

- **Traffic Intensity Under Project-Level Arrival**:
  $$\rho_{\text{burst}} = \frac{\lambda_{\text{burst}}}{\mu_{\text{max}}} = \frac{240.0}{34.32} \approx 6.99 \quad (\gg 1.0)$$
  $$\rho_{\text{steady}} = \frac{\lambda_{\text{steady}}}{\mu_{\text{max}}} = \frac{90.0}{34.32} \approx 2.62 \quad (\gg 1.0)$$

- **Feasibility Conclusion**:
  Under a project-level arrival interpretation, the system is fundamentally oversubscribed by **700% in burst phases** and **262% in steady phases**. In an unconstrained $M/M/1$ or $M/G/1$ queueing model, $\rho > 1$ leads to deterministic, unbounded queue divergence ($Q(t) \rightarrow \infty$). Specifically, the queue backlog would grow at an unmanageable rate of $\approx 205$ projects per hour, exhausting host memory or triggering timeouts within 10 minutes.

---

### B. Interpretation 2: "Request" = Individual Work Order (Subtask)
- If the arrival rate specifies discrete engineering work items dispatched to the orchestrator:
  Each project comprises exactly $8$ work items ($K = 8$). Therefore:
  $$\lambda_{\text{burst}} = 4.0\text{ tasks/min} = \frac{4.0}{8} = 0.50\text{ projects/min} = 30.0\text{ projects/hour}$$
  $$\lambda_{\text{steady}} = 1.5\text{ tasks/min} = \frac{1.5}{8} = 0.1875\text{ projects/min} = 11.25\text{ projects/hour}$$

- **Traffic Intensity Under Task-Level Arrival**:
  $$\rho_{\text{burst}} = \frac{30.0}{34.32} \approx 0.874 \quad (< 1.0)$$
  $$\rho_{\text{steady}} = \frac{11.25}{34.32} \approx 0.328 \quad (\ll 1.0)$$

- **Feasibility Conclusion**:
  Under the task-level arrival interpretation, the physical host operates in a realistic, non-divergent queueing regime:
  - Burst phase ($\rho = 0.874$): Highly saturated operating regime, testing queue buffering, scheduling concurrency, and specialist offloading under peak pressure.
  - Steady phase ($\rho = 0.328$): Normal nominal operating regime with rapid queue draining.

---

## 3. Preregistered Overload and Queue Management Policy

To ensure rigorous qualification regardless of workload interpretation, the following prospective admission and queue management rules are frozen:

1. **Explicit Admission Bound**:
   Maximum concurrent active projects admitted to execution is capped at $N_{\text{max\_active}} = 3$. Any arriving project when $N_{\text{active}} = 3$ enters the Orchestrator Project Queue.
2. **Queue Backlog Ceiling**:
   The Orchestrator Project Queue capacity is bounded at $Q_{\text{max}} = 10$. If an arriving project finds $Q(t) \ge 10$, it is flagged as `DROPPED_OVERLOAD` and recorded in the queue telemetry.
3. **Task-Level Queueing**:
   Specialist tasks (Items 04, 05) and Lead tasks (Items 01, 02, 03, 06, 07, 08) queue independently on their respective worker endpoints:
   - Worker 1 queue: Max concurrency = 1 (Stage 1/3) or 1 (Stage 2 concurrent).
   - Worker 2 queue: Max concurrency = 2 (`max-num-seqs: 2`).

---

## 4. Frozen Dual-Regime Evaluation Strategy

To eliminate denominator conflation and provide complete evidentiary coverage, the causal campaign executes two distinct, clearly separated evaluation regimes:

### Regime 1: Completed-Workload Saturated Benchmark ($N=6$ per configuration)
- **Objective**: Measure absolute system throughput under 100% capacity saturation (back-to-back synchronous project execution).
- **Configurations Tested**: Configuration A, Configuration B, Configuration C.
- **Metric**:
  $$\text{Throughput}_{\text{completed}} = \frac{N_{\text{accepted}}}{\Delta t_{\text{active}}} \times 3,600$$
- **Primary Causal Contrast**: Configuration B vs. Configuration C isolates the pure effect of the 7B AWQ model over the 30B MoE model under identical scheduling.

### Regime 2: Sustained Queueing & Poisson Arrival Observation
- **Objective**: Evaluate queue dynamics, queue backlog stability, arrival vs. service rates, and tail latency under stochastic Poisson arrival.
- **Configurations Tested**: Scheduling-matched architectures (Configuration B and Configuration C).
- **Workload Profile**: Staged Poisson arrival ($\lambda = 4.0$ req/min burst, $\lambda = 1.5$ req/min steady).
- **Metrics**:
  - Queue depth trajectory $Q(t)$
  - Mean and 95th percentile project wait time $W_q$
  - End-to-end turnaround latency $T_{\text{turnaround}} = W_q + T_{\text{service}}$
  - Stability disposition: Stable operating regime ($\rho < 1$) vs. backlogged queue ($\rho \ge 1$).

This dual-regime formulation satisfies the full preregistered contract while preserving unambiguous denominators and rigorous causal isolation.
