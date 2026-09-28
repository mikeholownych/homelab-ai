# Phase 13 Statistical Validity Audit Report

## 1. Executive Summary & Audit Mandate
This audit independently inspects the inferential statistics, hypothesis testing methods, experimental units, and confidence bounds reported in [`phase13_expanded_comparative_analysis.md`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/evidence/phase13_expanded_comparative_analysis.md).

### Summary of Audit Findings:
1. **Arithmetic Errors in Published Welch Test**:
   - The reported control variance was $s^2 = 0.126$ (actual $s^2 = 0.4150$).
   - The reported $t$-statistic was $t = 93.42$ with $df = 9.38$ (actual Welch $t = 68.92$ with $df = 9.06$).
2. **Pseudoreplication & Inappropriate Parametric Model**:
   - The two cohorts evaluated the exact same 6 project templates (`CTRL-01` to `CTRL-06` vs `HETERO-01` to `HETERO-06`) at greedy decoding (`temperature = 0.0`).
   - Treating them as independent random samples in an unpaired Welch t-test commits pseudoreplication and ignores the paired experimental design.
   - For matched fixtures, a **paired difference analysis** ($df = 5$) is the correct descriptive formulation ($t_{\text{paired}} = 115.08, p = 5.2 \times 10^{-8}$).
3. **Statistical Fallacy of $p < 10^{-15}$ across Workloads**:
   - The ultra-small variance is an artifact of deterministic greedy sampling on identical text prompts, not low variance across the infinite population of real-world software projects.
   - A sample of $N = 6$ benchmark fixtures cannot support generalizable population claims of $p < 10^{-15}$ for all production engineering tasks.
4. **Bootstrap Confidence Interval Understatement**:
   - The reported 95% bootstrap CI `[1.112x, 1.123x]` resampled across $N = 6$ nearly identical ratio values.
   - With $N = 6$, empirical bootstrap percentiles fail to model tail distributions and omit between-repository variation.
5. **Ungrounded Non-Inferiority Claim ($p < 0.001$)**:
   - Claiming non-inferiority with $p < 0.001$ for binomial acceptance (6/6 vs 6/6) is statistically invalid.
   - The exact 95% Clopper-Pearson lower bound for 6/6 successes is **54.07%** (Wilson score: **60.97%**). Parity was observed descriptively, but inferential non-inferiority cannot be proven with $N=6$.

---

## 2. Granular Evaluation of Statistical Claims

### 2.1 Recomputation of Two-Sample Test

| Parameter | Published in Comparative Analysis | Independently Recomputed (Unpaired Welch) | Corrected Paired Model ($df=5$) |
| :--- | :--- | :--- | :--- |
| **Sample Size ($N_1, N_2$)** | 6, 6 | 6, 6 | 6 pairs |
| **Control Mean ($\bar{x}_1$)** | 211.94s | 211.9383s | 211.9383s |
| **Control Variance ($s_1^2$)** | **0.126 (ERRONEOUS)** | **0.4150** | - |
| **Candidate Mean ($\bar{x}_2$)** | 189.65s | 189.6450s | 189.6450s |
| **Candidate Variance ($s_2^2$)** | 0.217 | 0.2128 | - |
| **Mean Paired Difference ($\bar{d}$)** | - | - | **22.2933s** |
| **StdDev of Differences ($s_d$)** | - | - | **0.4745s** |
| **Degrees of Freedom ($df$)** | 9.38 | 9.06 | **5.00** |
| **Test Statistic ($t$)** | **93.42 (ERRONEOUS)** | **68.92** | **115.08** |
| **$p$-value** | $< 10^{-15}$ | $7.7 \times 10^{-14}$ | $5.2 \times 10^{-8}$ |

**Finding**: The published report misstated both the control variance and the Welch $t$-statistic. While the wall-clock reduction on these 6 specific fixtures is consistent and repeatable, the inferential interpretation must be restricted to the tested benchmark cohort.

---

### 2.2 Paired vs. Unpaired Observations & Pseudoreplication
- Each project in the heterogeneous cohort (`HETERO-01` to `HETERO-06`) directly corresponds to a project in the control cohort (`CTRL-01` to `CTRL-06`):
  - Project 1: Distributed Consensus & State Machine Engine
  - Project 2: Durable Event Journal & Compactor
  - Project 3: REST / OpenAPI Microservices & Async Worker
  - Project 4: Zero-Downtime Database Migration Engine
  - Project 5: High-Throughput In-Memory LRU Cache & Eviction
  - Project 6: Security-Critical Auth Gateway & Permission Fencing
- Because identical prompt templates were used, the test was a **repeated-measures paired comparison**, not two independent random samples.
- The paired difference in wall-clock time was:
  - Project 1: $+22.16\text{s}$
  - Project 2: $+21.92\text{s}$
  - Project 3: $+22.37\text{s}$
  - Project 4: $+23.13\text{s}$
  - Project 5: $+22.39\text{s}$
  - Project 6: $+21.79\text{s}$
  - **Mean Paired Acceleration**: **$22.29\text{ seconds}$ ($\text{StdDev} = 0.47\text{s}$)**.

---

### 2.3 Bootstrap Resampling Limitations with $N = 6$
- The published analysis performed 10,000 bootstrap resamples on the 6 observed speedup ratios.
- The 6 speedup ratios are:
  $$\{1.1167, 1.1159, 1.1178, 1.1223, 1.1176, 1.1150\}$$
- Because all 6 observed ratios cluster tightly around $1.1176$ due to deterministic decoding, resampling from this discrete 6-element set inevitably yields a tiny confidence interval:
  $$\text{Bootstrap 95\% CI: } [1.1160, 1.1197] \text{ (paired)} \quad \text{or} \quad [1.112, 1.123] \text{ (published)}$$
- **Methodological Flaw**: An $N = 6$ bootstrap does not capture the true distribution of software engineering workloads. It captures only the sampling variance of this specific 6-project set under greedy token decoding.

---

### 2.4 Non-Inferiority Audit on Binary Project Acceptance
- Both campaigns observed $6 / 6$ accepted projects ($100.0\%$).
- The published report stated: `Non-inferior (p < 0.001)`.
- **Mathematical Correction**:
  - The exact 95% Clopper-Pearson confidence interval for $k = 6, n = 6$ is:
    $$[0.025^{1/6}, 1.0] = [0.5407, 1.0000]$$
  - The Wilson score interval with continuity correction is $[0.6097, 1.0000]$.
  - An observed sample of 6 successes provides insufficient statistical power to establish non-inferiority with $p < 0.001$ against any standard engineering margin (e.g., $\delta = 0.05$).
  - **Correct Statement**: "Acceptance parity was observed descriptively (6/6 vs 6/6, 100%), but formal statistical non-inferiority requires a much larger sample size ($N \ge 60$ for $\delta = 0.05$)."

---

## 3. Corrected Statistical Summary
1. **Descriptive Reality**: On the 6 evaluated representative project archetypes, the heterogeneous configuration completed each project an average of **22.29 seconds faster** (189.65s vs 211.94s, a **10.52% overall wall-clock reduction**), driven by a **22.17 second reduction in Stage 2** (34.88s vs 57.05s, a **38.86% concurrent stage reduction**).
2. **Inferential Boundary**: These results establish consistent physical speedup for the specific benchmark DAG and concurrency profile. They do not constitute generalizable mathematical proof across all possible repositories or prompt variations.
