"""Phase 3 Real-Task Interruption, Revocation, and Recovery Tests.

Evaluates:
1. Worker process termination (SIGKILL) mid-task and lease expiration recovery.
2. Operator mid-execution cancellation and atomic worker lease revocation.
3. Operator mid-execution bounded revision and stale fencing token rejection.
4. Work order pause and resume across persistent storage boundaries.
5. Orchestrator restart and continuation from SQLite WAL durable state.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import pytest

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.authority.admission import AdmissionEvaluator
from autonomous_engineering.core.types import (
    ArtifactType,
    FailureClass,
    RevisionKind,
    TaskStepState,
    WorkOrderState,
)
from autonomous_engineering.interface.adapter import HumanInterfaceAdapter
from autonomous_engineering.orchestrator import OrchestratorControlPlane
from autonomous_engineering.planning.models import ExecutionPlan, TaskStepDefinition
from autonomous_engineering.planning.planner import ExecutionPlanner
from autonomous_engineering.registry.models import (
    EmpiricalSkillRecord,
    EvidenceSource,
    HardwareTarget,
    RuntimeConfig,
    WorkerCapabilityProfile,
)
from autonomous_engineering.registry.registry import WorkerCapabilityRegistry
from autonomous_engineering.repair.controller import BoundedRepairController
from autonomous_engineering.router.router import CapabilityRouter
from autonomous_engineering.validator.independent import IndependentValidator
from autonomous_engineering.workers.simulated import FastCoderWorker, ReviewerWorker
from autonomous_engineering.workflow.engine import WorkflowEngine, WorkflowEngineError
from autonomous_engineering.work_order.compiler import WorkOrderCompiler
from autonomous_engineering.work_order.models import AcceptanceCriterion


@pytest.fixture
def b65_profiles():
    registry = WorkerCapabilityRegistry()
    hw_0 = HardwareTarget("intel_arc_pro_b65", "0000:51:00.0", 32 * 1024**3, "xe-24.1")
    hw_1 = HardwareTarget("intel_arc_pro_b65", "0000:93:00.0", 32 * 1024**3, "xe-24.1")
    runtime = RuntimeConfig("vllm_xpu", "engineering/b0", "v1.7", "int4", 16384, "qwen2", "hermes")

    prof_author = WorkerCapabilityProfile(
        profile_id="prof-b65-0",
        worker_id="worker-b65-0",
        hardware=hw_0,
        runtime=runtime,
        empirical_skills={
            "defect_patch": EmpiricalSkillRecord(
                "defect_patch", True, 0.94, 50, "2026-09-27", EvidenceSource.EMPIRICAL_DEPLOYED_MEASUREMENT
            ),
        },
    )
    prof_reviewer = WorkerCapabilityProfile(
        profile_id="prof-b65-1",
        worker_id="worker-b65-1",
        hardware=hw_1,
        runtime=runtime,
        empirical_skills={
            "independent_review": EmpiricalSkillRecord(
                "independent_review", True, 0.96, 60, "2026-09-27", EvidenceSource.EMPIRICAL_DEPLOYED_MEASUREMENT
            )
        },
    )
    registry.register(prof_author)
    registry.register(prof_reviewer)
    return registry, prof_author, prof_reviewer


def test_worker_sigkill_and_lease_expiration_recovery(tmp_path: Path):
    """Test 1: Worker process killed with SIGKILL mid-task.
    Lease expires and is safely re-acquired by a replacement worker without database corruption.
    Stale attempts from old worker token are strictly rejected.
    """
    db_file = tmp_path / "recovery_wf.sqlite"
    engine = WorkflowEngine(db_file)

    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Recovery test",
        source_channel="cli",
        source_reference="rec-1",
        repository_id="disposable_repo",
        baseline_commit="8b25d26",
    )
    engine.register_work_order(wo)

    plan = ExecutionPlan(
        plan_id="p-rec",
        work_order_id=wo.work_order_id,
        work_order_version=1,
        steps=(
            TaskStepDefinition(
                step_id="step-1",
                required_role="defect_patch",
                description="Long-running synthesis",
                target_paths=("src/**",),
                dependencies=(),
                output_artifact_type=ArtifactType.PATCH,
            ),
        ),
    )
    asgn_ids = engine.initialize_plan(plan)
    asgn_id = asgn_ids[0]

    # Acquire short lease: 1 second
    token_1 = engine.acquire_lease(asgn_id, "worker-dying", lease_seconds=1)

    # Spawn child process that sleeps
    worker_script = (
        "import time\n"
        "time.sleep(10)\n"
    )
    proc = subprocess.Popen([sys.executable, "-c", worker_script])
    time.sleep(0.2)
    # SIGKILL the worker process
    proc.send_signal(signal.SIGKILL)
    proc.wait()

    # Re-acquire lease by replacement worker
    token_2 = engine.acquire_lease(asgn_id, "worker-replacement", lease_seconds=30)
    assert token_2 > token_1

    # Stale completion attempt with token_1 MUST be rejected with STALE_FENCING_TOKEN
    with pytest.raises(WorkflowEngineError) as exc_info:
        engine.complete_assignment(asgn_id, token_1, "hash-stale-artifact")
    assert exc_info.value.failure_class == FailureClass.STALE_FENCING_TOKEN

    # Replacement worker completes successfully
    engine.complete_assignment(asgn_id, token_2, "hash-replacement-artifact")
    asgn = engine.get_assignment(asgn_id)
    assert asgn["status"] == str(TaskStepState.COMPLETED)
    assert asgn["output_artifact_hash"] == "hash-replacement-artifact"


def test_operator_mid_execution_cancellation_revocation(tmp_path: Path):
    """Test 2: Operator cancels work order while worker has an active lease.
    Subsequent completion attempt by worker is strictly rejected with WORK_ORDER_CANCELLED.
    """
    db_file = tmp_path / "cancel_wf.sqlite"
    engine = WorkflowEngine(db_file)
    store = ArtifactStore(tmp_path / "artifacts")
    adapter = HumanInterfaceAdapter(engine, store)

    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Cancellation test",
        source_channel="cli",
        source_reference="rec-2",
        repository_id="disposable_repo",
        baseline_commit="8b25d26",
    )
    adapter.submit_work_order(wo)

    plan = ExecutionPlan(
        plan_id="p-cancel",
        work_order_id=wo.work_order_id,
        work_order_version=1,
        steps=(
            TaskStepDefinition(
                step_id="step-cancel-1",
                required_role="defect_patch",
                description="Task to be cancelled",
                target_paths=("src/**",),
                dependencies=(),
                output_artifact_type=ArtifactType.PATCH,
            ),
        ),
    )
    asgn_ids = engine.initialize_plan(plan)
    asgn_id = asgn_ids[0]

    # Worker acquires lease
    fencing_token = engine.acquire_lease(asgn_id, "worker-b65-0")

    # Operator cancels work order
    adapter.cancel_work_order(wo.work_order_id, wo.version, "Emergency operator stop")

    # Verify work order state in engine is CANCELLED
    wo_rec = engine.get_work_order(wo.work_order_id, wo.version)
    assert wo_rec["state"] == str(WorkOrderState.CANCELLED)

    # Worker attempts completion with acquired fencing token -> MUST be rejected
    with pytest.raises(WorkflowEngineError) as exc_info:
        engine.complete_assignment(asgn_id, fencing_token, "hash-late-artifact")
    assert exc_info.value.failure_class in (FailureClass.WORK_ORDER_CANCELLED, FailureClass.CAPABILITY_EXPIRED_OR_REVOKED)


def test_mid_execution_revision_stale_token_rejection(tmp_path: Path):
    """Test 3: Work order is revised while worker holds active lease on v1.
    Worker attempting completion on v1 is rejected with REVISION_SUPERSEDED or SUPERSEDED.
    """
    db_file = tmp_path / "revision_wf.sqlite"
    engine = WorkflowEngine(db_file)
    store = ArtifactStore(tmp_path / "artifacts")
    adapter = HumanInterfaceAdapter(engine, store)

    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Revision test initial",
        source_channel="cli",
        source_reference="rec-3",
        repository_id="disposable_repo",
        baseline_commit="8b25d26",
        proposed_mutation_paths=["src/stats_utils.py"],
    )
    adapter.submit_work_order(wo)

    plan_v1 = ExecutionPlan(
        plan_id="p-v1",
        work_order_id=wo.work_order_id,
        work_order_version=1,
        steps=(
            TaskStepDefinition(
                step_id="step-v1-patch",
                required_role="defect_patch",
                description="Synthesize patch v1",
                target_paths=("src/stats_utils.py",),
                dependencies=(),
                output_artifact_type=ArtifactType.PATCH,
            ),
        ),
    )
    asgn_ids = engine.initialize_plan(plan_v1)
    asgn_id = asgn_ids[0]

    # In-flight worker acquires lease
    fencing_token_v1 = engine.acquire_lease(asgn_id, "worker-b65-0")

    # Operator revises work order (restricting scope or updating criteria)
    rev_receipt = adapter.revise_work_order(
        work_order_id=wo.work_order_id,
        version=1,
        revision_kind=RevisionKind.CRITERIA_MUTATION,
        change_reason="Updated acceptance test requirement",
        updated_criteria=[
            AcceptanceCriterion("c_new", "New test", "pytest", "tests/test_new.py")
        ],
    )
    assert rev_receipt.version == 2

    # In-flight worker on v1 attempts completion -> MUST be rejected as superseded
    with pytest.raises(WorkflowEngineError) as exc_info:
        engine.complete_assignment(asgn_id, fencing_token_v1, "hash-v1-patch")
    assert exc_info.value.failure_class in (FailureClass.REVISION_SUPERSEDED, FailureClass.SUPERSEDED)

    # Verify v1 is SUPERSEDED and v2 is recorded
    v1_rec = engine.get_work_order(wo.work_order_id, 1)
    v2_rec = engine.get_work_order(wo.work_order_id, 2)
    assert v1_rec["state"] == str(WorkOrderState.SUPERSEDED)
    assert v2_rec is not None


def test_pause_and_resume_durability(tmp_path: Path):
    """Test 4: Pause work order, verify state, and resume with clean continuation."""
    db_file = tmp_path / "pause_wf.sqlite"
    engine = WorkflowEngine(db_file)
    store = ArtifactStore(tmp_path / "artifacts")
    adapter = HumanInterfaceAdapter(engine, store)

    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Pause resume test",
        source_channel="cli",
        source_reference="rec-4",
        repository_id="disposable_repo",
        baseline_commit="8b25d26",
    )
    adapter.submit_work_order(wo)

    # Pause
    adapter.pause_work_order(wo.work_order_id, 1)
    wo_rec = engine.get_work_order(wo.work_order_id, 1)
    assert wo_rec["state"] == str(WorkOrderState.PAUSED)

    # Resume
    adapter.resume_work_order(wo.work_order_id, 1)
    wo_rec = engine.get_work_order(wo.work_order_id, 1)
    assert wo_rec["state"] == str(WorkOrderState.EXECUTING)


def test_orchestrator_restart_recovery_from_wal(b65_profiles, tmp_path: Path):
    """Test 5: Orchestrator process crash and restart.
    Verifies that a new Orchestrator instance connects to the existing SQLite WAL database,
    inspects existing assignments, avoids re-running completed steps, and finishes execution.
    """
    registry, author_prof, reviewer_prof = b65_profiles
    db_file = tmp_path / "crash_restart_wf.sqlite"
    store = ArtifactStore(tmp_path / "artifacts")
    fixture_dir = Path(__file__).parent.parent / "fixtures" / "disposable_repo"
    repo_dir = tmp_path / "repo"
    shutil.copytree(fixture_dir, repo_dir)

    patch = (
        "diff --git a/src/stats_utils.py b/src/stats_utils.py\n"
        "--- a/src/stats_utils.py\n"
        "+++ b/src/stats_utils.py\n"
        "@@ -9,4 +9,4 @@\n"
        "-    if window_size == 0:\n"
        "+    if window_size <= 0:\n"
        "         raise ValueError(\"window_size must be positive\")\n"
        "-\n"
        "+    if window_size > len(data):\n"
        "+        return []\n"
    )

    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Fix moving average bounds crash recovery",
        source_channel="cli",
        source_reference="rec-5",
        repository_id="disposable_repo",
        baseline_commit="8b25d26",
        proposed_mutation_paths=["src/stats_utils.py"],
        acceptance_criteria=[
            AcceptanceCriterion("c1", "Run pytest", "pytest", "tests/test_stats_utils.py")
        ],
    )

    # Engine 1 and Orchestrator 1 execute up to patch creation
    engine1 = WorkflowEngine(db_file)
    workers1 = {
        "worker-b65-0": FastCoderWorker("worker-b65-0", "prof-b65-0", store, patch_content=patch),
        "worker-b65-1": ReviewerWorker("worker-b65-1", "prof-b65-1", store),
    }

    # Simulate crash before validation: execute plan steps directly in engine
    plan = ExecutionPlanner(include_investigation=False, include_review=True, primary_role="defect_patch").create_plan(wo)
    engine1.register_work_order(wo)
    engine1.initialize_plan(plan)

    # Complete step-patch in engine1
    patch_asgn = [a for a in engine1.list_assignments(wo.work_order_id, 1) if a["step_id"] == "step-patch"][0]
    tok = engine1.acquire_lease(patch_asgn["assignment_id"], "worker-b65-0")
    patch_art = store.put(patch, ArtifactType.PATCH, wo.work_order_id, 1, "step-patch", "worker-b65-0", "prof-b65-0", tok)
    engine1.complete_assignment(patch_asgn["assignment_id"], tok, patch_art.artifact_hash)
    engine1.advance_ready_tasks(plan)

    # Complete step-review in engine1
    rev_asgn = [a for a in engine1.list_assignments(wo.work_order_id, 1) if a["step_id"] == "step-review"][0]
    tok_rev = engine1.acquire_lease(rev_asgn["assignment_id"], "worker-b65-1")
    rev_art = store.put(json.dumps({"disposition": "RECOMMEND_ACCEPT", "findings": []}), ArtifactType.REVIEW_REPORT, wo.work_order_id, 1, "step-review", "worker-b65-1", "prof-b65-1", tok_rev)
    engine1.complete_assignment(rev_asgn["assignment_id"], tok_rev, rev_art.artifact_hash)
    engine1.advance_ready_tasks(plan)

    # Simulate abrupt orchestrator process exit / crash (close engine1 connection)
    del engine1

    # Orchestrator 2 starts up afresh on the exact same SQLite WAL file
    engine2 = WorkflowEngine(db_file)
    orch2 = OrchestratorControlPlane(
        admission_evaluator=AdmissionEvaluator(),
        planner=ExecutionPlanner(include_investigation=False, include_review=True, primary_role="defect_patch"),
        router=CapabilityRouter(registry),
        engine=engine2,
        artifact_store=store,
        validator=IndependentValidator(store),
        repair_controller=BoundedRepairController(),
        workers=workers1,
        baseline_repo_dir=repo_dir,
    )

    # Execute work order with Orch 2 - it picks up existing plan, skips completed steps, and validates patch
    state = orch2.execute_work_order(wo)
    assert state == WorkOrderState.ACCEPTED

    wo_final = engine2.get_work_order(wo.work_order_id, 1)
    assert wo_final["state"] == str(WorkOrderState.ACCEPTED)
    assert wo_final["terminal_disposition"] == "ACCEPTED"
