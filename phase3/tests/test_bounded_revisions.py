"""Tests for Bounded Work-Order Revision, Invalidation, and Stale Worker Fencing."""
from pathlib import Path
import pytest
import tempfile

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.core.types import (
    ArtifactType,
    FailureClass,
    RevisionKind,
    TaskStepState,
    WorkOrderState,
)
from autonomous_engineering.interface.adapter import HumanInterfaceAdapter
from autonomous_engineering.workflow.engine import WorkflowEngine, WorkflowEngineError
from autonomous_engineering.work_order.compiler import WorkOrderCompiler
from autonomous_engineering.work_order.models import AcceptanceCriterion
from autonomous_engineering.work_order.versioning import WorkOrderRevisionManager


@pytest.fixture
def env():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "test_engine.sqlite"
        art_path = tmp_path / "artifacts"
        engine = WorkflowEngine(db_path)
        store = ArtifactStore(art_path)
        adapter = HumanInterfaceAdapter(engine, store)
        yield {
            "tmp_path": tmp_path,
            "engine": engine,
            "store": store,
            "adapter": adapter,
        }


def test_revision_classification_invalidation():
    compiler = WorkOrderCompiler()
    base_wo = compiler.compile(
        raw_text="Base prompt",
        source_channel="cli",
        source_reference="ref-1",
        repository_id="homelab-ai",
        baseline_commit="8b25d26",
        proposed_mutation_paths=["src/stats_utils.py"],
        acceptance_criteria=[
            AcceptanceCriterion("c1", "test", "pytest", "tests/test_stats.py")
        ],
    )

    # 1. Clarification
    rev_clarif = WorkOrderRevisionManager.create_revision(
        current_wo=base_wo,
        change_reason="Clarify negative window handling",
        author="human_dev",
        revision_kind=RevisionKind.CLARIFICATION,
        new_instruction_text="Base prompt with clarification",
    )
    inv_clarif = WorkOrderRevisionManager.evaluate_invalidation(base_wo, rev_clarif, RevisionKind.CLARIFICATION)
    assert not inv_clarif["scope_expanded"]
    assert not inv_clarif["requires_reauthorization"]
    assert rev_clarif.version == 2
    assert rev_clarif.predecessor_hash == base_wo.contract_hash

    # 2. Scope Expansion
    rev_scope = WorkOrderRevisionManager.create_revision(
        current_wo=base_wo,
        change_reason="Add new helper file",
        author="human_dev",
        revision_kind=RevisionKind.SCOPE_EXPANSION,
        updated_paths=["src/stats_utils.py", "src/helpers.py"],
    )
    inv_scope = WorkOrderRevisionManager.evaluate_invalidation(base_wo, rev_scope, RevisionKind.SCOPE_EXPANSION)
    assert inv_scope["scope_expanded"] is True
    assert inv_scope["requires_reauthorization"] is True
    assert inv_scope["prior_artifacts_reusable"] is False

    # 3. Criteria Mutation
    new_crit = [
        AcceptanceCriterion("c1", "test", "pytest", "tests/test_stats.py"),
        AcceptanceCriterion("c2", "integration test", "pytest", "tests/test_integration.py"),
    ]
    rev_crit = WorkOrderRevisionManager.create_revision(
        current_wo=base_wo,
        change_reason="Add integration test criterion",
        author="human_dev",
        revision_kind=RevisionKind.CRITERIA_MUTATION,
        updated_criteria=new_crit,
    )
    inv_crit = WorkOrderRevisionManager.evaluate_invalidation(base_wo, rev_crit, RevisionKind.CRITERIA_MUTATION)
    assert inv_crit["criteria_changed"] is True
    assert inv_crit["prior_artifacts_reusable"] is False

    # 4. Cancellation
    rev_cancel = WorkOrderRevisionManager.create_revision(
        current_wo=base_wo,
        change_reason="User cancelled",
        author="human_dev",
        revision_kind=RevisionKind.CANCELLATION,
    )
    inv_cancel = WorkOrderRevisionManager.evaluate_invalidation(base_wo, rev_cancel, RevisionKind.CANCELLATION)
    assert inv_cancel["is_cancellation"] is True
    assert rev_cancel.state.current_stage == WorkOrderState.CANCELLED


