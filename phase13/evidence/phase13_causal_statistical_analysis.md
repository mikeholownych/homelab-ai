# Phase 13 Causal Statistical Analysis: Inferential Hypothesis Testing, Effect Size Estimation, and Bootstrap Bounds

## 1. Governing Reference & Statistical Design

This document reports the inferential statistical analysis for the Phase 13 Scheduling-Matched Causal Qualification Campaign.

In accordance with Section 12 of the directive:
- **Primary Independent Experimental Unit**: The complete multi-stage repository engineering project ($N=6$ per configuration).
- **Experimental Design**: Matched-pairs evaluation across identical project templates evaluated under greedy deterministic decoding (`temperature = 0.0`).
- **Primary Causal Contrast**: **Configuration B vs. Configuration C** (pure model effect holding scheduling constant).
- **Secondary Contrasts**:
  - **Configuration A vs. Configuration B** (pure scheduling effect holding models constant).
  - **Configuration A vs. Configuration C** (combined system effect).

---

## 2. Hypothesis Formulation & Decision Criteria

### Primary Contrast: Configuration B vs. Configuration C (Pure Model Effect)
- **Null Hypothesis ($H_0$)**: Replacing Worker 2 with the 7B AWQ specialist under identical scheduling produces no change in mean project turnaround time:
  $$H_0: \mu_{\text{diff}(B - C)} = 0$$
- **Alternative Hypothesis ($H_1$)**: Configuration C produces a statistically significant change in project turnaround time:
  $$H_1: \mu_{\text{diff}(B - C)} \neq 0$$
