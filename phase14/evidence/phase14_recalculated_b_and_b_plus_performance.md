# Phase 14 Experiment 02: Recalculated Configuration B and B+ Performance

- **Date:** 2026-09-29
- **Scope:** Metric recalculation, uncertainty bounds, and attribution reconciliation across experimental cohorts.

---

## 1. Metric Accounting Rules and Ground Truth

In compliance with human instructions:
1. **No Silent Subtraction:** OpenCode execution duration has **not** been artificially subtracted from raw traces. All reported metrics represent empirical measurements.
2. **Defensible Separation:** Metrics are reported both across the complete cohort and partitioned into uncontended versus contended intervals.

---

## 2. Regime 1 (Nominal Arrival: $\lambda = 12.0\text{ proj/hr}$, $T_{\text{arr}} = 300\text{s}$)

Both arms executed in complete physical isolation with zero outside traffic:

| Metric | Configuration B (Control) | Configuration B+ (Candidate) | Difference |
|---|---|---|---|
| **Offered Projects** | 2 | 2 | 0 |
| **Accepted Projects** | 2 (100%) | 2 (100%) | 0 |
| **Accepted Throughput** | 12.00 proj/hr | 12.00 proj/hr | 0.0% |
| **Mean Turnaround** | 223.83 s | 224.01 s | +0.18 s (+0.08%) |
| **Worker 1 Mean Demand** | 196.53 s | 168.18 s | **-28.35 s (-14.42%)** |
| **Worker 2 Mean Demand** | 69.31 s | 97.51 s | +28.20 s (+40.69%) |
| **Mean Queue Wait** | 0.00 s | 0.00 s | 0.00 s |
| **P95 Latency** | 229.07 s | 229.23 s | +0.16 s |

**Finding:** In the sub-saturated regime, throughput is strictly arrival-bound at 12.0 proj/hr. Configuration B+ reduces Worker 1 service demand by **14.42%**, perfectly shifting the demand of Item 01 to Worker 2.

---

## 3. Regime 2 (Capacity Stress: $\lambda = 19.5\text{ proj/hr}$, $T_{\text{arr}} = 184.6\text{s}$)

### Comparative Results Summary

| Metric | Configuration B (Uncontended) | Configuration B+ (Contended by 14 OpenCode reqs) | Reported Difference |
|---|---|---|---|
| **Offered Projects** | 6 | 6 | 0 |
| **Accepted Projects** | 6 (100%) | 6 (100%) | 0 |
| **Total Campaign Duration** | 1337.59 s | 1214.10 s | **-123.49 s (-9.23%)** |
| **Accepted Throughput** | 16.15 proj/hr | 17.79 proj/hr | **+1.64 proj/hr (+10.15%)** |
| **Mean Queue Wait** | 93.68 s | 6.29 s | **-87.39 s (-93.29%)** |
| **P95 End-to-End Latency** | 404.45 s | 284.83 s | **-119.62 s (-29.58%)** |
| **Queue Wait Trend** | Divergent (+39.3s/proj) | Transient (0s on p1-4, 12s on p5, 25s on p6) | Stabilized arrival clearance |

---

## 4. Fine-Grained Partitioning of Configuration B+ (Projects 1-4 vs. 5-6)

Partitioning Configuration B+ by OpenCode interference reveals the precise impact of the concurrent workload:

| Project Sub-Cohort | Mean $W_1$ Demand | Mean Turnaround | Mean Queue Wait | Peak Queue Wait | OpenCode Status |
|---|---|---|---|---|---|
| **Projects 1 – 4 (B+)** | **164.80 s** | **236.95 s** | **0.00 s** | **0.00 s** | Uncontended (0 reqs) |
| **Projects 5 – 6 (B+)** | **171.85 s** | **259.80 s** | **18.85 s** | **25.50 s** | Contended (14 reqs) |
| **Projects 1 – 6 (All B)** | **194.86 s** | **222.92 s** | **93.68 s** | **189.70 s** | Uncontended (0 reqs) |

### Key Analytical Insights
1. **Uncontended B+ Service Demand:** For Projects 1-4, Worker 1 service demand averaged **164.80s**, well below the inter-arrival window of **184.6s**. As a direct consequence, queue wait was strictly **0.00 seconds** across the entire first 4 projects.
2. **Contended B+ Service Demand:** For Projects 5-6, the 14 OpenCode requests caused Worker 1 demand to rise to **171.85s** and turnaround to stretch to **259.80s**, causing the pipeline to fall slightly behind schedule and accumulate 12.2s and 25.5s of queue wait.
3. **Control Arm Saturation:** In contrast, Configuration B's Worker 1 service demand was **194.86s**, which exceeds the inter-arrival window of 184.6s by ~10.3s. This structural oversaturation caused queue wait to explode linearly from 0.0s to 189.7s, proving that Configuration B cannot handle 19.5 proj/hr even under perfect isolation.
