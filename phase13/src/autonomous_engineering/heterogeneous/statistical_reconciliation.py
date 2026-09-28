"""Statistical Reconciliation and Metric Analysis Module for Phase 13.

Provides independent, deterministic, pure-Python implementations of:
- Exact throughput calculations (completed-workload vs fixed-window)
- Project acceptance filtering, warmup exclusion, and interval merging
- Monotonic timeline verification and clock skew detection
- Paired and Welch's t-tests with Student's t p-values
- Exact Clopper-Pearson and Wilson score binomial confidence intervals
- Cluster-level (hierarchical) bootstrap resampling
- Non-inferiority testing and margin validation
"""

import math
import random
from typing import Dict, List, Optional, Tuple, Union


# ============================================================================
# Math & Distribution Helpers (Pure Python)
# ============================================================================

def _betacf(a: float, b: float, x: float, max_iter: int = 200, eps: float = 1e-12) -> float:
    """Continued fraction evaluation for incomplete beta function (Lentz's method)."""
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        # Even step
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c

        # Odd step
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        del_h = d * c
        h *= del_h
        if abs(del_h - 1.0) < eps:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    if x < (a + 1.0) / (a + b + 2.0):
        front = math.exp(math.log(x) * a + math.log(1.0 - x) * b - lbeta) / a
        return front * _betacf(a, b, x)
    else:
        front_sym = math.exp(math.log(1.0 - x) * b + math.log(x) * a - lbeta) / b
        return 1.0 - front_sym * _betacf(b, a, 1.0 - x)


def student_t_pvalue(t_stat: float, df: float) -> float:
    """Two-tailed p-value for Student's t-distribution with df degrees of freedom."""
    if df <= 0:
        raise ValueError(f"Degrees of freedom must be positive, got {df}")
    if math.isnan(t_stat):
        return float("nan")
    x = df / (df + t_stat * t_stat)
    return betainc(df / 2.0, 0.5, x)


def beta_ppf(target: float, a: float, b: float, iterations: int = 60) -> float:
    """Percent-point function (quantile) of Beta(a, b) via bisection."""
    if target <= 0.0:
        return 0.0
    if target >= 1.0:
        return 1.0
    low, high = 0.0, 1.0
    for _ in range(iterations):
        mid = (low + high) / 2.0
        val = betainc(a, b, mid)
        if val < target:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


# ============================================================================
# Core Metric & Throughput Functions
# ============================================================================

