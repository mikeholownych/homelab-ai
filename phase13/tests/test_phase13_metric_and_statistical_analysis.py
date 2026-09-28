"""Tests for Phase 13 Metric and Statistical Reconciliation.

Enforces the corrected analytical contract and verifies 12 analytical edge cases:
1. Correct accepted-project numerator
2. Fixed-window versus completion-window denominators
3. Incomplete projects
4. Zero accepted projects
5. Overlapping project execution
6. Warm-up exclusions
7. Monotonic timestamp conversion
8. Paired project observations
9. Hierarchical bootstrap sampling
10. Insufficient sample size
11. Missing observations
12. Invalid non-inferiority margins
"""

import math
import pytest
from autonomous_engineering.heterogeneous.statistical_reconciliation import (
    calculate_throughput,
    convert_monotonic_timeline,
    paired_t_test,
    welch_t_test,
    binomial_confidence_interval,
    hierarchical_bootstrap,
    evaluate_non_inferiority,
    merge_time_intervals,
    calculate_active_duration,
)


# ============================================================================
# Edge Case 1: Correct Accepted-Project Numerator
# ============================================================================

def test_accepted_project_numerator_filtering():
    """Verify rejected projects are strictly excluded from throughput numerator."""
    projects = [
        {"id": "p1", "accepted": True, "status": "COMPLETED", "start_time": 0.0, "end_time": 100.0},
        {"id": "p2", "accepted": False, "status": "COMPLETED", "start_time": 100.0, "end_time": 200.0}, # Rejected
        {"id": "p3", "accepted": True, "status": "COMPLETED", "start_time": 200.0, "end_time": 300.0},
    ]
    # Total span 300s, but only 2 accepted
    result = calculate_throughput(projects, window_type="completion")
    assert result["accepted_count"] == 2
    assert result["total_completed_count"] == 3
    # Throughput: (2 / 300) * 3600 = 24.0 proj/hr
    assert result["throughput_per_hour"] == 24.0


# ============================================================================
# Edge Case 2: Fixed-Window vs Completion-Window Denominators
# ============================================================================

def test_fixed_vs_completion_window_denominators():
    """Verify distinct calculation between completed-workload and sustained fixed window."""
    # Historical Phase 13 expanded heterogeneous numbers: 6 accepted in 1137.87s
    projects = [
        {"id": f"p{i}", "accepted": True, "status": "COMPLETED", "start_time": i * 189.645, "end_time": (i + 1) * 189.645}
        for i in range(6)
    ]
    # Total duration = 6 * 189.645 = 1137.87s

    # Completion window: denominator is actual completion span (1137.87s)
    res_comp = calculate_throughput(projects, window_type="completion")
    assert res_comp["accepted_count"] == 6
    assert abs(res_comp["window_seconds"] - 1137.87) < 1e-4
    assert abs(res_comp["throughput_per_hour"] - 18.9828) < 1e-2

    # Fixed window (preregistered 2.0-hour requirement = 7200s)
    res_fixed = calculate_throughput(projects, window_type="fixed", fixed_window_seconds=7200.0)
    assert res_fixed["accepted_count"] == 6
    assert res_fixed["window_seconds"] == 7200.0
    # Throughput under fixed window: (6 / 7200) * 3600 = 3.0 proj/hr
    assert res_fixed["throughput_per_hour"] == 3.0


# ============================================================================
# Edge Case 3: Incomplete Projects
# ============================================================================

def test_incomplete_project_handling():
    """Verify in-flight or timed-out projects are excluded from accepted numerator."""
    projects = [
        {"id": "p1", "accepted": True, "status": "COMPLETED", "start_time": 0.0, "end_time": 200.0},
        {"id": "p2", "accepted": True, "status": "IN_FLIGHT", "start_time": 200.0, "end_time": None}, # Incomplete
        {"id": "p3", "accepted": False, "status": "TIMEOUT", "start_time": 200.0, "end_time": None}, # Timed out
    ]
    res = calculate_throughput(projects, window_type="completion")
    assert res["accepted_count"] == 1
    assert res["total_completed_count"] == 1
    assert res["incomplete_count"] == 2
    assert res["throughput_per_hour"] == 18.0  # (1 / 200s) * 3600


