# Phase 14 Experiment 02: Sustained Workload Design

## 1. Objective and Causal Hypothesis

Phase 14 Experiment 01 established a significant reduction in Worker 1 critical-path service demand ($197.28\text{s} \rightarrow 168.56\text{s}$, $-14.56\%$) under isolated single-project execution. This implied a theoretical saturated capacity increase from $18.25$ to $21.36$ projects/hour (+17.0%).

**The objective of Phase 14 Experiment 02** is to empirically test this throughput capacity claim under sustained, multi-project arrival queues.

### Primary Experimental Hypothesis
> *Under a multi-project arrival queue operating at or near the Configuration B bottleneck boundary ($\lambda \approx 19.5\text{ proj/hr}$), Configuration B experiences queue instability ($\rho > 1.0$) with backlog growth and tail-latency inflation, whereas Configuration B+ remains queue-stable ($\rho < 1.0$) and delivers a statistically sustained increase in independently accepted engineering projects per hour.*

---

## 2. Experimental Regime Architecture

To evaluate the operational envelope without biasing towards either configuration, the experiment specifies two distinct workload regimes:

```
                      ┌──────────────────────────────────────────────┐
                      │          MULTI-PROJECT ARRIVAL QUEUE         │
                      └──────────────────────────────────────────────┘
                                              │
                      ┌───────────────────────┴───────────────────────┐
                      ▼                                               ▼
         [Regime 1: Sub-Saturated]                       [Regime 2: Capacity Boundary]
         λ = 12.0 projects/hour                          λ = 19.5 projects/hour
         Inter-arrival: 300s (5.0m)                      Inter-arrival: 184.6s (3.08m)
         Config B:  ρ = 0.658 (Stable)                   Config B:  ρ = 1.068 (UNSTABLE)
         Config B+: ρ = 0.562 (Stable)                   Config B+: ρ = 0.913 (STABLE)
```

### Regime 1: Sub-Saturated Stable Regime (Ordinary Operation)
- **Offered Arrival Rate**: $\lambda_1 = 12.0\text{ projects/hour}$ (mean inter-arrival time: $300\text{ seconds}$).
- **Target Condition**: Both configurations operate comfortably below capacity limits.
- **Hypothesis**: Both B and B+ maintain queue depth $\le 1$, zero backlog accumulation, bounded queue wait ($\approx 0\text{s}$), and 100% acceptance. Demonstrates that B+ introduces zero regressions under ordinary operational workloads.

### Regime 2: Capacity Boundary Stress Regime (Bottleneck Boundary)
- **Offered Arrival Rate**: $\lambda_2 = 19.5\text{ projects/hour}$ (mean inter-arrival time: $184.6\text{ seconds}$).
- **Target Condition**: The arrival rate is strictly above the Configuration B capacity ceiling ($18.25\text{ proj/hr}$) but strictly within the Configuration B+ capacity envelope ($21.36\text{ proj/hr}$).
- **Hypothesis**:
  - Configuration B accumulates queue backlog at rate $\approx 19.5 - 18.25 = +1.25\text{ projects/hour}$, resulting in queue wait inflation and tail-latency escalation.
  - Configuration B+ sustains the full arrival rate, keeps queue depth bounded, and achieves an independently accepted throughput rate exceeding $18.5\text{ proj/hr}$.

---

## 3. Workload Phases and Bounded Execution

Each experimental run adheres to a strict three-phase lifecycle:

1. **Warm-Up Phase**:
   - 1 pilot project dispatched to prime server caches, warm CUDA contexts, and verify end-to-end network connectivity.
   - Warm-up project metrics are recorded in raw traces but excluded from steady-state throughput calculations.
2. **Measurement Phase**:
   - Admitted cohort of projects dispatched according to the declared arrival schedule.
   - All queue entry times, dispatch times, stage latencies, worker service demands, and gate checks are logged with monotonic timers.
3. **Drain Phase**:
   - No new projects admitted.
   - All in-flight projects in the queue are processed through Stage 3 and submitted to independent validation gates.
   - Drain time is recorded to evaluate recovery dynamics.

---

## 4. Run Order & Thermal Bias Mitigation

To eliminate bias from environmental drift, GPU thermal throttling, or diurnal network variance:
- Run order alternates between configurations:
  - Sequence: `[Regime 1: Config B]` $\rightarrow$ `[Regime 1: Config B+]` $\rightarrow$ `[Regime 2: Config B+]` $\rightarrow$ `[Regime 2: Config B]`.
- A 60-second cooldown interval is enforced between cohorts to ensure GPU temperatures return to idle baseline ($\le 45^\circ\text{C}$).
