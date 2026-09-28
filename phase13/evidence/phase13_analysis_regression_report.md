# Phase 13 Analysis Regression Report: Deterministic Verification of Metric and Statistical Corrections

## 1. Governing Purpose & Scope
This report documents the design, implementation, and automated regression verification of the corrected analytical contracts governing Phase 13 evaluation metrics. 

During the reconciliation audit of the Expanded Physical Campaign (`phase13-heterogeneous-qualification` at commit [`fa65f04`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization)), multiple analytical defects were identified in published metrics and inferential claims, including:
1. Denominator conflation (treating completed-workload throughput as fixed-window queueing throughput).
2. Degrees-of-freedom and test misclassification (reporting independent Welch $t$-test on deterministic paired project templates, while miscalculating sample variance and degrees of freedom).
3. Statistical pseudoreplication (interpreting deterministic repetition on identical prompt seeds as independent physical variance, leading to unsupportable claims of $p < 10^{-15}$).
4. Underpowered and invalid non-inferiority claims on small-sample binary acceptance ($N=6$, $6/6$ vs $6/6$).

To ensure these defects cannot recur in future evaluation cycles or promotion gates, a dedicated statistical reconciliation module ([`statistical_reconciliation.py`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/src/autonomous_engineering/heterogeneous/statistical_reconciliation.py)) and a deterministic test suite ([`test_phase13_metric_and_statistical_analysis.py`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/tests/test_phase13_metric_and_statistical_analysis.py)) were constructed.

---

## 2. Analytical Edge Cases & Fixture Mapping

The test suite systematically covers all 12 analytical edge cases mandated by Section 12 of the reconciliation directive:

| # | Analytical Edge Case | Implementation Function | Test Assertion & Fixture Scope |
| :--- | :--- | :--- | :--- |
| **1** | **Correct Accepted-Project Numerator** | `calculate_throughput` | Verifies that rejected projects (e.g. failing acceptance gate 4) are strictly excluded from the throughput numerator, even if execution status is `COMPLETED`. |
| **2** | **Fixed vs. Completion Window Denominators** | `calculate_throughput` | Verifies the mathematical distinction between completed-workload throughput ($N_{\text{acc}} / T_{\text{active}}$) and sustained fixed-window throughput ($N_{\text{acc}} / T_{\text{fixed}}$), proving $18.98$ proj/hr vs $3.00$ proj/hr under a 2-hour window. |
| **3** | **Incomplete Projects** | `calculate_throughput` | Verifies that in-flight, timed-out, or aborted projects with missing `end_time` or `status != "COMPLETED"` are excluded from accepted counts and properly segregated. |
| **4** | **Zero Accepted Projects** | `calculate_throughput`, `binomial_confidence_interval` | Verifies that when $k=0$, throughput computes to strictly $0.0$ proj/hr without zero-division or NaN exceptions, and Clopper-Pearson returns $[0.0, 1 - (\alpha/2)^{1/n}]$. |
| **5** | **Overlapping Project Execution** | `merge_time_intervals`, `calculate_active_duration` | Verifies that concurrent or overlapping execution intervals merge into disjoint active wall-clock spans rather than naively summing latencies, preventing throughput deflation. |
| **6** | **Warm-up Exclusions** | `calculate_throughput` | Verifies that projects dispatched during or completed within a defined warmup window ($T_{\text{warmup}}$) are excluded from the steady-state numerator and denominator. |
| **7** | **Monotonic Timestamp Conversion** | `convert_monotonic_timeline` | Verifies validation of monotonic event sequences, calculation of elapsed seconds relative to base clock, and explicit error raising upon detecting negative clock skew. |
| **8** | **Paired Project Observations** | `paired_t_test`, `welch_t_test` | Verifies paired $t$-test evaluation on matched archetypes ($N=6$, $df=5$, $t=115.08$) and contrasts against independent Welch $t$-test ($df=9.06$, $t=68.92$), proving paired structure. |
| **9** | **Hierarchical Bootstrap Sampling** | `hierarchical_bootstrap` | Verifies cluster-level resampling at the independent project template level (not pooled prompt requests), producing deterministic percentile intervals and emitting small-sample warnings when $N < 10$. |
| **10** | **Insufficient Sample Size** | `paired_t_test`, `welch_t_test` | Verifies that tests strictly enforce $N \ge 2$, raising explicit `ValueError` when $N < 2$ rather than returning undefined or infinite values. |
| **11** | **Missing Observations in Paired Design** | `paired_t_test` | Verifies that unbalanced or missing observations across paired cohorts raise explicit errors, preventing silent misalignment of project templates. |
| **12** | **Invalid Non-Inferiority Margins** | `evaluate_non_inferiority` | Verifies rejection of non-positive or $\ge 1.0$ margins, emits power warnings for $N=6$, and demonstrates that exact Clopper-Pearson lower bounds ($54.07\%$) prevent claiming non-inferiority against $\delta=0.05$. |

