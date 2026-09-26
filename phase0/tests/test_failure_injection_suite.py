"""Automated Failure-Injection and Authority Recovery Test Suite.

Proves all 12 non-negotiable failure boundaries mandated in Section 8:
1. Duplicate assignment delivery.
2. Worker crash before artifact submission.
3. Worker crash after artifact submission but before acknowledgment.
4. Expired lease and stale fencing token.
5. Orchestrator restart during execution.
6. Stale artifact or review submission.
7. Work-order revision during active execution.
8. Revoked or expired capability.
9. Validator rejection.
10. Missing or contradictory authority.
11. Retry-budget exhaustion.
12. Attempted mutation outside authorized scope.
"""
from datetime import datetime, timezone
from pathlib import Path
import pytest

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.authority.admission import AdmissionEvaluator
from autonomous_engineering.authority.guard import ScopeGuard, ScopeViolationError
from autonomous_engineering.authority.tokens import CapabilityToken
from autonomous_engineering.core.types import (
    ArtifactType,
    FailureClass,
    TaskStepState,
    ValidationStatus,
    WorkOrderState,
)
from autonomous_engineering.planning.models import ExecutionPlan, TaskStepDefinition
from autonomous_engineering.planning.planner import ExecutionPlanner
from autonomous_engineering.repair.controller import BoundedRepairController
from autonomous_engineering.router.router import CapabilityRouter
from autonomous_engineering.validator.independent import IndependentValidator, ValidationVerdict
from autonomous_engineering.workers.simulated import (
    FastCoderWorker,
    FaultyWorker,
    InvestigatorWorker,
    OutOfScopeWorker,
)
from autonomous_engineering.workflow.engine import WorkflowEngine, WorkflowEngineError
from autonomous_engineering.work_order.compiler import WorkOrderCompiler
from autonomous_engineering.work_order.models import AcceptanceCriterion


@pytest.fixture
def repo_fixture_path() -> Path:
    base = Path(__file__).parent.parent / "fixtures" / "sample_repo"
    assert base.exists()
    return base


def test_failure_mode_1_duplicate_assignment_delivery(tmp_path: Path):
    """1. Duplicate assignment delivery is handled idempotently without corrupting state."""
    engine = WorkflowEngine(tmp_path / "wf.sqlite")
    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Test",
        source_channel="t",
        source_reference="r",
        repository_id="repo",
        baseline_commit="c",
    )
    engine.register_work_order(wo)

    plan = ExecutionPlan(
        plan_id="p1",
        work_order_id=wo.work_order_id,
        work_order_version=1,
        steps=(
            TaskStepDefinition(
                step_id="step-1",
                required_role="defect_patch",
                description="desc",
                target_paths=("src/**",),
                dependencies=(),
                output_artifact_type=ArtifactType.PATCH,
            ),
        ),
    )
    asgn_id = engine.initialize_plan(plan)[0]
    token = engine.acquire_lease(asgn_id, "worker-1")

    # First delivery succeeds
    engine.complete_assignment(asgn_id, token, "hash-123")

    # Duplicate delivery with identical token and hash completes idempotently
    engine.complete_assignment(asgn_id, token, "hash-123")
    asgn = engine.get_assignment(asgn_id)
    assert asgn is not None
    assert asgn["status"] == str(TaskStepState.COMPLETED)
    assert asgn["output_artifact_hash"] == "hash-123"


def test_failure_mode_2_worker_crash_before_artifact_submission(tmp_path: Path):
    """2. Worker crashes before submitting artifact.

    Lease expires, and re-assignment increments fencing token for Worker 2.
    """
    engine = WorkflowEngine(tmp_path / "wf.sqlite")
    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Test",
        source_channel="t",
        source_reference="r",
        repository_id="repo",
        baseline_commit="c",
    )
    engine.register_work_order(wo)

    plan = ExecutionPlan(
        plan_id="p1",
        work_order_id=wo.work_order_id,
        work_order_version=1,
        steps=(
            TaskStepDefinition(
                step_id="step-1",
                required_role="defect_patch",
                description="desc",
                target_paths=("src/**",),
                dependencies=(),
                output_artifact_type=ArtifactType.PATCH,
            ),
        ),
    )
    asgn_id = engine.initialize_plan(plan)[0]

    # Worker 1 leases task at token=2 then crashes
    token_w1 = engine.acquire_lease(asgn_id, "worker-1", lease_seconds=1)
    assert token_w1 == 2

    # Orchestrator detects timeout and reassigns to Worker 2 at token=3
    token_w2 = engine.acquire_lease(asgn_id, "worker-2", lease_seconds=60)
    assert token_w2 == 3

    # Worker 2 submits successfully
    engine.complete_assignment(asgn_id, token_w2, "hash-worker-2")
    asgn = engine.get_assignment(asgn_id)
    assert asgn is not None
    assert asgn["output_artifact_hash"] == "hash-worker-2"


