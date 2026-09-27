"""Tests for Work-Order Revisions, Scope Restriction, and Cancellation on Real Repositories."""
import tempfile
from pathlib import Path
import pytest

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.authority.admission import AdmissionEvaluator
from autonomous_engineering.core.types import (
    ArtifactType,
    RevisionKind,
    TaskStepState,
    WorkOrderState,
)
from autonomous_engineering.planning.models import ExecutionPlan, TaskStepDefinition
from autonomous_engineering.workflow.engine import WorkflowEngine, WorkflowEngineError
from autonomous_engineering.work_order.compiler import WorkOrderCompiler
from autonomous_engineering.work_order.versioning import WorkOrderRevisionManager


@pytest.fixture
def revision_env():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "revision.sqlite"
        art_path = tmp_path / "artifacts"

        engine = WorkflowEngine(db_path)
        store = ArtifactStore(art_path)
        compiler = WorkOrderCompiler()

        yield {
            "engine": engine,
            "store": store,
            "compiler": compiler,
        }


def test_work_order_scope_restriction_supersedes_active_leases(revision_env):
    engine = revision_env["engine"]
    compiler = revision_env["compiler"]

    wo_v1 = compiler.compile(
        raw_text="Initial intent: allow mutating entire src and tests",
        source_channel="cli",
        source_reference="sess-rev-1",
        repository_id="aihost-repo",
        baseline_commit="commit-1",
        proposed_mutation_paths=["src/server.py", "tests/test_server.py"],
    )
    engine.register_work_order(wo_v1)

    plan = ExecutionPlan(
        plan_id=f"plan-{wo_v1.work_order_id}-v1",
        work_order_id=wo_v1.work_order_id,
        work_order_version=1,
        steps=(
            TaskStepDefinition(
                step_id="step-1",
                required_role="defect_patch",
                description="Patch server.py",
                target_paths=("src/server.py",),
                dependencies=(),
                output_artifact_type=ArtifactType.PATCH,
            ),
        ),
    )
    asgn_id = engine.initialize_plan(plan)[0]
    token_v1 = engine.acquire_lease(asgn_id, "worker-1", lease_seconds=60)

    # Human restricts scope to server.py only
    wo_v2 = WorkOrderRevisionManager.create_revision(
        current_wo=wo_v1,
        change_reason="Restricting mutation exclusively to server.py",
        author="human_supervisor",
        revision_kind=RevisionKind.SCOPE_RESTRICTION,
        new_instruction_text="Restricted intent",
        updated_paths=["src/server.py"],
    )
    assert wo_v2.version == 2
    assert wo_v2.authorization.authorized_mutation_paths == ("src/server.py",)

    # Invalidate v1 in engine
    engine.supersede_work_order(wo_v1.work_order_id, wo_v1.version)

    # Stale worker tries to commit using v1 token
    with pytest.raises(WorkflowEngineError, match="superseded"):
        engine.complete_assignment(asgn_id, token_v1, output_artifact_hash="hash_patch_v1")


def test_work_order_cancellation_revocation(revision_env):
    engine = revision_env["engine"]
    compiler = revision_env["compiler"]

    wo = compiler.compile(
        raw_text="Task to be cancelled",
        source_channel="cli",
        source_reference="sess-cancel-1",
        repository_id="aihost-repo",
        baseline_commit="commit-1",
        proposed_mutation_paths=["src/server.py"],
    )
    engine.register_work_order(wo)

    plan = ExecutionPlan(
        plan_id=f"plan-{wo.work_order_id}-v1",
        work_order_id=wo.work_order_id,
        work_order_version=1,
        steps=(
            TaskStepDefinition(
                step_id="step-1",
                required_role="defect_patch",
                description="Patch",
                target_paths=("src/server.py",),
                dependencies=(),
                output_artifact_type=ArtifactType.PATCH,
            ),
        ),
    )
    asgn_id = engine.initialize_plan(plan)[0]
    token = engine.acquire_lease(asgn_id, "worker-b65-0", lease_seconds=60)

    # Cancel work order
    engine.cancel_work_order(wo.work_order_id, wo.version, reason="Human operator cancelled task")

    # Stale worker attempts commit after revocation
    with pytest.raises(WorkflowEngineError, match="revoked|cancelled"):
        engine.complete_assignment(asgn_id, token, output_artifact_hash="hash_patch_cancelled")
