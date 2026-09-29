# Phase 14 Experiment 02: Sustained Queue Measurement Definitions

## 1. Metric Taxonomy and Timing Formalisms

All queue timing, resource utilization, and throughput metrics are captured using high-resolution monotonic timestamps (`time.monotonic()`) at the boundary of queue admission, stage dispatch, item completion, and independent gate validation.

```
Project Arrival (t_arr)
      │
      ▼  [Queue Wait: W_q = t_disp - t_arr]
Project Dispatch (t_disp)
      │
      ▼  [Stage 1: Investigation & Planning]
Stage 1 Complete (t_s1)
      │
      ▼  [Stage 2: Parallel Specialist / Review]
Stage 2 Complete (t_s2)
      │
      ▼  [Stage 3: Integration & Acceptance]
Project Acceptance (t_acc)
      │
      └─────────────────────────────────────────────────────►
        Execution Turnaround: T_turnaround = t_acc - t_disp
        End-to-End Latency:   T_e2e = t_acc - t_arr = W_q + T_turnaround
```

---

## 2. Core Queue & Latency Formulations

### 2.1 Arrival and Throughput Rates
- **Offered Arrival Rate ($\lambda_{\text{offered}}$)**:
  $$\lambda_{\text{offered}} = \frac{N_{\text{offered}}}{t_{\text{arrival, last}} - t_{\text{arrival, first}}} \times 3600 \quad \text{projects/hour}$$
- **Independently Accepted Completion Rate ($X_{\text{accepted}}$)**:
  $$X_{\text{accepted}} = \frac{N_{\text{accepted}}}{t_{\text{drain, complete}} - t_{\text{arrival, first}}} \times 3600 \quad \text{projects/hour}$$
- **Rejection and Failure Rate ($R_{\text{failed}}$)**:
  $$R_{\text{failed}} = \frac{N_{\text{rejected}} + N_{\text{error}}}{N_{\text{admitted}}}$$

### 2.2 Latency and Queue Wait Distributions
- **Queue Wait Time ($W_{q, i}$)**: The delay between project arrival in the admission queue and the initiation of its first task:
  $$W_{q, i} = t_{\text{dispatch}, i} - t_{\text{arrival}, i}$$
- **Execution Turnaround Time ($T_{\text{turnaround}, i}$)**: The physical execution duration once dispatched:
  $$T_{\text{turnaround}, i} = t_{\text{acceptance}, i} - t_{\text{dispatch}, i}$$
- **End-to-End Latency ($T_{\text{e2e}, i}$)**: The user-perceived turnaround including queue buffer delay:
  $$T_{\text{e2e}, i} = t_{\text{acceptance}, i} - t_{\text{arrival}, i} = W_{q, i} + T_{\text{turnaround}, i}$$
- **Tail Latency Quantiles**: Sample percentiles (p50, p90, p95, p99) computed over the admitted cohort.

---

## 3. Worker Utilization and Idle Accounting

For campaign duration $T_{\text{campaign}} = t_{\text{final}} - t_{\text{start}}$:

- **Worker 1 Active Service Demand ($D_{1, \text{total}}$)**:
  $$D_{1, \text{total}} = \sum_{i=1}^N D_{1, i}$$
- **Worker 1 Utilization ($U_1$)**:
  $$U_1 = \frac{D_{1, \text{total}}}{T_{\text{campaign}}}$$
- **Worker 2 Active Service Demand ($D_{2, \text{total}}$)**:
  $$D_{2, \text{total}} = \sum_{i=1}^N D_{2, i}$$
- **Worker 2 Utilization ($U_2$)**:
  $$U_2 = \frac{D_{2, \text{total}}}{T_{\text{campaign}}}$$
- **Worker Idle Times ($I_1, I_2$)**:
  $$I_1 = T_{\text{campaign}} - D_{1, \text{total}}, \quad I_2 = T_{\text{campaign}} - D_{2, \text{total}}$$

---

## 4. Queue Stability and Backlog Growth Criteria

A workload operating point is classified as **STABLE** if and only if all of the following conditions hold:

1. **Bounded Queue Depth**: Maximum queue depth does not grow monotonically toward queue capacity $Q_{\max}$.
2. **Backlog Clearance**: At the conclusion of the measurement interval, all admitted projects successfully drain to zero ($Q(t_{\text{end}}) = 0$).
3. **Queue Wait Boundedness**: Queue wait times do not exhibit exponential or divergent growth across successive arrivals.
4. **Zero Starvation / Dropped Work**: Every admitted project completes within the 360-second execution SLA.

If queue depth grows linearly ($\frac{dQ}{dt} > 0$) and queue wait inflates across project arrivals, the operating point is classified as **UNSTABLE** ($\rho > 1.0$).
