"""Integration tests for Phase 14 RebalancedEngineeringPipeline."""

import pytest

from autonomous_engineering.heterogeneous.capability_scheduler import WorkerState
from autonomous_engineering.heterogeneous.production_pipeline import (
    PipelineStage,
    ProductionProjectPlan,
    ProductionWorkItem,
)
from autonomous_engineering.heterogeneous.specialist_contracts import TaskClass
from autonomous_engineering.pipeline_rebalancing.rebalanced_pipeline import (
    RebalancedEngineeringPipeline,
)
from autonomous_engineering.pipeline_rebalancing.rebalanced_scheduler import (
    ExtendedSchedulingMode,
    RebalancedScheduler,
)


@pytest.fixture
def rebalanced_env():
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
    sched = RebalancedScheduler(w1, w2)
    pipeline = RebalancedEngineeringPipeline(scheduler=sched)
    return sched, pipeline


@pytest.fixture
def sample_project():
    items = [
        ProductionWorkItem(
            work_id="TEST-01-01",
            title="Architecture Investigation",
            task_class=TaskClass.ARCHITECTURAL_PLANNING,
            stage=PipelineStage.STAGE_1_PLANNING,
            prompt="Analyze repository architecture and components.",
        ),
        ProductionWorkItem(
            work_id="TEST-01-02",
            title="Execution DAG Plan",
            task_class=TaskClass.ARCHITECTURAL_PLANNING,
            stage=PipelineStage.STAGE_1_PLANNING,
            prompt="Define execution DAG and rollback plan.",
            predecessors=["TEST-01-01"],
        ),
        ProductionWorkItem(
            work_id="TEST-01-03",
            title="Core Engine Implementation",
            task_class=TaskClass.MULTI_FILE_IMPLEMENTATION,
            stage=PipelineStage.STAGE_1_PLANNING,
            prompt="Implement core engine.",
            predecessors=["TEST-01-02"],
        ),
        ProductionWorkItem(
            work_id="TEST-01-04",
            title="Unit Tests",
            task_class=TaskClass.TEST_GENERATION,
            stage=PipelineStage.STAGE_2_CONCURRENT,
            prompt="Generate pytest unit tests.",
            predecessors=["TEST-01-03"],
        ),
        ProductionWorkItem(
            work_id="TEST-01-05",
            title="OpenAPI Schema",
            task_class=TaskClass.STRUCTURED_OUTPUT,
            stage=PipelineStage.STAGE_2_CONCURRENT,
            prompt="Generate OpenAPI schema contract.",
            predecessors=["TEST-01-03"],
        ),
        ProductionWorkItem(
            work_id="TEST-01-06",
            title="Security Review",
            task_class=TaskClass.SECURITY_REVIEW,
            stage=PipelineStage.STAGE_2_CONCURRENT,
            prompt="Review SAST findings.",
            predecessors=["TEST-01-03"],
        ),
        ProductionWorkItem(
            work_id="TEST-01-07",
            title="Project Integration",
            task_class=TaskClass.PROJECT_INTEGRATION,
            stage=PipelineStage.STAGE_3_INTEGRATION,
            prompt="Integrate components.",
            predecessors=["TEST-01-04", "TEST-01-05", "TEST-01-06"],
        ),
        ProductionWorkItem(
            work_id="TEST-01-08",
            title="Acceptance Signoff",
            task_class=TaskClass.ARCHITECTURAL_PLANNING,
            stage=PipelineStage.STAGE_3_INTEGRATION,
            prompt="Perform final acceptance verification.",
            predecessors=["TEST-01-07"],
        ),
    ]
    return ProductionProjectPlan(
        project_id="PROJ-TEST-01",
        name="Test API Refactor",
        archetype="API Refactoring",
        work_items=items,
    )


def test_pipeline_execution_under_config_b(rebalanced_env, sample_project):
    sched, pipeline = rebalanced_env
    assert sched.extended_mode == ExtendedSchedulingMode.CONFIGURATION_B

    res = pipeline.execute_project(sample_project)
    assert res["status"] == "ACCEPTED"
    assert res["scheduling_mode"] == "CONFIGURATION_B"
    # Under Config B: Item 01 runs on Worker 1
    assert res["item_results"]["TEST-01-01"]["assigned_worker"] == "worker_1"
    assert res["acceptance_gates"]["gate1_syntax_ast"] is True
    assert res["acceptance_gates"]["gate2_test_execution"] is True
    assert res["acceptance_gates"]["gate3_security_review"] is True
    assert res["acceptance_gates"]["gate4_lead_integration"] is True


def test_pipeline_execution_under_config_b_plus(rebalanced_env, sample_project):
    sched, pipeline = rebalanced_env
    token = "QVF-MUMrVzpjD7eyzZVveAEN06U4r3_jg2AFIeEoPkM"
    sched.set_experimental_mode(ExtendedSchedulingMode.CONFIGURATION_B_PLUS, token=token)

    res = pipeline.execute_project(sample_project)
    assert res["status"] == "ACCEPTED"
    assert res["scheduling_mode"] == "CONFIGURATION_B_PLUS"
    # Under Config B+: Item 01 runs on Worker 2
    assert res["item_results"]["TEST-01-01"]["assigned_worker"] == "worker_2"
    # Items 02 and 03 run on Worker 1
    assert res["item_results"]["TEST-01-02"]["assigned_worker"] == "worker_1"
    assert res["item_results"]["TEST-01-03"]["assigned_worker"] == "worker_1"
    # Handoff receipt verified
    assert res["handoff_receipt"] is not None
    assert res["handoff_receipt"]["task_id"] == "TEST-01-01"
    assert res["handoff_receipt"]["is_accepted"] is True
    assert res["acceptance_gates"]["gate4_lead_integration"] is True


def test_pipeline_critical_path_demand_reduction(rebalanced_env, sample_project):
    sched, pipeline = rebalanced_env
    token = "QVF-MUMrVzpjD7eyzZVveAEN06U4r3_jg2AFIeEoPkM"

    # Run Config B
    sched.set_experimental_mode(ExtendedSchedulingMode.CONFIGURATION_B, token=token)
    res_b = pipeline.execute_project(sample_project)

    # Run Config B+
    sched.set_experimental_mode(ExtendedSchedulingMode.CONFIGURATION_B_PLUS, token=token)
    res_b_plus = pipeline.execute_project(sample_project)

    # Worker 1 service demand must be strictly less under Config B+ than Config B
    w1_demand_b = res_b["w1_active_demand_sec"]
    w1_demand_b_plus = res_b_plus["w1_active_demand_sec"]
    assert w1_demand_b_plus < w1_demand_b
    assert res_b_plus["w2_active_demand_sec"] > res_b["w2_active_demand_sec"]
