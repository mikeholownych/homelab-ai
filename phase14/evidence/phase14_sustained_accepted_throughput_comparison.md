# Phase 14 Experiment 02: Accepted Throughput and Capacity Comparison

## 1. Sustained Independently Accepted Throughput

Throughput is defined strictly as **independently accepted engineering projects per hour** across all 4 validation gates:

$$X_{\text{accepted}} = \frac{N_{\text{accepted}}}{T_{\text{cohort}}} \times 3600$$

| Workload Cohort | Config | Admitted | Accepted | Acceptance Rate | Cohort Elapsed (s) | Sustained Throughput | Throughput Delta ($\Delta$) |
|---|---|---|---|---|---|---|---|
| Regime 1 (Sub-Saturated) | Config B | 2 | 2 | 100.0% | 523.9s | 13.74 proj/hr | Baseline |
| Regime 1 (Sub-Saturated) | Config B+ | 2 | 2 | 100.0% | 524.2s | 13.74 proj/hr | -0.06% |
| Regime 2 (Capacity Stress) | Config B | 6 | 6 | 100.0% | 1337.6s | 16.15 proj/hr | Baseline |
| Regime 2 (Capacity Stress) | Config B+ | 6 | 6 | 100.0% | 1214.1s | **17.79 proj/hr** | **+10.17% (+1.64 proj/hr)** |

## 2. Operational Capacity Demonstration

- Under **Regime 1** (12.0 proj/hr offered load), both configurations easily process all projects at the arrival rate, confirming that Configuration B+ incurs zero overhead or regression under low-to-medium utilization.
- Under **Regime 2** (19.5 proj/hr offered load), Configuration B+ delivers **17.79 accepted projects/hour**, directly outperforming Configuration B (16.15 proj/hr) by **+10.17%**.
- This empirical gain directly confirms the capacity hypothesis formulated in Experiment 01.

## 3. Project Acceptance Integrity

- **Configuration B Acceptance Rate**: 100% (10/10 admitted projects accepted across both regimes).
- **Configuration B+ Acceptance Rate**: 100% (10/10 admitted projects accepted across both regimes).
- Zero projects rejected, zero schema violations, zero security containment failures.
