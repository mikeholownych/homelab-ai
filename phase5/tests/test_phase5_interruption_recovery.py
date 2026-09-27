"""Tests for Session Detachment, Durable Recovery, and Stale Worker Fencing."""
import tempfile
from pathlib import Path
import pytest

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.core.types import WorkOrderState, TaskStepState, ArtifactType
from autonomous_engineering.planning.models import ExecutionPlan, TaskStepDefinition
from autonomous_engineering.workflow.engine import WorkflowEngine, WorkflowEngineError
from autonomous_engineering.work_order.compiler import WorkOrderCompiler


@pytest.fixture
def recovery_env():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "durable_service.sqlite"
        store_path = tmp_path / "artifacts"
        engine = WorkflowEngine(db_path)
        store = ArtifactStore(store_path)
        yield {
            "engine": engine,
            "store": store,
            "db_path": db_path,
            "tmp_path": tmp_path,
        }


def test_session_detachment_persistence(recovery_env):
    engine = recovery_env["engine"]
    db_path = recovery_env["db_path"]

    # 1. Interface submits work order
    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Perform decoupled refactoring",
        source_channel="cli",
        source_reference="sess-1",
        repository_id="repo-durable",
        baseline_commit="commit-1",
        proposed_mutation_paths=["src/"],
    )
    engine.register_work_order(wo)

    # 2. Interface detaches (simulated by closing and re-opening database connection)
    del engine
    reconnected_engine = WorkflowEngine(db_path)

    # 3. Work order state is durably preserved
    retrieved = reconnected_engine.get_work_order(wo.work_order_id, wo.version)
    assert retrieved is not None
    assert retrieved["work_order_id"] == wo.work_order_id
    assert retrieved["version"] == wo.version
    assert retrieved["state"] == str(WorkOrderState.DRAFT)


def test_stale_worker_fencing_rejection(recovery_env):
    engine = recovery_env["engine"]
    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Task for fencing test",
        source_channel="cli",
        source_reference="sess-2",
        repository_id="repo-fence",
        baseline_commit="commit-2",
        proposed_mutation_paths=["src/"],
    )
    engine.register_work_order(wo)

    plan = ExecutionPlan(
        plan_id=f"plan-{wo.work_order_id}",
        work_order_id=wo.work_order_id,
        work_order_version=wo.version,
        steps=(
            TaskStepDefinition(
                step_id="step-1",
                required_role="defect_patch",
                description="Patch",
                target_paths=("src/**",),
                dependencies=(),
                output_artifact_type=ArtifactType.PATCH,
            ),
        ),
    )
    asgn_id = engine.initialize_plan(plan)[0]
    token = engine.acquire_lease(asgn_id, "worker-old", lease_seconds=1)

    # Simulate revision superseding the work order
    engine.supersede_work_order(wo.work_order_id, wo.version)

    # Stale worker tries to commit output to superseded work order
    with pytest.raises(WorkflowEngineError, match="superseded"):
        engine.complete_assignment(asgn_id, token, output_artifact_hash="hash_patch_123")


def test_cancellation_revocation(recovery_env):
    engine = recovery_env["engine"]
    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Task for cancellation test",
        source_channel="cli",
        source_reference="sess-3",
        repository_id="repo-cancel",
        baseline_commit="commit-3",
        proposed_mutation_paths=["src/"],
    )
    engine.register_work_order(wo)

    plan = ExecutionPlan(
        plan_id=f"plan-{wo.work_order_id}",
        work_order_id=wo.work_order_id,
        work_order_version=wo.version,
        steps=(
            TaskStepDefinition(
                step_id="step-1",
                required_role="defect_patch",
                description="Patch",
                target_paths=("src/**",),
                dependencies=(),
                output_artifact_type=ArtifactType.PATCH,
            ),
        ),
    )
    asgn_id = engine.initialize_plan(plan)[0]
    token = engine.acquire_lease(asgn_id, "worker-b65-0", lease_seconds=60)

    # Cancel work order
    engine.cancel_work_order(wo.work_order_id, wo.version, reason="User requested cancellation")

    # Worker attempts to commit after cancellation
    with pytest.raises(WorkflowEngineError, match="revoked|cancelled"):
        engine.complete_assignment(asgn_id, token, output_artifact_hash="hash_patch_456")