def merge_time_intervals(intervals: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Merge overlapping or contiguous time intervals and return disjoint intervals."""
    if not intervals:
        return []
    sorted_intervals = sorted(intervals, key=lambda x: x[0])
    merged = [sorted_intervals[0]]
    for start, end in sorted_intervals[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def calculate_active_duration(intervals: List[Tuple[float, float]]) -> float:
    """Calculate the total non-overlapping duration from a list of time intervals."""
    merged = merge_time_intervals(intervals)
    return sum(end - start for start, end in merged)


def calculate_throughput(
    projects: List[Dict],
    window_type: str = "completion",
    fixed_window_seconds: Optional[float] = None,
    warmup_seconds: float = 0.0,
) -> Dict[str, Union[float, int, str]]:
    """Calculate project throughput under specified window model and constraints.

    Args:
        projects: List of project dictionaries. Must contain:
            - 'accepted' (bool): True if project passed all acceptance gates
            - 'status' (str): "COMPLETED", "FAILED", "IN_FLIGHT", etc.
            - 'start_time' (float): Monotonic or epoch start timestamp (seconds)
            - 'end_time' (float, optional): Monotonic or epoch completion timestamp
        window_type: 'completion' (workload completion window) or 'fixed' (fixed duration)
        fixed_window_seconds: Required if window_type == 'fixed'
        warmup_seconds: Duration of warm-up phase from earliest project start to exclude

    Returns:
        Dict with keys:
            - 'accepted_count': Number of accepted completed projects in steady state
            - 'total_completed_count': Number of completed projects in steady state
            - 'incomplete_count': Number of projects incomplete or in flight
            - 'window_seconds': Effective denominator duration in seconds
            - 'throughput_per_hour': Throughput in accepted projects per hour
            - 'window_type': Window type applied
    """
    if window_type not in ("completion", "fixed"):
        raise ValueError(f"Invalid window_type: {window_type}. Must be 'completion' or 'fixed'.")
    if window_type == "fixed" and (fixed_window_seconds is None or fixed_window_seconds <= 0):
        raise ValueError("fixed_window_seconds must be a positive number when window_type is 'fixed'.")

    if not projects:
        return {
            "accepted_count": 0,
            "total_completed_count": 0,
            "incomplete_count": 0,
            "window_seconds": fixed_window_seconds if window_type == "fixed" else 0.0,
            "throughput_per_hour": 0.0,
            "window_type": window_type,
        }

    # Determine earliest project start
    valid_starts = [p["start_time"] for p in projects if "start_time" in p]
    if not valid_starts:
        raise ValueError("Projects must have valid 'start_time' fields.")
    min_start = min(valid_starts)
    warmup_cutoff = min_start + warmup_seconds

    # Filter projects by steady-state criteria
    steady_state_projects = []
    incomplete_count = 0
    for p in projects:
        start = p.get("start_time", 0.0)
        status = p.get("status", "")
        end = p.get("end_time")

        # Check warmup exclusion
        if start < warmup_cutoff:
            continue

        # Incomplete / In-flight handling
        if status != "COMPLETED" or end is None:
            incomplete_count += 1
            continue

        steady_state_projects.append(p)

    # Numerator: Count strictly accepted completed projects
    accepted_count = sum(1 for p in steady_state_projects if p.get("accepted") is True)
    total_completed = len(steady_state_projects)

    # Denominator determination
    if window_type == "fixed":
        effective_window = fixed_window_seconds - warmup_seconds
        if effective_window <= 0:
            raise ValueError("Warmup duration exceeds or equals fixed window size.")
    else:
        # Completion window: active span from first steady-state start to last steady-state end
        if not steady_state_projects:
            effective_window = 0.0
        else:
            intervals = [(p["start_time"], p["end_time"]) for p in steady_state_projects]
            # Use interval span or interval union
            min_steady_start = min(s for s, _ in intervals)
            max_steady_end = max(e for _, e in intervals)
            effective_window = max_steady_end - min_steady_start

    # Throughput calculation
    if effective_window <= 0.0 or accepted_count == 0:
        throughput_per_hour = 0.0
    else:
        throughput_per_hour = (accepted_count / effective_window) * 3600.0

    return {
        "accepted_count": accepted_count,
        "total_completed_count": total_completed,
        "incomplete_count": incomplete_count,
        "window_seconds": effective_window,
        "throughput_per_hour": round(throughput_per_hour, 4),
        "window_type": window_type,
    }


def convert_monotonic_timeline(
    events: List[Dict],
    timestamp_key: str = "timestamp",
    require_strictly_increasing: bool = False,
) -> List[Dict]:
    """Validate and align event timestamps into relative monotonic offsets.

    Detects clock jumps, backward shifts, and converts timestamps to elapsed monotonic seconds.
    """
    if not events:
        return []

    processed = []
    base_time = None
    prev_time = None

    for idx, event in enumerate(events):
        if timestamp_key not in event:
            raise ValueError(f"Event at index {idx} missing timestamp key '{timestamp_key}'")

        t = float(event[timestamp_key])
        if base_time is None:
            base_time = t
            prev_time = t

        if require_strictly_increasing and t < prev_time:
            raise ValueError(f"Clock anomaly detected: timestamp decreased at index {idx} ({t} < {prev_time})")
        elif t < prev_time:
            raise ValueError(f"Clock anomaly detected: non-monotonic timestamp at index {idx} ({t} < {prev_time})")

        prev_time = t
        copied = dict(event)
        copied["elapsed_seconds"] = round(t - base_time, 4)
        processed.append(copied)

    return processed


# ============================================================================
# Inferential Statistics & Hypothesis Testing
# ============================================================================

def paired_t_test(
    sample_control: List[float],
    sample_treatment: List[float],
) -> Dict[str, float]:
    """Calculate exact paired Student's t-test on matched observations.

    Degrees of freedom is strictly N - 1.
    """
    if len(sample_control) != len(sample_treatment):
        raise ValueError(
            f"Mismatched sample lengths for paired t-test: {len(sample_control)} vs {len(sample_treatment)}"
        )
    n = len(sample_control)
    if n < 2:
        raise ValueError(f"Insufficient sample size for paired t-test: N={n}. Minimum N=2 required.")

    diffs = [c - t for c, t in zip(sample_control, sample_treatment)]
    mean_diff = sum(diffs) / n

    # Unbiased sample variance of differences
    var_diff = sum((d - mean_diff) ** 2 for d in diffs) / (n - 1)
    std_diff = math.sqrt(var_diff)

    if var_diff == 0.0:
        t_stat = 0.0
        p_val = 1.0
    else:
        se_diff = std_diff / math.sqrt(n)
        t_stat = mean_diff / se_diff
        df = n - 1
        p_val = student_t_pvalue(t_stat, df)

    return {
        "n": n,
        "df": n - 1,
        "mean_difference": round(mean_diff, 4),
        "std_difference": round(std_diff, 4),
        "t_statistic": round(t_stat, 4),
        "p_value": p_val,
    }


def welch_t_test(
    sample1: List[float],
    sample2: List[float],
) -> Dict[str, float]:
    """Calculate exact Welch's two-sample t-test with unequal variances.

    Uses unbiased sample variances (N-1 denominator) and Welch-Satterthwaite df.
    """
    n1 = len(sample1)
    n2 = len(sample2)
    if n1 < 2 or n2 < 2:
        raise ValueError(f"Insufficient sample size: n1={n1}, n2={n2}. Minimum 2 per group required.")

    mean1 = sum(sample1) / n1
    mean2 = sum(sample2) / n2

    var1 = sum((x - mean1) ** 2 for x in sample1) / (n1 - 1)
    var2 = sum((x - mean2) ** 2 for x in sample2) / (n2 - 1)

    vn1 = var1 / n1
    vn2 = var2 / n2
    se = math.sqrt(vn1 + vn2)

    if se == 0.0:
        return {
            "n1": n1,
            "n2": n2,
            "var1": var1,
            "var2": var2,
            "df": float("inf"),
            "t_statistic": 0.0,
            "p_value": 1.0,
        }

    t_stat = (mean1 - mean2) / se

    # Welch-Satterthwaite equation
    num = (vn1 + vn2) ** 2
    denom = ((vn1 ** 2) / (n1 - 1)) + ((vn2 ** 2) / (n2 - 1))
    df = num / denom if denom > 0 else 1.0

    p_val = student_t_pvalue(t_stat, df)

    return {
        "n1": n1,
        "n2": n2,
        "mean1": round(mean1, 4),
        "mean2": round(mean2, 4),
        "var1": round(var1, 4),
        "var2": round(var2, 4),
        "df": round(df, 4),
        "t_statistic": round(t_stat, 4),
        "p_value": p_val,
    }


def binomial_confidence_interval(
    k: int,
    n: int,
    method: str = "clopper_pearson",
    alpha: float = 0.05,
) -> Tuple[float, float]:
    """Compute exact or score binomial confidence intervals.

    Args:
        k: Number of successes
        n: Number of trials
        method: 'clopper_pearson' (exact) or 'wilson' (score)
        alpha: Significance level (default 0.05 for 95% CI)
    """
    if n <= 0:
        raise ValueError(f"Number of trials n must be positive, got {n}")
    if k < 0 or k > n:
        raise ValueError(f"Successes k={k} must satisfy 0 <= k <= n={n}")

    if method == "clopper_pearson":
        lower = 0.0 if k == 0 else beta_ppf(alpha / 2.0, k, n - k + 1)
        upper = 1.0 if k == n else beta_ppf(1.0 - alpha / 2.0, k + 1, n - k)
        return round(lower, 4), round(upper, 4)

    elif method == "wilson":
        # Wilson score interval
        p = k / n
        # z for two-sided alpha
        # For alpha=0.05, z=1.95996; for alpha=0.01, z=2.57583
        # Approximate standard normal quantile
        z = math.sqrt(2.0) * _erfcinv(alpha)
        denom = 1.0 + (z ** 2) / n
        center = (p + (z ** 2) / (2.0 * n)) / denom
        delta = (z * math.sqrt((p * (1.0 - p) / n) + ((z ** 2) / (4.0 * (n ** 2))))) / denom
        lower = max(0.0, center - delta)
        upper = min(1.0, center + delta)
        return round(lower, 4), round(upper, 4)

    else:
        raise ValueError(f"Unknown method '{method}'. Choose 'clopper_pearson' or 'wilson'.")


def _erfcinv(y: float) -> float:
    """Inverse complementary error function approximation for standard normal quantile."""
    # Approximation via Winitzki / Abramowitz & Stegun
    # For alpha=0.05 -> y=0.05 -> z = sqrt(2)*erfcinv(0.05) ~ 1.95996
    # Let's use high precision rational approximation for normal quantile
    # z = -qnorm(y/2)
    p = y / 2.0
    return _norm_ppf(1.0 - p) / math.sqrt(2.0)


def _norm_ppf(p: float) -> float:
    """Acklam's algorithm for inverse standard normal CDF."""
    if p <= 0.0 or p >= 1.0:
        raise ValueError("Probability p must be in (0, 1)")

    # Coefficients in rational approximations
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]

    q = min(p, 1.0 - p)
    if q > 0.02425:
        # Central region
        u = q - 0.5
        r = u * u
        z = u * (((((a[0]*r + a[1])*r + a[2])*r + a[3])*r + a[4])*r + a[5]) / \
            (((((b[0]*r + b[1])*r + b[2])*r + b[3])*r + b[4])*r + 1.0)
    else:
        # Tail region
        r = math.sqrt(-math.log(q if p < 0.5 else 1.0 - p))
        z = (((((c[0]*r + c[1])*r + c[2])*r + c[3])*r + c[4])*r + c[5]) / \
            ((((d[0]*r + d[1])*r + d[2])*r + d[3])*r + 1.0)
        if p < 0.5:
            z = -z

    if p > 0.5 and q > 0.02425:
        # adjust for upper central
        u = (1.0 - p) - 0.5
        r = u * u
        z = - (u * (((((a[0]*r + a[1])*r + a[2])*r + a[3])*r + a[4])*r + a[5]) / \
            (((((b[0]*r + b[1])*r + b[2])*r + b[3])*r + b[4])*r + 1.0))

    return z