def test_failure_mode_3_worker_crash_after_artifact_submission_before_ack(tmp_path: Path):
    """3. Worker crashes after writing artifact to store and DB, before ack to caller.

    Replay queries DB and discovers completed state without re-executing.
    """
    engine = WorkflowEngine(tmp_path / "wf.sqlite")
    store = ArtifactStore(tmp_path / "artifacts")
    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Test",
        source_channel="t",
        source_reference="r",
        repository_id="repo",
        baseline_commit="c",
    )
    engine.register_work_order(wo)

    plan = ExecutionPlan(
        plan_id="p1",
        work_order_id=wo.work_order_id,
        work_order_version=1,
        steps=(
            TaskStepDefinition(
                step_id="step-1",
                required_role="defect_patch",
                description="desc",
                target_paths=("src/**",),
                dependencies=(),
                output_artifact_type=ArtifactType.PATCH,
            ),
        ),
    )
    asgn_id = engine.initialize_plan(plan)[0]
    token = engine.acquire_lease(asgn_id, "worker-1")

    art = store.put(
        content="patch bytes",
        artifact_type=ArtifactType.PATCH,
        work_order_id=wo.work_order_id,
        work_order_version=1,
        step_id="step-1",
        producing_worker_id="worker-1",
        producing_profile_hash="p1",
        capability_token_id="tok-1",
    )
    engine.complete_assignment(asgn_id, token, art.artifact_hash)

    # Worker crashes before returning ACK to orchestrator.
    # Orchestrator replay checks assignment status:
    asgn = engine.get_assignment(asgn_id)
    assert asgn is not None
    assert asgn["status"] == str(TaskStepState.COMPLETED)
    assert asgn["output_artifact_hash"] == art.artifact_hash
    # Verified: No duplicate mutation needed!


def test_failure_mode_4_expired_lease_and_stale_fencing_token(tmp_path: Path):
    """4. Late worker submission with stale fencing token is rejected."""
    engine = WorkflowEngine(tmp_path / "wf.sqlite")
    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Test",
        source_channel="t",
        source_reference="r",
        repository_id="repo",
        baseline_commit="c",
    )
    engine.register_work_order(wo)

    plan = ExecutionPlan(
        plan_id="p1",
        work_order_id=wo.work_order_id,
        work_order_version=1,
        steps=(
            TaskStepDefinition(
                step_id="step-1",
                required_role="defect_patch",
                description="desc",
                target_paths=("src/**",),
                dependencies=(),
                output_artifact_type=ArtifactType.PATCH,
            ),
        ),
    )
    asgn_id = engine.initialize_plan(plan)[0]

    stale_token = engine.acquire_lease(asgn_id, "worker-1", lease_seconds=1)
    fresh_token = engine.acquire_lease(asgn_id, "worker-2", lease_seconds=60)

    # Late worker-1 attempts submission
    with pytest.raises(WorkflowEngineError) as exc_info:
        engine.complete_assignment(asgn_id, stale_token, "stale-artifact")
    assert exc_info.value.failure_class == FailureClass.STALE_FENCING_TOKEN


def test_failure_mode_5_orchestrator_restart_during_execution(tmp_path: Path):
    """5. Orchestrator crashes and restarts mid-execution. State is recovered from disk."""
    db_file = tmp_path / "wf_restart.sqlite"
    engine1 = WorkflowEngine(db_file)
    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Test restart",
        source_channel="t",
        source_reference="r",
        repository_id="repo",
        baseline_commit="c",
    )
    engine1.register_work_order(wo)

    plan = ExecutionPlan(
        plan_id="p-restart",
        work_order_id=wo.work_order_id,
        work_order_version=1,
        steps=(
            TaskStepDefinition(
                step_id="step-1",
                required_role="investigation",
                description="desc",
                target_paths=("src/**",),
                dependencies=(),
                output_artifact_type=ArtifactType.REPRODUCTION_SCRIPT,
            ),
        ),
    )
    asgn_id = engine1.initialize_plan(plan)[0]
    token = engine1.acquire_lease(asgn_id, "worker-1")

    # Orchestrator process crashes abruptly
    del engine1

    # Orchestrator boots up fresh
    engine2 = WorkflowEngine(db_file)
    asgn = engine2.get_assignment(asgn_id)
    assert asgn is not None
    assert asgn["fencing_token"] == token
    assert asgn["status"] == str(TaskStepState.DISPATCHED)