# ============================================================================
# Edge Case 4: Zero Accepted Projects
# ============================================================================

def test_zero_accepted_projects():
    """Verify zero accepted projects yields 0.0 throughput without division error."""
    projects = [
        {"id": "p1", "accepted": False, "status": "COMPLETED", "start_time": 0.0, "end_time": 100.0},
        {"id": "p2", "accepted": False, "status": "COMPLETED", "start_time": 100.0, "end_time": 200.0},
    ]
    res = calculate_throughput(projects, window_type="completion")
    assert res["accepted_count"] == 0
    assert res["throughput_per_hour"] == 0.0

    # Test confidence interval with k=0
    lower, upper = binomial_confidence_interval(k=0, n=6, method="clopper_pearson")
    assert lower == 0.0
    assert abs(upper - 0.4593) < 1e-3


# ============================================================================
# Edge Case 5: Overlapping Project Execution
# ============================================================================

def test_overlapping_project_execution():
    """Verify parallel intervals use active span union, not naive sum."""
    intervals = [(0.0, 50.0), (20.0, 70.0), (60.0, 100.0)]
    merged = merge_time_intervals(intervals)
    assert merged == [(0.0, 100.0)]
    assert calculate_active_duration(intervals) == 100.0

    # Disjoint intervals: [0, 40] and [60, 100]
    disjoint = [(0.0, 40.0), (60.0, 100.0)]
    assert calculate_active_duration(disjoint) == 80.0


# ============================================================================
# Edge Case 6: Warm-up Exclusions
# ============================================================================

def test_warmup_phase_exclusion():
    """Verify warmup projects and duration are excluded from steady-state throughput."""
    projects = [
        # Warmup project: started at t=0
        {"id": "warmup_p0", "accepted": True, "status": "COMPLETED", "start_time": 0.0, "end_time": 150.0},
        # Steady state projects: start >= 300.0
        {"id": "p1", "accepted": True, "status": "COMPLETED", "start_time": 300.0, "end_time": 500.0},
        {"id": "p2", "accepted": True, "status": "COMPLETED", "start_time": 500.0, "end_time": 700.0},
    ]
    # Warmup of 300 seconds
    res = calculate_throughput(projects, window_type="completion", warmup_seconds=300.0)
    assert res["accepted_count"] == 2
    assert res["total_completed_count"] == 2
    assert res["window_seconds"] == 400.0 # From 300.0 to 700.0
    # Throughput: (2 / 400) * 3600 = 18.0 proj/hr
    assert res["throughput_per_hour"] == 18.0


# ============================================================================
# Edge Case 7: Monotonic Timestamp Conversion
# ============================================================================

def test_monotonic_timestamp_validation_and_clock_skew():
    """Verify monotonic conversion detects backward clock skew."""
    valid_events = [
        {"timestamp": 1000.0, "event": "start"},
        {"timestamp": 1025.5, "event": "stage1"},
        {"timestamp": 1050.0, "event": "stage2"},
    ]
    converted = convert_monotonic_timeline(valid_events)
    assert len(converted) == 3
    assert converted[0]["elapsed_seconds"] == 0.0
    assert converted[1]["elapsed_seconds"] == 25.5
    assert converted[2]["elapsed_seconds"] == 50.0

    # Clock anomaly: timestamp drops
    skewed_events = [
        {"timestamp": 1000.0, "event": "start"},
        {"timestamp": 950.0, "event": "skewed"},
    ]
    with pytest.raises(ValueError, match="Clock anomaly detected"):
        convert_monotonic_timeline(skewed_events)


# ============================================================================
# Edge Case 8: Paired Project Observations vs Independent
# ============================================================================