---

## 3. Regression Test Execution Summary

The test suite was executed against the active repository worktree using `pytest 9.0.3` under `Python 3.12.3`:

```bash
$ PYTHONPATH=phase13/src pytest -v phase13/tests/test_phase13_metric_and_statistical_analysis.py
============================= test session starts ==============================
platform linux -- Python 3.12.3, pytest-9.0.3, pluggy-1.6.0 -- /usr/bin/python3
cachedir: .pytest_cache
rootdir: /home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization
plugins: asyncio-1.3.0, respx-0.23.1, anyio-4.13.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 12 items

phase13/tests/test_phase13_metric_and_statistical_analysis.py::test_accepted_project_numerator_filtering PASSED [  8%]
phase13/tests/test_phase13_metric_and_statistical_analysis.py::test_fixed_vs_completion_window_denominators PASSED [ 16%]
phase13/tests/test_phase13_metric_and_statistical_analysis.py::test_incomplete_project_handling PASSED [ 25%]
phase13/tests/test_phase13_metric_and_statistical_analysis.py::test_zero_accepted_projects PASSED [ 33%]
phase13/tests/test_phase13_metric_and_statistical_analysis.py::test_overlapping_project_execution PASSED [ 41%]
phase13/tests/test_phase13_metric_and_statistical_analysis.py::test_warmup_phase_exclusion PASSED [ 50%]
phase13/tests/test_phase13_metric_and_statistical_analysis.py::test_monotonic_timestamp_validation_and_clock_skew PASSED [ 58%]
phase13/tests/test_phase13_metric_and_statistical_analysis.py::test_paired_project_observations PASSED [ 66%]
phase13/tests/test_phase13_metric_and_statistical_analysis.py::test_hierarchical_bootstrap_sampling PASSED [ 75%]
phase13/tests/test_phase13_metric_and_statistical_analysis.py::test_insufficient_sample_size_guards PASSED [ 83%]
phase13/tests/test_phase13_metric_and_statistical_analysis.py::test_missing_observations_in_paired_design PASSED [ 91%]
phase13/tests/test_phase13_metric_and_statistical_analysis.py::test_invalid_non_inferiority_margins_and_underpowered_assertions PASSED [100%]

============================== 12 passed in 0.15s ==============================
```

---

## 4. Architectural & Safety Guarantees
1. **Zero External Heavy Dependencies**:
   The module avoids unverified runtime dependencies (such as `scipy` or `statsmodels`), implementing exact numerical algorithms for the incomplete beta function, Student's $t$ CDF, and normal percent-point approximations in pure Python standard library.
2. **Immutable Trace Integrity**:
   The tests operate purely on in-memory fixtures and historical constants without modifying or appending to the immutable physical traces (`phase13/traces/*.json`).
3. **Audit Reproducibility**:
   All bootstrap and statistical routines accept explicit random seeds and significance parameters, guaranteeing bit-for-bit deterministic reproducibility across subsequent regression runs.