def test_failure_mode_6_stale_artifact_or_review_submission(tmp_path: Path):
    """6. Reject artifact submission when submitted hash conflicts with existing completed assignment."""
    engine = WorkflowEngine(tmp_path / "wf.sqlite")
    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Test",
        source_channel="t",
        source_reference="r",
        repository_id="repo",
        baseline_commit="c",
    )
    engine.register_work_order(wo)

    plan = ExecutionPlan(
        plan_id="p1",
        work_order_id=wo.work_order_id,
        work_order_version=1,
        steps=(
            TaskStepDefinition(
                step_id="step-1",
                required_role="defect_patch",
                description="desc",
                target_paths=("src/**",),
                dependencies=(),
                output_artifact_type=ArtifactType.PATCH,
            ),
        ),
    )
    asgn_id = engine.initialize_plan(plan)[0]
    token = engine.acquire_lease(asgn_id, "worker-1")
    engine.complete_assignment(asgn_id, token, "hash-original")

    # Conflicting submission with different hash
    with pytest.raises(WorkflowEngineError) as exc_info:
        engine.complete_assignment(asgn_id, token, "hash-conflicting-different")
    assert exc_info.value.failure_class == FailureClass.MALFORMED_OUTPUT


def test_failure_mode_7_work_order_revision_during_active_execution(tmp_path: Path):
    """7. Revision during active execution supersedes and invalidates active assignments."""
    engine = WorkflowEngine(tmp_path / "wf.sqlite")
    compiler = WorkOrderCompiler()
    wo_v1 = compiler.compile(
        raw_text="V1",
        source_channel="t",
        source_reference="r",
        repository_id="repo",
        baseline_commit="c",
    )
    engine.register_work_order(wo_v1)

    plan_v1 = ExecutionPlan(
        plan_id="p1",
        work_order_id=wo_v1.work_order_id,
        work_order_version=1,
        steps=(
            TaskStepDefinition(
                step_id="step-1",
                required_role="defect_patch",
                description="desc",
                target_paths=("src/**",),
                dependencies=(),
                output_artifact_type=ArtifactType.PATCH,
            ),
        ),
    )
    asgn_id = engine.initialize_plan(plan_v1)[0]
    token = engine.acquire_lease(asgn_id, "worker-1")

    # Work order is superseded while worker-1 is executing
    engine.supersede_work_order(wo_v1.work_order_id, 1)

    # Worker-1 tries to commit
    with pytest.raises(WorkflowEngineError) as exc_info:
        engine.complete_assignment(asgn_id, token, "hash-late")
    assert exc_info.value.failure_class == FailureClass.SUPERSEDED


def test_failure_mode_8_revoked_or_expired_capability():
    """8. Expired or revoked capability fails closed."""
    # Revoked token
    token_revoked = CapabilityToken(
        token_id="tok-rev",
        work_order_id="wo-1",
        work_order_version=1,
        task_id="t-1",
        authorized_paths=("src/**",),
        authorized_tools=("read_file",),
        max_retries=1,
        fencing_token=1,
        issued_at="2026-09-26T00:00:00Z",
        expires_at="2030-01-01T00:00:00Z",
        revoked=True,
    )
    assert token_revoked.is_valid() is False
    with pytest.raises(ScopeViolationError) as exc_rev:
        ScopeGuard.verify_token(token_revoked)
    assert exc_rev.value.failure_class == FailureClass.CAPABILITY_EXPIRED_OR_REVOKED

    # Expired token
    token_expired = CapabilityToken(
        token_id="tok-exp",
        work_order_id="wo-1",
        work_order_version=1,
        task_id="t-1",
        authorized_paths=("src/**",),
        authorized_tools=("read_file",),
        max_retries=1,
        fencing_token=1,
        issued_at="2020-01-01T00:00:00Z",
        expires_at="2021-01-01T00:00:00Z",
        revoked=False,
    )
    assert token_expired.is_valid() is False
    with pytest.raises(ScopeViolationError) as exc_exp:
        ScopeGuard.verify_token(token_expired)
    assert exc_exp.value.failure_class == FailureClass.CAPABILITY_EXPIRED_OR_REVOKED