def test_paired_project_observations():
    """Verify paired t-test correctly computes df=N-1 and accounts for covariance."""
    # Historical Project elapsed latencies for 6 archetypes (Control vs Heterogeneous)
    control_elapsed = [212.02, 211.11, 212.27, 212.30, 212.72, 211.21]
    hetero_elapsed = [189.86, 189.19, 189.90, 189.17, 190.33, 189.42]

    paired_res = paired_t_test(control_elapsed, hetero_elapsed)
    assert paired_res["n"] == 6
    assert paired_res["df"] == 5
    assert abs(paired_res["mean_difference"] - 22.2933) < 1e-3
    assert abs(paired_res["t_statistic"] - 115.0848) < 1e-2
    assert paired_res["p_value"] < 1e-8

    # Compare against independent Welch t-test
    welch_res = welch_t_test(control_elapsed, hetero_elapsed)
    assert welch_res["n1"] == 6
    assert welch_res["n2"] == 6
    # Welch degrees of freedom is 9.06 (Welch-Satterthwaite), NOT 5
    assert abs(welch_res["df"] - 9.0595) < 1e-3
    assert abs(welch_res["t_statistic"] - 68.921) < 1e-2


# ============================================================================
# Edge Case 9: Hierarchical Bootstrap Sampling
# ============================================================================

def test_hierarchical_bootstrap_sampling():
    """Verify bootstrap resamples at the independent project template level."""
    control_latencies = [211.85, 212.04, 211.90, 212.10, 211.80, 211.94]
    hetero_latencies = [189.62, 189.70, 189.60, 189.75, 189.58, 189.63]

    boot_res = hierarchical_bootstrap(
        control_latencies,
        hetero_latencies,
        n_resamples=500,
        seed=12345,
        metric_type="ratio",
    )
    # Ratio: ~189.65 / 211.94 = ~0.8948
    assert abs(boot_res["observed"] - 0.8948) < 0.01
    assert boot_res["small_sample_warning"] is True  # N=6 < 10
    assert boot_res["ci_lower"] < boot_res["observed"] < boot_res["ci_upper"]


# ============================================================================
# Edge Case 10: Insufficient Sample Size Guards
# ============================================================================

def test_insufficient_sample_size_guards():
    """Verify statistical tests reject N < 2."""
    with pytest.raises(ValueError, match="Insufficient sample size"):
        paired_t_test([10.0], [8.0])

    with pytest.raises(ValueError, match="Insufficient sample size"):
        welch_t_test([10.0], [8.0, 9.0])


# ============================================================================
# Edge Case 11: Missing Observations
# ============================================================================

def test_missing_observations_in_paired_design():
    """Verify mismatched sample lengths in paired tests raise ValueError."""
    ctrl = [10.0, 20.0, 30.0]
    hetero = [8.0, 16.0] # Missing 3rd observation
    with pytest.raises(ValueError, match="Mismatched sample lengths"):
        paired_t_test(ctrl, hetero)


# ============================================================================
# Edge Case 12: Invalid Non-Inferiority Margins and Underpowered Assertions
# ============================================================================

def test_invalid_non_inferiority_margins_and_underpowered_assertions():
    """Verify rejection of invalid margins and underpowered small-sample warnings."""
    # Invalid negative margin
    with pytest.raises(ValueError, match="Invalid non-inferiority margin"):
        evaluate_non_inferiority(6, 6, 6, 6, margin=-0.05)

    # Invalid margin >= 1.0
    with pytest.raises(ValueError, match="Invalid non-inferiority margin"):
        evaluate_non_inferiority(6, 6, 6, 6, margin=1.5)

    # Valid evaluation for N=6, 6/6 vs 6/6
    res = evaluate_non_inferiority(k_treatment=6, n_treatment=6, k_control=6, n_control=6, margin=0.05)
    assert res["p_treatment"] == 1.0
    assert res["p_control"] == 1.0
    assert res["rate_difference"] == 0.0
    assert "Underpowered sample size" in res["power_warning"]

    # Exact Clopper-Pearson lower bound for 6/6 is 0.5407.
    # Therefore, difference conservative lower bound is 0.5407 - 1.0 = -0.4593.
    # Against standard margin 0.05 (-0.05), non_inferior is FALSE because -0.4593 < -0.05!
    assert res["diff_conservative_lower_bound"] == -0.4593
    assert res["non_inferior"] is False
