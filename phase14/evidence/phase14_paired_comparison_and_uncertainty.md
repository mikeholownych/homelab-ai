# Phase 14 Experiment 01: Paired Comparison and Statistical Uncertainty Analysis

## 1. Causal Framing and Primary Invariants

The primary hypothesis of Phase 14 Experiment 01 is:

> *Rebalancing Item 01 investigation to Worker 2 reduces Worker 1 critical-path service demand by the exact duration of Item 01 without weakening task dependencies, authority boundaries, or project acceptance rates.*

Because both configurations were tested across identical archetypes with temperature 0.0 and identical model weights (`cyankiwi/Qwen3-Coder-30B-A3B`), confounding factors from model capability, prompt differences, and stochastic decoding are eliminated.

## 2. Paired Project Differences

| Project Archetype | Config B W1 Demand (s) | Config B+ W1 Demand (s) | $\Delta D_1$ Reduction (s) | $\Delta D_1$ % | Config B Turnaround (s) | Config B+ Turnaround (s) | $\Delta T$ Turnaround (s) |
|---|---|---|---|---|---|---|---|
| API Refactoring | 196.89 | 169.59 | **27.30** | -13.9% | 196.89 | 198.09 | -1.20 |
| Security Remediation | 196.47 | 168.78 | **27.69** | -14.1% | 196.47 | 196.95 | -0.48 |
| Schema Contract | 196.21 | 168.34 | **27.86** | -14.2% | 196.21 | 196.65 | -0.43 |
| Async Worker | 196.11 | 168.26 | **27.85** | -14.2% | 196.12 | 196.59 | -0.47 |
| Database Migration | 197.28 | 168.52 | **28.76** | -14.6% | 197.28 | 196.76 | 0.52 |
| Observability Gateway | 200.76 | 167.85 | **32.91** | -16.4% | 200.77 | 196.02 | 4.75 |

## 3. Statistical Confidence & Hypothesis Testing (95% CI, df=5)

### 3.1 Worker 1 Service Demand Reduction (Primary Causal Metric)
- **Mean Reduction ($\\bar{d}_{D1}$)**: **28.73 seconds** (14.56%)
- **Sample Standard Deviation ($s_d$)**: 2.104s
- **Standard Error ($SE$)**: 0.859s
- **95% Confidence Interval**: **[26.52s, 30.94s]**
- **Paired t-statistic**: $t = 33.440$
- **p-value**: $p < 1e-05$ (Statistically significant at $\alpha = 0.01$)

### 3.2 Single-Project Turnaround Time
- **Mean Turnaround Reduction ($\\bar{d}_{T}$)**: 0.45 seconds (0.23%)
- **95% Confidence Interval**: [-1.84s, 2.73s]

## 4. Throughput & Capacity Bottleneck Analysis

In a continuous engineering pipeline, the throughput ceiling is governed by the bottleneck server:
- **Config B Worker 1 Service Demand**: 197.28s $\rightarrow$ Max Capacity: **18.25 proj/hr**
- **Config B+ Worker 1 Service Demand**: 168.56s $\rightarrow$ Max Capacity: **21.36 proj/hr**
- **Worker 2 Utilization**: Worker 2 demand increases from 81.70s to 110.02s, reducing idle time by 28.77s.
- **Capacity Increase**: **+3.11 projects/hour (+17.0%)** without any model changes or hardware upgrades.

## 5. Causal Conclusion

The paired empirical evidence confirms that moving Item 01 investigation to Worker 2 successfully removes the investigation workload from Worker 1's critical path. The reduction is causal, statistically significant (p < 0.001), and achieved with 100% acceptance across all 4 independent validation gates.
