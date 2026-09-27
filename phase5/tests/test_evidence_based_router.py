"""Tests for Evidence-Based Bounded Router."""
import pytest
from autonomous_engineering.router.evidence_router import (
    EvidenceBasedRouter,
    RoutingTopology,
    RoutingDecisionRecord,
)


def test_router_author_assignment():
    router = EvidenceBasedRouter()
    decision = router.route_assignment(
        assignment_id="asgn-101",
        task_id="task-defect-01",
        task_class="defect_repair",
        required_role="author",
    )
    assert decision.selected_candidate_id == "control-qwen3-coder-30b-awq"
    assert decision.selected_topology == RoutingTopology.HOMOGENEOUS
    assert len(decision.decision_hash) == 64
    assert len(router.decision_history) == 1


def test_router_specialist_reviewer_available():
    router = EvidenceBasedRouter()
    state = {"phi4_specialist_available": True}
    decision = router.route_assignment(
        assignment_id="asgn-102",
        task_id="task-multi-01",
        task_class="multi_file",
        required_role="reviewer",
        resource_state=state,
    )
    assert decision.selected_candidate_id == "cand-phi4-fp8"
    assert decision.selected_topology == RoutingTopology.HETEROGENEOUS
    assert "Phi-4 specialist reviewer" in decision.rationale


def test_router_specialist_unavailable_fallback():
    router = EvidenceBasedRouter()
    # When Phi-4 endpoint is occupied or unavailable
    state = {"phi4_specialist_available": False}
    decision = router.route_assignment(
        assignment_id="asgn-103",
        task_id="task-maintain-01",
        task_class="maintainability",
        required_role="reviewer",
        resource_state=state,
    )
    assert decision.selected_candidate_id == "control-qwen3-coder-30b-awq"
    assert decision.selected_topology == RoutingTopology.HOMOGENEOUS
    assert "falling back to homogeneous" in decision.rationale


def test_router_single_worker_bypass():
    router = EvidenceBasedRouter()
    decision = router.route_assignment(
        assignment_id="asgn-104",
        task_id="task-simple-01",
        task_class="defect_repair",
        required_role="reviewer",
        force_topology=RoutingTopology.SINGLE_WORKER,
    )
    assert decision.selected_topology == RoutingTopology.SINGLE_WORKER
    assert decision.selected_candidate_id == "none"
