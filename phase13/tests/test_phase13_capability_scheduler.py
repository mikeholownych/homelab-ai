"""Unit tests for Capability-Aware Heterogeneous Scheduler (Phase 13 Workstream D)."""

import pytest
from autonomous_engineering.heterogeneous.capability_scheduler import (
    CapabilityAwareScheduler,
    WorkerState,
    WorkerStatus,
)
from autonomous_engineering.heterogeneous.specialist_contracts import TaskClass


@pytest.fixture
def hetero_scheduler():
    w1 = WorkerState(
        worker_id="b0-live-tp1-worker1",
        model_name="cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
        revision="4bd30395b72ea6045edd04806c4fea448d4467b3",
        port=8000,
        gpu_id=0,
        status=WorkerStatus.HEALTHY,
    )
    w2 = WorkerState(
        worker_id="b0-live-tp1-worker2",
        model_name="Qwen/Qwen2.5-7B-Instruct-AWQ",
        revision="b25037543e9394b818fdfca67ab2a00ecc7dd641",
        port=8001,
        gpu_id=1,
        status=WorkerStatus.HEALTHY,
    )
    return CapabilityAwareScheduler(worker1=w1, worker2=w2)


@pytest.fixture
def baseline_scheduler():
    w1 = WorkerState(
        worker_id="b0-live-tp1-worker1",
        model_name="cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
        revision="4bd30395b72ea6045edd04806c4fea448d4467b3",
        port=8000,
        gpu_id=0,
        status=WorkerStatus.HEALTHY,
    )
    w2 = WorkerState(
        worker_id="b0-live-tp1-worker2",
        model_name="cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
        revision="4bd30395b72ea6045edd04806c4fea448d4467b3",
        port=8001,
        gpu_id=1,
        status=WorkerStatus.HEALTHY,
    )
    return CapabilityAwareScheduler(worker1=w1, worker2=w2)


def test_specialist_routing_success(hetero_scheduler):
    res = hetero_scheduler.route_task(
        task_id="TASK-T1",
        task_class=TaskClass.TEST_GENERATION,
        context_token_count=2048,
        requested_tools=["run_pytest"],
    )
    assert res.assigned_worker == "b0-live-tp1-worker2"
    assert res.assigned_model == "Qwen/Qwen2.5-7B-Instruct-AWQ"
    assert res.routed_as_specialist is True
    assert res.fallback_triggered is False


def test_lead_task_routes_to_worker1(hetero_scheduler):
    res = hetero_scheduler.route_task(
        task_id="TASK-A1",
        task_class=TaskClass.ARCHITECTURAL_PLANNING,
        context_token_count=15000,
        requested_tools=["read_file"],
    )
    assert res.assigned_worker == "b0-live-tp1-worker1"
    assert res.assigned_model == "cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit"
    assert res.routed_as_specialist is False


def test_specialist_context_overflow_fallback(hetero_scheduler):
    res = hetero_scheduler.route_task(
        task_id="TASK-T2",
        task_class=TaskClass.TEST_GENERATION,
        context_token_count=35000,  # Exceeds 32K specialist cap
        requested_tools=["run_pytest"],
    )
    # Should automatically divert to Worker 1
    assert res.assigned_worker == "b0-live-tp1-worker1"
    assert res.assigned_model == "cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit"
    assert res.routed_as_specialist is False


def test_unhealthy_specialist_fallback(hetero_scheduler):
    hetero_scheduler.worker2.status = WorkerStatus.UNHEALTHY
    res = hetero_scheduler.route_task(
        task_id="TASK-T3",
        task_class=TaskClass.TEST_GENERATION,
        context_token_count=2048,
        requested_tools=["run_pytest"],
    )
    assert res.assigned_worker == "b0-live-tp1-worker1"
    assert res.fallback_triggered is True
    assert "unhealthy" in res.fallback_reason.lower()


def test_specialist_validation_failure_escalation(hetero_scheduler):
    res = hetero_scheduler.handle_specialist_validation_failure(
        task_id="TASK-T4",
        failure_message="SyntaxError on line 12",
    )
    assert res.assigned_worker == "b0-live-tp1-worker1"
    assert res.fallback_triggered is True
    assert any("SPECIALIST_EXECUTION_FAILED" in p for p in res.provenance_chain)


def test_baseline_dual_30b_routing(baseline_scheduler):
    # In baseline, even if a test task arrives, Worker 2 has 30B, so it routes as lead
    res = baseline_scheduler.route_task(
        task_id="TASK-T5",
        task_class=TaskClass.TEST_GENERATION,
        context_token_count=2048,
        requested_tools=["run_pytest"],
    )
    assert res.routed_as_specialist is False
    assert res.assigned_model == "cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit"