# ============================================================================
# Bootstrap Resampling & Non-Inferiority
# ============================================================================

def hierarchical_bootstrap(
    control_metrics: List[float],
    treatment_metrics: List[float],
    n_resamples: int = 1000,
    seed: int = 42,
    alpha: float = 0.05,
    metric_type: str = "ratio",
) -> Dict[str, Union[float, Tuple[float, float], bool]]:
    """Perform cluster-level bootstrap resampling at the independent project template level.

    Args:
        control_metrics: Project-level metrics for control group
        treatment_metrics: Project-level metrics for treatment group
        n_resamples: Number of bootstrap iterations
        seed: Random seed for deterministic reproducibility
        alpha: Significance level for two-sided percentile interval
        metric_type: 'ratio' (mean(treatment)/mean(control)) or 'diff' (mean(treatment) - mean(control))

    Returns:
        Dict containing observed value, confidence interval, and small-sample warning.
    """
    n_c = len(control_metrics)
    n_t = len(treatment_metrics)

    if n_c == 0 or n_t == 0:
        raise ValueError("Cannot perform bootstrap on empty samples.")

    small_sample_warning = n_c < 10 or n_t < 10

    mean_c = sum(control_metrics) / n_c
    mean_t = sum(treatment_metrics) / n_t

    if metric_type == "ratio":
        observed = mean_t / mean_c if mean_c != 0 else float("nan")
    else:
        observed = mean_t - mean_c

    rng = random.Random(seed)
    bootstrap_distribution = []

    for _ in range(n_resamples):
        resample_c = [rng.choice(control_metrics) for _ in range(n_c)]
        resample_t = [rng.choice(treatment_metrics) for _ in range(n_t)]

        b_mean_c = sum(resample_c) / n_c
        b_mean_t = sum(resample_t) / n_t

        if metric_type == "ratio":
            if b_mean_c != 0:
                bootstrap_distribution.append(b_mean_t / b_mean_c)
        else:
            bootstrap_distribution.append(b_mean_t - b_mean_c)

    bootstrap_distribution.sort()
    n_boot = len(bootstrap_distribution)

    if n_boot == 0:
        return {
            "observed": observed,
            "ci_lower": float("nan"),
            "ci_upper": float("nan"),
            "small_sample_warning": small_sample_warning,
        }

    lower_idx = int((alpha / 2.0) * n_boot)
    upper_idx = int((1.0 - alpha / 2.0) * n_boot)
    upper_idx = min(upper_idx, n_boot - 1)

    ci_lower = bootstrap_distribution[lower_idx]
    ci_upper = bootstrap_distribution[upper_idx]

    return {
        "observed": round(observed, 4),
        "ci_lower": round(ci_lower, 4),
        "ci_upper": round(ci_upper, 4),
        "n_resamples": n_boot,
        "small_sample_warning": small_sample_warning,
    }


