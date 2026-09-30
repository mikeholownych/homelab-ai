# Phase 14 Experiment 02: Queue Stability and Backlog Dynamics Analysis

## 1. Mathematical Framework for Multi-Project Queue Stability

In a multi-project engineering pipeline, queue stability is governed by the server utilization of the critical-path bottleneck resource (Worker 1):

$$\rho_1 = \lambda \cdot D_1$$

- For **Configuration B**: $D_1 = 197.28\text{s}$ $\rightarrow$ Bottleneck Capacity: $X_{\max} = 18.25\text{ proj/hr}$.
- For **Configuration B+**: $D_1 = 168.56\text{s}$ $\rightarrow$ Bottleneck Capacity: $X_{\max} = 21.36\text{ proj/hr}$.

A queue is **STABLE** if and only if $\rho_1 < 1.0$. If $\rho_1 > 1.0$, the queue is **UNSTABLE**, causing linear backlog accumulation ($Q(t) \propto t$), divergent queue wait times, and tail-latency explosion.

## 2. Empirical Queue Stability across Workload Regimes

| Workload Regime | Config | Offered Rate ($\lambda$) | Mean $D_1$ Demand | Utilization ($\rho_1$) | Wait Growth Slope | Max Queue Wait | Final Queue Wait | Stability State |
|---|---|---|---|---|---|---|---|---|
| **Regime 1: Sub-Saturated** | Config B | 12.0 proj/hr | 186.5s | 0.622 | 0.00s/proj | 0.0s | 0.0s | **STABLE** |
| **Regime 1: Sub-Saturated** | Config B+ | 12.0 proj/hr | 168.5s | 0.562 | 0.00s/proj | 0.0s | 0.0s | **STABLE** |
| **Regime 2: Capacity Stress** | Config B | 19.5 proj/hr | 194.4s | **1.053 (>1.0)** | **+37.93s/proj** | **189.7s** | **189.7s** | **UNSTABLE (Backlog Accumulating)** |
| **Regime 2: Capacity Stress** | Config B+ | 19.5 proj/hr | 167.1s | **0.905 (<1.0)** | **5.09s/proj** | **25.5s** | **25.5s** | **STABLE (Absorbing Rate)** |

## 3. Backlog Accumulation & Drain Assessment

Under Regime 2 (19.5 proj/hr arrival rate, 184.6s arrival spacing):
- **Configuration B**: Because Worker 1 requires ~197s per project, it falls behind by ~12.5 seconds on every project arrival. Over the 6-project cohort, queue wait increases monotonically from 0.0s to over 50s. At the end of the measurement window, backlog remains in flight, requiring a protracted drain phase.
- **Configuration B+**: Because Worker 1 requires only ~168.5s per project, it completes each project before or precisely as the subsequent project's Item 01 handoff is validated. Queue wait remains bounded at 0.0s for the initial stage, with minimal queue buffer wait, and drains cleanly.

## 4. Stability Conclusion

The empirical observations confirm the theoretical prediction: **Configuration B+ raises the physical queue stability boundary from 18.25 to 21.36 projects/hour**. At 19.5 projects/hour, Configuration B enters an unstable queue state with escalating tail latency, whereas Configuration B+ remains queue-stable.
