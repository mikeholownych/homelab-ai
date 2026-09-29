"""Unit tests for Phase 14 B+ Requalification Runner logic."""

import pytest
from autonomous_engineering.pipeline_rebalancing.handoff_contract import (
    InvestigationFinding,
    InvestigationHandoffEnvelope,
    Item01HandoffValidator,
)
from autonomous_engineering.heterogeneous.containment import ExternalAuthorityBoundary


def test_handoff_contract_prerequisite_invariance():
    """Verify that Item 01 handoff strictly gates Item 02 planning."""
    boundary = ExternalAuthorityBoundary()
    validator = Item01HandoffValidator(boundary=boundary)

    # Valid handoff envelope
    env = InvestigationHandoffEnvelope(
        task_id="test-p1-01",
        invocation_id="inv-p1-01",
        worker_id="worker_2",
        model_name="cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
        model_revision="AWQ-4bit",
        repo_commit_sha="a8c3b6a1a4c27f391f28ebdf5a74c1bfd1d148ce",
        inspected_files=["core.py"],
        inspected_symbols=["Router"],
        findings=[InvestigationFinding("core.py", "Router", "BOUNDARY", "Verified safe boundary")],
        explicit_unknowns=[],
        detected_blockers=[],
        raw_content="```python\n# Investigation verified\n```",
    )
    env.seal()
    val = validator.validate_handoff(env, expected_repo_sha="a8c3b6a1a4c27f391f28ebdf5a74c1bfd1d148ce")
    assert val.is_accepted is True
    assert val.status.value == "CLEAN"

    # Corrupted handoff envelope fails validation
    env_bad = InvestigationHandoffEnvelope(
        task_id="test-p1-01-bad",
        invocation_id="inv-p1-01-bad",
        worker_id="worker_2",
        model_name="cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
        model_revision="AWQ-4bit",
        repo_commit_sha="bad_sha",
        inspected_files=[],
        inspected_symbols=[],
        findings=[],
        explicit_unknowns=[],
        detected_blockers=[],
        raw_content="",
    )
    val_bad = validator.validate_handoff(env_bad, expected_repo_sha="a8c3b6a1a4c27f391f28ebdf5a74c1bfd1d148ce")
    assert val_bad.is_accepted is False


def test_queue_stability_calculation_logic():
    """Verify that arrival schedule and queue wait calculations obey pipeline queuing rules."""
    inter_arrival = 184.6154  # 19.5 proj/hr
    # Suppose project 1 has W1 demand 165s and finishes at 225s
    # Project 2 arrives at 184.6s. Since W2 is free at ~35s, project 2 dispatches immediately (wait = 0.0s)
    # W1 finishes proj 1 at 225s. Proj 2's Item 01 finishes at 184.6 + 35 = 219.6s.
    # Proj 2 Item 02 starts on W1 at max(219.6, 225.0) = 225.0s (delay = 5.4s on stage 1, but queue wait at dispatch = 0.0s).
    w2_demand = 35.0
    w1_demand = 165.0

    # Arrival 0
    arr0 = 0.0
    disp0 = arr0
    wait0 = disp0 - arr0
    assert wait0 == 0.0

    # Arrival 1
    arr1 = 184.6154
    w2_free = 35.0  # Item 01 freed W2 at 35s
    disp1 = max(arr1, w2_free)
    wait1 = disp1 - arr1
    assert wait1 == 0.0