def evaluate_non_inferiority(
    k_treatment: int,
    n_treatment: int,
    k_control: int,
    n_control: int,
    margin: float,
    alpha: float = 0.05,
) -> Dict[str, Union[float, bool, str]]:
    """Evaluate non-inferiority of treatment relative to control on binary acceptance.

    H0: p_treatment - p_control <= -margin
    H1: p_treatment - p_control > -margin

    Args:
        k_treatment: Accepted projects in treatment
        n_treatment: Total projects in treatment
        k_control: Accepted projects in control
        n_control: Total projects in control
        margin: Pre-specified non-inferiority margin delta (must satisfy 0 < margin < 1)
        alpha: Significance level (default 0.05)
    """
    if margin <= 0.0 or margin >= 1.0:
        raise ValueError(f"Invalid non-inferiority margin: {margin}. Must be in (0, 1).")

    p_t = k_treatment / n_treatment
    p_c = k_control / n_control
    rate_difference = p_t - p_c

    # Check sample size adequacy
    if n_treatment < 30 or n_control < 30:
        power_warning = (
            f"Underpowered sample size (n_t={n_treatment}, n_c={n_control}). "
            f"Asymptotic normal tests for non-inferiority are invalid; exact bounds required."
        )
    else:
        power_warning = ""

    # Exact Clopper-Pearson lower bound for treatment
    t_lower, t_upper = binomial_confidence_interval(k_treatment, n_treatment, method="clopper_pearson", alpha=alpha)
    c_lower, c_upper = binomial_confidence_interval(k_control, n_control, method="clopper_pearson", alpha=alpha)

    # Conservative lower bound on difference: t_lower - c_upper
    diff_lower_bound = t_lower - c_upper
    non_inferior = diff_lower_bound > -margin

    return {
        "p_treatment": round(p_t, 4),
        "p_control": round(p_c, 4),
        "rate_difference": round(rate_difference, 4),
        "margin": margin,
        "diff_conservative_lower_bound": round(diff_lower_bound, 4),
        "non_inferior": non_inferior,
        "power_warning": power_warning,
    }
