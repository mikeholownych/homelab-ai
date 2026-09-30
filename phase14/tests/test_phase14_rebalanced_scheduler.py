"""Deterministic unit and safety tests for Phase 14 RebalancedScheduler."""

import pytest

from autonomous_engineering.heterogeneous.capability_scheduler import (
    AuthorityEscalationError,
    WorkerState,
    WorkerStatus,
)
from autonomous_engineering.heterogeneous.specialist_contracts import TaskClass
from autonomous_engineering.pipeline_rebalancing.rebalanced_scheduler import (
    ExtendedSchedulingMode,
    RebalancedScheduler,
)


@pytest.fixture
def dual_30b_workers():
    w1 = WorkerState(
        worker_id="worker_1",
        model_name="cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
        revision="AWQ-4bit",
        port=18000,
        gpu_id=0,
    )
    w2 = WorkerState(
        worker_id="worker_2",
        model_name="cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
        revision="AWQ-4bit",
        port=8001,
        gpu_id=1,
    )
    return w1, w2


def test_default_mode_is_configuration_b(dual_30b_workers):
    w1, w2 = dual_30b_workers
    sched = RebalancedScheduler(w1, w2)
    assert sched.extended_mode == ExtendedSchedulingMode.CONFIGURATION_B


def test_authenticated_mode_switch(dual_30b_workers):
    w1, w2 = dual_30b_workers
    sched = RebalancedScheduler(w1, w2)
    valid_token = "QVF-MUMrVzpjD7eyzZVveAEN06U4r3_jg2AFIeEoPkM"

    # Reject unauthorized switch
    with pytest.raises(PermissionError):
        sched.set_experimental_mode(ExtendedSchedulingMode.CONFIGURATION_B_PLUS, token="BAD_TOKEN")

    # Accept authorized switch
    sched.set_experimental_mode(ExtendedSchedulingMode.CONFIGURATION_B_PLUS, token=valid_token)
    assert sched.extended_mode == ExtendedSchedulingMode.CONFIGURATION_B_PLUS


def test_item_01_placement_under_config_b_vs_b_plus(dual_30b_workers):
    w1, w2 = dual_30b_workers
    sched = RebalancedScheduler(w1, w2)
    valid_token = "QVF-MUMrVzpjD7eyzZVveAEN06U4r3_jg2AFIeEoPkM"

    # Under Config B: Item 01 routes to Worker 1
    res_b = sched.route_task("PROJ-01-01", TaskClass.ARCHITECTURAL_PLANNING, 512, [])
    assert res_b.assigned_worker == "worker_1"

    # Under Config B+: Item 01 routes to Worker 2
    sched.set_experimental_mode(ExtendedSchedulingMode.CONFIGURATION_B_PLUS, token=valid_token)
    res_b_plus = sched.route_task("PROJ-01-01", TaskClass.ARCHITECTURAL_PLANNING, 512, [])
    assert res_b_plus.assigned_worker == "worker_2"
    assert res_b_plus.routed_as_specialist is True

    # Items 02 and 03 still route to Worker 1 under Config B+
    res_02 = sched.route_task("PROJ-01-02", TaskClass.ARCHITECTURAL_PLANNING, 512, [])
    assert res_02.assigned_worker == "worker_1"
    res_03 = sched.route_task("PROJ-01-03", TaskClass.MULTI_FILE_IMPLEMENTATION, 768, [])
    assert res_03.assigned_worker == "worker_1"


def test_stage2_placement_under_config_b_plus(dual_30b_workers):
    w1, w2 = dual_30b_workers
    sched = RebalancedScheduler(w1, w2)
    valid_token = "QVF-MUMrVzpjD7eyzZVveAEN06U4r3_jg2AFIeEoPkM"
    sched.set_experimental_mode(ExtendedSchedulingMode.CONFIGURATION_B_PLUS, token=valid_token)

    # Stage 2 Items 04, 05 route to Worker 2
    res_04 = sched.route_task("PROJ-01-04", TaskClass.TEST_GENERATION, 512, [])
    assert res_04.assigned_worker == "worker_2"
    res_05 = sched.route_task("PROJ-01-05", TaskClass.STRUCTURED_OUTPUT, 512, [])
    assert res_05.assigned_worker == "worker_2"

    # Item 06 routes to Worker 1
    res_06 = sched.route_task("PROJ-01-06", TaskClass.SECURITY_REVIEW, 512, [])
    assert res_06.assigned_worker == "worker_1"


def test_authority_escalation_blocked(dual_30b_workers):
    w1, w2 = dual_30b_workers
    sched = RebalancedScheduler(w1, w2)
    valid_token = "QVF-MUMrVzpjD7eyzZVveAEN06U4r3_jg2AFIeEoPkM"
    sched.set_experimental_mode(ExtendedSchedulingMode.CONFIGURATION_B_PLUS, token=valid_token)

    # Worker 2 attempting MULTI_FILE_IMPLEMENTATION or PROJECT_INTEGRATION raises AuthorityEscalationError
    with pytest.raises(AuthorityEscalationError):
        sched.validate_worker_authority("worker_2", TaskClass.MULTI_FILE_IMPLEMENTATION, task_id="PROJ-01-03")

    with pytest.raises(AuthorityEscalationError):
        sched.validate_worker_authority("worker_2", TaskClass.PROJECT_INTEGRATION, task_id="PROJ-01-07")


def test_fail_closed_rollback_to_config_b(dual_30b_workers):
    w1, w2 = dual_30b_workers
    sched = RebalancedScheduler(w1, w2)
    valid_token = "QVF-MUMrVzpjD7eyzZVveAEN06U4r3_jg2AFIeEoPkM"
    sched.set_experimental_mode(ExtendedSchedulingMode.CONFIGURATION_B_PLUS, token=valid_token)
    assert sched.extended_mode == ExtendedSchedulingMode.CONFIGURATION_B_PLUS

    # Trigger rollback
    sched.rollback_to_configuration_b()
    assert sched.extended_mode == ExtendedSchedulingMode.CONFIGURATION_B

    # Item 01 routes back to Worker 1
    res = sched.route_task("PROJ-01-01", TaskClass.ARCHITECTURAL_PLANNING, 512, [])
    assert res.assigned_worker == "worker_1"
