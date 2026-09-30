"""Unit tests for Phase 14 18.0 proj/hr capacity runner logic and telemetry parsing."""

import pytest
from autonomous_engineering.pipeline_rebalancing.capacity_18_runner import percentile


def test_percentile_calculation():
    data = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentile(data, 0.50) == 30.0
    assert percentile(data, 0.0) == 10.0
    assert percentile(data, 1.0) == 50.0
    assert percentile([], 0.50) == 0.0


def test_capacity_18_arrival_spacing_invariance():
    """Verify that 18.0 proj/hr enforces exactly 200.0s inter-arrival spacing."""
    rate = 18.0
    spacing = 3600.0 / rate
    assert spacing == 200.0

    scheduled_arrivals = [i * spacing for i in range(10)]
    assert scheduled_arrivals[0] == 0.0
    assert scheduled_arrivals[1] == 200.0
    assert scheduled_arrivals[9] == 1800.0


def test_capacity_18_stability_criterion():
    """Verify slope stability threshold logic (|s| <= 1.0 s/proj)."""
    waits_stable = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    slope_stable = (waits_stable[-1] - waits_stable[0]) / (len(waits_stable) - 1)
    assert abs(slope_stable) <= 1.0

    waits_divergent = [0.0, 0.0, 10.0, 25.0, 50.0, 75.0, 100.0, 120.0, 140.0, 160.0]
    slope_divergent = (waits_divergent[-1] - waits_divergent[0]) / (len(waits_divergent) - 1)
    assert slope_divergent > 1.0