def test_stale_worker_rejection_after_revision(env):
    engine: WorkflowEngine = env["engine"]
    adapter: HumanInterfaceAdapter = env["adapter"]
    store: ArtifactStore = env["store"]

    compiler = WorkOrderCompiler()
    wo_v1 = compiler.compile(
        raw_text="Initial work order",
        source_channel="cli",
        source_reference="ref-stale",
        repository_id="homelab-ai",
        baseline_commit="8b25d26",
        proposed_mutation_paths=["src/stats_utils.py"],
        acceptance_criteria=[
            AcceptanceCriterion("c1", "test", "pytest", "tests/test_stats.py")
        ],
    )
    adapter.submit_work_order(wo_v1)
    wo_id = wo_v1.work_order_id

    # Create assignment and acquire lease
    with engine._get_connection() as conn:
        conn.execute(
            """
            INSERT INTO task_assignments (
                assignment_id, work_order_id, work_order_version, step_id,
                required_role, status, fencing_token, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            ("asgn-stale-1", wo_id, 1, "step-patch", "defect_patch", "READY", 1),
        )
        conn.commit()

    # Worker leases assignment in v1 (fencing token becomes 2)
    worker_fence = engine.acquire_lease("asgn-stale-1", "worker-b65-0")
    assert worker_fence == 2

    # Operator revises work order to v2
    adapter.revise_work_order(
        work_order_id=wo_id,
        version=1,
        revision_kind=RevisionKind.SCOPE_EXPANSION,
        change_reason="Scope expanded to include additional modules",
        updated_paths=["src/stats_utils.py", "src/helpers.py"],
    )

    # v1 is now SUPERSEDED
    v1_rec = engine.get_work_order(wo_id, 1)
    assert v1_rec["state"] == str(WorkOrderState.SUPERSEDED)

    # Assignment in v1 is marked SUPERSEDED and fence incremented
    asgn_rec = engine.get_assignment("asgn-stale-1")
    assert asgn_rec["status"] == str(TaskStepState.SUPERSEDED)
    assert asgn_rec["fencing_token"] == 3  # incremented to 3 by supersede

    # Store a dummy artifact
    art = store.put(
        content="diff --git a/src/stats_utils.py b/src/stats_utils.py\n",
        artifact_type=ArtifactType.PATCH,
        work_order_id=wo_id,
        work_order_version=1,
        step_id="step-patch",
        producing_worker_id="worker-b65-0",
        producing_profile_hash="prof-0",
        capability_token_id="tok-0",
    )

    # Worker attempts commit with stale fencing token 2 and superseded assignment
    with pytest.raises(WorkflowEngineError) as exc_info:
        engine.complete_assignment(
            assignment_id="asgn-stale-1",
            fencing_token=worker_fence,  # token 2
            output_artifact_hash=art.artifact_hash,
        )
    assert exc_info.value.failure_class in (FailureClass.SUPERSEDED, FailureClass.STALE_FENCING_TOKEN)


def test_stale_worker_rejection_after_cancellation(env):
    engine: WorkflowEngine = env["engine"]
    adapter: HumanInterfaceAdapter = env["adapter"]
    store: ArtifactStore = env["store"]

    compiler = WorkOrderCompiler()
    wo_v1 = compiler.compile(
        raw_text="Work order to cancel",
        source_channel="cli",
        source_reference="ref-cancel",
        repository_id="homelab-ai",
        baseline_commit="8b25d26",
        proposed_mutation_paths=["src/stats_utils.py"],
        acceptance_criteria=[
            AcceptanceCriterion("c1", "test", "pytest", "tests/test_stats.py")
        ],
    )
    adapter.submit_work_order(wo_v1)
    wo_id = wo_v1.work_order_id

    # Create assignment and acquire lease
    with engine._get_connection() as conn:
        conn.execute(
            """
            INSERT INTO task_assignments (
                assignment_id, work_order_id, work_order_version, step_id,
                required_role, status, fencing_token, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            ("asgn-cancel-1", wo_id, 1, "step-patch", "defect_patch", "READY", 1),
        )
        conn.commit()

    worker_fence = engine.acquire_lease("asgn-cancel-1", "worker-b65-0")
    assert worker_fence == 2

    # Operator cancels work order
    adapter.cancel_work_order(wo_id, 1, reason="Operator halted execution")

    # Assignment is now REVOKED
    asgn_rec = engine.get_assignment("asgn-cancel-1")
    assert asgn_rec["status"] == str(TaskStepState.REVOKED)

    # Store dummy artifact
    art = store.put(
        content="diff --git a/src/stats_utils.py b/src/stats_utils.py\n",
        artifact_type=ArtifactType.PATCH,
        work_order_id=wo_id,
        work_order_version=1,
        step_id="step-patch",
        producing_worker_id="worker-b65-0",
        producing_profile_hash="prof-0",
        capability_token_id="tok-0",
    )

    # Worker commit must fail
    with pytest.raises(WorkflowEngineError) as exc_info:
        engine.complete_assignment(
            assignment_id="asgn-cancel-1",
            fencing_token=worker_fence,
            output_artifact_hash=art.artifact_hash,
        )
    assert exc_info.value.failure_class in (
        FailureClass.CAPABILITY_EXPIRED_OR_REVOKED,
        FailureClass.WORK_ORDER_CANCELLED,
        FailureClass.STALE_FENCING_TOKEN,
    )


def test_immutable_revision_lineage_chain(env):
    adapter: HumanInterfaceAdapter = env["adapter"]
    compiler = WorkOrderCompiler()

    wo_v1 = compiler.compile(
        raw_text="Revision lineage test",
        source_channel="cli",
        source_reference="ref-lineage",
        repository_id="homelab-ai",
        baseline_commit="8b25d26",
        proposed_mutation_paths=["src/stats_utils.py"],
        acceptance_criteria=[
            AcceptanceCriterion("c1", "test", "pytest", "tests/test_stats.py")
        ],
    )
    adapter.submit_work_order(wo_v1)
    wo_id = wo_v1.work_order_id

    # Revise to v2
    rec_v2 = adapter.revise_work_order(
        work_order_id=wo_id,
        version=1,
        revision_kind=RevisionKind.CLARIFICATION,
        change_reason="Clarification 1",
    )
    # Revise to v3
    rec_v3 = adapter.revise_work_order(
        work_order_id=wo_id,
        version=2,
        revision_kind=RevisionKind.SCOPE_EXPANSION,
        change_reason="Scope expansion 2",
        updated_paths=["src/stats_utils.py", "src/extra.py"],
    )

    insp_v1 = adapter.inspect_work_order(wo_id, 1)
    insp_v2 = adapter.inspect_work_order(wo_id, 2)
    insp_v3 = adapter.inspect_work_order(wo_id, 3)

    assert insp_v1["contract_hash"] == insp_v2["predecessor_hash"]
    assert insp_v2["contract_hash"] == insp_v3["predecessor_hash"]
    assert insp_v1["state"] == str(WorkOrderState.SUPERSEDED)
    assert insp_v2["state"] == str(WorkOrderState.SUPERSEDED)
    assert insp_v3["state"] == str(WorkOrderState.DRAFT)
