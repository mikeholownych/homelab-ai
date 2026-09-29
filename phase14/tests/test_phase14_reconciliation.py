"""Unit tests for Phase 14 Configuration B+ Reconciliation and Throughput Deconstruction."""

import json
import os
import pytest


def test_throughput_deconstruction_accounting():
    """Verify separate calculation of arrival, completion, and drain throughputs."""
    results_path = "phase14/evidence/phase14_capacity_18_results.json"
    assert os.path.exists(results_path), f"Missing {results_path}"

    with open(results_path) as f:
        data = json.load(f)

    projects = data["projects"]
    assert len(projects) == 10

    # 1. Offered arrival rate
    inter_arrival = data["inter_arrival_spacing_sec"]
    assert inter_arrival == 200.0
    offered_rate = 3600.0 / inter_arrival
    assert offered_rate == 18.0

    # 2. Completions during arrival window (t <= 1800.0s)
    arr_window_end = 9 * inter_arrival  # 1800.0s
    completions_in_window = [p for p in projects if p["completion_time_sec"] <= arr_window_end]
    assert len(completions_in_window) == 8
    arrival_window_rate = (len(completions_in_window) / arr_window_end) * 3600.0
    assert arrival_window_rate == 16.0

    # 3. Active completion window rate (first completion to last completion)
    first_comp = projects[0]["completion_time_sec"]
    last_comp = projects[-1]["completion_time_sec"]
    comp_window = last_comp - first_comp
    assert round(comp_window, 2) == 1817.31
    completion_window_rate = (9 / comp_window) * 3600.0
    assert round(completion_window_rate, 4) == 17.8285

    # 4. Drain-inclusive batch throughput
    total_campaign_span = last_comp - projects[0]["arrival_time_sec"]
    assert round(total_campaign_span, 2) == 2044.94
    drain_inclusive_throughput = (10 / total_campaign_span) * 3600.0
    assert round(drain_inclusive_throughput, 4) == 17.6044


def test_queue_stability_and_zero_wait():
    """Verify that every project experienced exactly 0.00s queue wait."""
    results_path = "phase14/evidence/phase14_capacity_18_results.json"
    with open(results_path) as f:
        data = json.load(f)

    waits = [p["queue_wait_seconds"] for p in data["projects"]]
    assert all(w == 0.0 for w in waits)

    slope = (waits[-1] - waits[0]) / (len(waits) - 1)
    assert slope == 0.0


def test_independent_4_gate_acceptance():
    """Verify that all 10 projects independently satisfied all 4 quality gates."""
    results_path = "phase14/evidence/phase14_capacity_18_results.json"
    with open(results_path) as f:
        data = json.load(f)

    for p in data["projects"]:
        assert p["accepted"] is True
        gates = p["gates"]
        assert gates["gate1_syntax"] is True
        assert gates["gate2_tests"] is True
        assert gates["gate3_security"] is True
        assert gates["gate4_schema"] is True
        assert p["handoff_receipt"]["is_accepted"] is True
        assert p["handoff_receipt"]["status"] == "CLEAN"