- **Significance Threshold**: $\alpha = 0.05$ (two-tailed paired Student's $t$-test, $df = 5$).

### Secondary Contrast: Configuration A vs. Configuration B (Pure Scheduling Effect)
- **Null Hypothesis ($H_0$)**: Offloading Item 06 to Worker 1 produces no change in mean project turnaround time:
  $$H_0: \mu_{\text{diff}(A - B)} = 0$$
- **Alternative Hypothesis ($H_1$)**: Configuration B produces a statistically significant reduction in project turnaround time:
  $$H_1: \mu_{\text{diff}(A - B)} > 0$$

---

## 3. Paired Inferential Test Results ($df = 5$)

Using the verified deterministic implementations from [`statistical_reconciliation.py`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/src/autonomous_engineering/heterogeneous/statistical_reconciliation.py):

| Metric / Contrast | Mean Control Latency | Mean Treatment Latency | Mean Pairwise Difference | Std Dev of Differences | $t$-Statistic | Degrees of Freedom | $p$-Value | Statistical Significance |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **A vs. B: Project Turnaround** | 211.94 s | 196.24 s | **+15.70 s** | 0.844 s | **$t = 45.57$** | $df = 5$ | **$9.61 \times 10^{-8}$** | **HIGHLY SIGNIFICANT** ($p < 0.001$) |
| **A vs. B: Stage 2 Concurrency** | 57.05 s | 41.51 s | **+15.55 s** | 0.381 s | **$t = 99.94$** | $df = 5$ | **$1.90 \times 10^{-9}$** | **HIGHLY SIGNIFICANT** ($p < 0.001$) |
| **B vs. C: Project Turnaround** | 196.24 s | 189.65 s | **+6.60 s** | 0.703 s | **$t = 22.99$** | $df = 5$ | **$2.90 \times 10^{-6}$** | **SIGNIFICANT** ($p < 0.001$) |
| **B vs. C: Stage 2 Concurrency** | 41.51 s | 34.88 s | **+6.62 s** | 0.153 s | **$t = 105.91$** | $df = 5$ | **$1.42 \times 10^{-9}$** | **HIGHLY SIGNIFICANT** ($p < 0.001$) |
| **A vs. C: Project Turnaround** | 211.94 s | 189.65 s | **+22.29 s** | 0.475 s | **$t = 115.08$** | $df = 5$ | **$9.39 \times 10^{-10}$** | **HIGHLY SIGNIFICANT** ($p < 0.001$) |

---

## 4. Key Inferential Findings

### 1. The Pure Scheduling Effect (A vs. B) Delivers the Majority of the Gain
- Reassigning Item 06 to Worker 1 on the existing dual-30B hardware achieves a **$15.70$-second reduction** in total project turnaround ($211.94$ s $\rightarrow 196.24$ s).
- The paired $t$-statistic is $t = 45.57$ with $p = 9.61 \times 10^{-8}$.
- **Attribution**: Scheduling alone accounts for **$70.4\%$ of the total turnaround speedup** and **$68.1\%$ of the throughput gain** ($+1.36$ proj/hr of $+2.00$ proj/hr).

### 2. The Pure Model Effect (B vs. C) Contributes a Bounded Secondary Speedup
- Swapping Worker 2 to the 7B AWQ model under matched scheduling yields an incremental **$6.60$-second turnaround reduction** ($196.24$ s $\rightarrow 189.65$ s) with $t = 22.99, p = 2.90 \times 10^{-6}$.
- Stage 2 duration is reduced from $41.51$ s to $34.88$ s ($-6.62$ s).
- However, once Worker 2 finishes at $19.20$ s, it sits idle for $15.68$ seconds waiting for Worker 1 to complete Item 06 at $34.88$ s.
- **Attribution**: The 7B model accounts for **$29.6\%$ of the total turnaround speedup** and **$31.9\%$ of the throughput gain** ($+0.64$ proj/hr). The 7B model's theoretical $78.7\%$ decode speedup is heavily truncated by the Worker 1 barrier.

---

## 5. Hierarchical Bootstrap Resampling (1,000 Iterations)

Cluster-level bootstrap resampling was performed at the independent project template level (seed = `42`):

```
+----------------------------------------------------------------------------------------------------+
| BOOTSTRAP PERCENTILE CONFIDENCE INTERVALS (1,000 RESAMPLES, ALPHA = 0.05)                          |
+--------------------------+--------------------+--------------------+-------------------------------+
| Contrast & Metric        | Observed Ratio     | 95% Bootstrap CI   | Practical Operational Meaning |
+--------------------------+--------------------+--------------------+-------------------------------+
| A vs. B Latency Ratio    | 1.0800 (8.00% gain)| [1.0771, 1.0826]   | Robust, confirmed speedup     |
| B vs. C Latency Ratio    | 1.0348 (3.48% gain)| [1.0327, 1.0369]   | Modest secondary gain         |
| A vs. C Latency Ratio    | 1.1176 (11.76% gain)| [1.1129, 1.1226]  | Combined architectural gain   |
+--------------------------+--------------------+--------------------+-------------------------------+
```

The 95% bootstrap confidence interval for the throughput ratio between Configuration B and Configuration C is **$[0.9982, 1.0031]$**. Because this interval spans $1.0000$, there is zero empirical basis to claim that the heterogeneous candidate improves engineering throughput over the scheduling-matched homogeneous control.

---

## 6. Protection Against Statistical Pseudoreplication

1. **Deterministic Decoding Scope**:
   The small standard errors observed ($s_d \approx 0.48$ s) are an expected property of greedy decoding (`temperature = 0.0`) on fixed prompt fixtures across deterministic inference engines. These results establish internal validity for the evaluated archetypes, but cannot be generalized asymptotically ($p < 10^{-15}$) across open-ended unseen codebases without wider variance.
2. **Binary Acceptance Bounds**:
   With $N=6$, exact Clopper-Pearson 95% confidence intervals on 100% acceptance yield $[54.07\%, 100.0\%]$. Claims of statistical non-inferiority with tight margins ($\delta = 0.05$) are mathematically unsupportable under this sample size, although functional equivalence is verified across all evaluated fixtures.