def test_failure_mode_9_validator_rejection(tmp_path: Path, repo_fixture_path: Path):
    """9. Flawed patch is rejected by validator, preserved as evidence, not accepted."""
    store = ArtifactStore(tmp_path / "artifacts")
    validator = IndependentValidator(store)

    flawed_patch = (
        "diff --git a/src/calculator/math_utils.py b/src/calculator/math_utils.py\n"
        "--- a/src/calculator/math_utils.py\n"
        "+++ b/src/calculator/math_utils.py\n"
        "@@ -6,2 +6,3 @@\n"
        " def calculate_ratio(a: float, b: float) -> float:\n"
        "+    return 42.0  # Incorrect logic\n"
        "     return a / b\n"
    )
    art = store.put(
        content=flawed_patch,
        artifact_type=ArtifactType.PATCH,
        work_order_id="wo-flawed",
        work_order_version=1,
        step_id="step-patch",
        producing_worker_id="worker-faulty",
        producing_profile_hash="prof-faulty",
        capability_token_id="tok-1",
    )

    criteria = (
        AcceptanceCriterion(
            criterion_id="crit-unit",
            description="Run test suite",
            validator_type="pytest",
            test_target="tests/test_math_utils.py",
            required=True,
        ),
    )
    verdict = validator.validate(art, criteria, repo_fixture_path)
    assert verdict.status == ValidationStatus.REJECTED
    assert len(verdict.diagnostic_logs) > 0


def test_failure_mode_10_missing_or_contradictory_authority():
    """10. Missing or contradictory authority fails closed at admission gate."""
    evaluator = AdmissionEvaluator()
    compiler = WorkOrderCompiler()

    wo = compiler.compile(
        raw_text="Valid text",
        source_channel="cli",
        source_reference="ref-1",
        repository_id="homelab-ai",
        baseline_commit="1aa374a",
    )

    # Missing human approval
    dec_no_approval = evaluator.evaluate(wo, human_approval_present=False)
    assert dec_no_approval.admitted is False

    # Expired authority
    wo_expired = compiler.compile(
        raw_text="Valid text",
        source_channel="cli",
        source_reference="ref-2",
        repository_id="homelab-ai",
        baseline_commit="1aa374a",
        valid_until="2020-01-01T00:00:00Z",
    )
    dec_expired = evaluator.evaluate(wo_expired, human_approval_present=True)
    assert dec_expired.admitted is False


def test_failure_mode_11_retry_budget_exhaustion(tmp_path: Path):
    """11. Repair controller stops and marks budget exhausted when max retries exceeded."""
    store = ArtifactStore(tmp_path / "artifacts")
    repair_ctrl = BoundedRepairController()
    compiler = WorkOrderCompiler()

    wo = compiler.compile(
        raw_text="Fix defect",
        source_channel="test",
        source_reference="ref-b",
        repository_id="homelab-ai",
        baseline_commit="1aa374a",
        max_retries=1,
    )
    art = store.put(
        content="failing patch",
        artifact_type=ArtifactType.PATCH,
        work_order_id=wo.work_order_id,
        work_order_version=1,
        step_id="step-patch",
        producing_worker_id="w-1",
        producing_profile_hash="p-1",
        capability_token_id="tok-1",
    )
    verdict = ValidationVerdict(
        verdict_id="vrd-1",
        work_order_id=wo.work_order_id,
        work_order_version=1,
        artifact_hash=art.artifact_hash,
        status=ValidationStatus.REJECTED,
        checks=(),
        diagnostic_logs="AssertionError: failed",
    )

    # Attempt 1
    repair_wo1 = repair_ctrl.prepare_repair_work_order(wo, art, verdict)
    assert repair_wo1 is not None

    # Attempt 2 -> Budget exhausted
    repair_wo2 = repair_ctrl.prepare_repair_work_order(repair_wo1, art, verdict)
    assert repair_wo2 is None


def test_failure_mode_12_attempted_mutation_outside_authorized_scope(tmp_path: Path):
    """12. Attempted mutation outside authorized scope is halted by ScopeGuard."""
    store = ArtifactStore(tmp_path / "artifacts")
    token = CapabilityToken(
        token_id="tok-scope",
        work_order_id="wo-scope",
        work_order_version=1,
        task_id="step-patch",
        authorized_paths=("src/calculator/*.py",),
        authorized_tools=("read_file", "write_patch"),
        max_retries=1,
        fencing_token=1,
        issued_at="2026-09-26T00:00:00Z",
        expires_at="2030-01-01T00:00:00Z",
    )

    rogue_worker = OutOfScopeWorker("worker-rogue", "prof-rogue", store)
    step = TaskStepDefinition(
        step_id="step-patch",
        required_role="defect_patch",
        description="Write patch",
        target_paths=("src/calculator/*.py",),
        dependencies=(),
        output_artifact_type=ArtifactType.PATCH,
    )

    with pytest.raises(ScopeViolationError) as exc_info:
        rogue_worker.execute("asgn-1", step, token, 1)
    assert exc_info.value.failure_class == FailureClass.SCOPE_VIOLATION
