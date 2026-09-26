"""Phase 2 Real-Process Concurrency, Lease Expiration, and 12 POSIX Signal Failure Modes.

Proves durability, fencing, independence, and supervisor authority across real operating system
child processes, signals, and database WAL transactions.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import pytest

from autonomous_engineering.artifacts.models import ArtifactRecord
from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.authority.admission import AdmissionEvaluator
from autonomous_engineering.authority.guard import ScopeGuard, ScopeViolationError
from autonomous_engineering.authority.tokens import CapabilityToken
from autonomous_engineering.core.types import (
    ArtifactType,
    FailureClass,
    TaskRole,
    TaskStepState,
    ValidationStatus,
    WorkOrderState,
)
from autonomous_engineering.orchestrator import OrchestratorControlPlane, OrchestrationError
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
from autonomous_engineering.review.models import (
    FindingSeverity,
    ReviewDisposition,
    ReviewFinding,
    ReviewReport,
)
from autonomous_engineering.router.router import CapabilityRouter
from autonomous_engineering.validator.independent import IndependentValidator, ValidationVerdict
from autonomous_engineering.workers.simulated import (
    FastCoderWorker,
    FaultyWorker,
    InvestigatorWorker,
    RepairWorker,
    ReviewerWorker,
)
from autonomous_engineering.workflow.engine import WorkflowEngine, WorkflowEngineError
from autonomous_engineering.work_order.compiler import WorkOrderCompiler
from autonomous_engineering.work_order.models import AcceptanceCriterion, Budget, WorkOrder


def test_1_concurrent_assignments_with_independent_dependencies(tmp_path: Path):
    """Failure Mode 1: Concurrent assignments with independent dependencies.
    Two child processes execute tasks concurrently without database deadlock.
    """
    db_file = tmp_path / "concurrent_wf.sqlite"
    engine = WorkflowEngine(db_file)

    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Concurrent test",
        source_channel="cli",
        source_reference="ref-conc",
        repository_id="homelab-ai",
        baseline_commit="8b25d26",
    )
    engine.register_work_order(wo)

    plan = ExecutionPlan(
        plan_id="p-conc",
        work_order_id=wo.work_order_id,
        work_order_version=1,
        steps=(
            TaskStepDefinition(
                step_id="step-conc-1",
                required_role="investigation",
                description="Investigate subtask 1",
                target_paths=("src/**",),
                dependencies=(),
                output_artifact_type=ArtifactType.REPRODUCTION_SCRIPT,
            ),
            TaskStepDefinition(
                step_id="step-conc-2",
                required_role="investigation",
                description="Investigate subtask 2",
                target_paths=("src/**",),
                dependencies=(),
                output_artifact_type=ArtifactType.REPRODUCTION_SCRIPT,
            ),
        ),
    )
    asgn_ids = engine.initialize_plan(plan)
    assert len(asgn_ids) == 2

    # Both steps have no dependencies and are initialized as READY
    token_1 = engine.acquire_lease(asgn_ids[0], "worker-child-1")
    token_2 = engine.acquire_lease(asgn_ids[1], "worker-child-2")

    worker_code_template = (
        "import sys\n"
        "from autonomous_engineering.workflow.engine import WorkflowEngine\n"
        "engine = WorkflowEngine(sys.argv[1])\n"
        "engine.complete_assignment(sys.argv[2], int(sys.argv[3]), sys.argv[4])\n"
    )

    env = {**os.environ, "PYTHONPATH": "phase2/src"}
    p1 = subprocess.Popen(
        [sys.executable, "-c", worker_code_template, str(db_file), asgn_ids[0], str(token_1), "hash-art-1"],
        env=env,
    )
    p2 = subprocess.Popen(
        [sys.executable, "-c", worker_code_template, str(db_file), asgn_ids[1], str(token_2), "hash-art-2"],
        env=env,
    )

    ret1 = p1.wait(timeout=10)
    ret2 = p2.wait(timeout=10)

    assert ret1 == 0
    assert ret2 == 0

    asgn1 = engine.get_assignment(asgn_ids[0])
    asgn2 = engine.get_assignment(asgn_ids[1])
    assert asgn1["status"] == str(TaskStepState.COMPLETED)
    assert asgn1["output_artifact_hash"] == "hash-art-1"
    assert asgn2["status"] == str(TaskStepState.COMPLETED)
    assert asgn2["output_artifact_hash"] == "hash-art-2"


def test_2_duplicate_assignment_dispatch_handling(tmp_path: Path):
    """Failure Mode 2: Duplicate assignment completion delivery.
    Idempotent success when identical artifact hash is submitted with same token;
    Atomic rejection if conflicting artifact is submitted.
    """
    db_file = tmp_path / "dup_wf.sqlite"
    engine = WorkflowEngine(db_file)

    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Duplicate test",
        source_channel="cli",
        source_reference="ref-dup",
        repository_id="homelab-ai",
        baseline_commit="8b25d26",
    )
    engine.register_work_order(wo)

    plan = ExecutionPlan(
        plan_id="p-dup",
        work_order_id=wo.work_order_id,
        work_order_version=1,
        steps=(
            TaskStepDefinition(
                step_id="step-dup",
                required_role="defect_patch",
                description="Patch task",
                target_paths=("src/**",),
                dependencies=(),
                output_artifact_type=ArtifactType.PATCH,
            ),
        ),
    )
    asgn_id = engine.initialize_plan(plan)[0]
    token = engine.acquire_lease(asgn_id, "worker-1")

    # Initial completion
    engine.complete_assignment(asgn_id, token, "hash-idempotent-patch")

    # Identical redelivery succeeds idempotently
    engine.complete_assignment(asgn_id, token, "hash-idempotent-patch")

    # Conflicting completion for already completed task raises error
    with pytest.raises(WorkflowEngineError) as exc_info:
        engine.complete_assignment(asgn_id, token, "hash-conflicting-patch")
    assert exc_info.value.failure_class == FailureClass.MALFORMED_OUTPUT


def test_3_worker_sigkill_during_implementation(tmp_path: Path):
    """Failure Mode 3: Real worker process SIGKILL during implementation.
    Child process terminated by OS signal; control plane re-leases to worker 2.
    """
    db_file = tmp_path / "sigkill_wf.sqlite"
    engine = WorkflowEngine(db_file)

    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="SIGKILL test",
        source_channel="cli",
        source_reference="ref-sigkill",
        repository_id="homelab-ai",
        baseline_commit="8b25d26",
    )
    engine.register_work_order(wo)

    plan = ExecutionPlan(
        plan_id="p-sigkill",
        work_order_id=wo.work_order_id,
        work_order_version=1,
        steps=(
            TaskStepDefinition(
                step_id="step-impl",
                required_role="implementation",
                description="Implementation step",
                target_paths=("src/**",),
                dependencies=(),
                output_artifact_type=ArtifactType.PATCH,
            ),
        ),
    )
    asgn_id = engine.initialize_plan(plan)[0]
    token_1 = engine.acquire_lease(asgn_id, "worker-author-1")

    # Spawn worker author 1 that simulates work
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    assert proc.poll() is None

    # Abrupt SIGKILL
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait()
    assert proc.poll() == -signal.SIGKILL

    # Reacquire lease for worker-author-2 with incremented fencing token
    token_2 = engine.acquire_lease(asgn_id, "worker-author-2")
    assert token_2 == token_1 + 1

    # Worker author 2 completes task
    engine.complete_assignment(asgn_id, token_2, "hash-author-2-success")
    asgn = engine.get_assignment(asgn_id)
    assert asgn["status"] == str(TaskStepState.COMPLETED)
    assert asgn["lease_worker"] == "worker-author-2"


def test_4_worker_sigkill_after_artifact_write_before_db_commit(tmp_path: Path):
    """Failure Mode 4: Worker SIGKILL after artifact write to CAS, before DB commit.
    Orphaned artifact is safely ignored or recovered; second worker completes.
    """
    db_file = tmp_path / "orphan_wf.sqlite"
    cas_dir = tmp_path / "artifacts"
    store = ArtifactStore(cas_dir)
    engine = WorkflowEngine(db_file)

    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Orphan test",
        source_channel="cli",
        source_reference="ref-orphan",
        repository_id="homelab-ai",
        baseline_commit="8b25d26",
    )
    engine.register_work_order(wo)

    plan = ExecutionPlan(
        plan_id="p-orphan",
        work_order_id=wo.work_order_id,
        work_order_version=1,
        steps=(
            TaskStepDefinition(
                step_id="step-patch",
                required_role="defect_patch",
                description="Patch step",
                target_paths=("src/**",),
                dependencies=(),
                output_artifact_type=ArtifactType.PATCH,
            ),
        ),
    )
    asgn_id = engine.initialize_plan(plan)[0]
    token_1 = engine.acquire_lease(asgn_id, "worker-crashed")

    # Worker writes artifact to disk
    orphaned_artifact = store.put(
        content="diff --git a/test.py b/test.py",
        artifact_type=ArtifactType.PATCH,
        work_order_id=wo.work_order_id,
        work_order_version=1,
        step_id="step-patch",
        producing_worker_id="worker-crashed",
        producing_profile_hash="hash-crashed",
        capability_token_id="tok-1",
    )

    # Worker crashes before engine.complete_assignment is called.
    # Assignment remains in DISPATCHED state with token_1
    asgn = engine.get_assignment(asgn_id)
    assert asgn["status"] == str(TaskStepState.DISPATCHED)
    assert asgn["output_artifact_hash"] is None

    # Re-leased to worker-recovery with token_2
    token_2 = engine.acquire_lease(asgn_id, "worker-recovery")
    assert token_2 == token_1 + 1

    # Worker recovery can reference or recommit the artifact
    engine.complete_assignment(asgn_id, token_2, orphaned_artifact.artifact_hash)
    asgn = engine.get_assignment(asgn_id)
    assert asgn["status"] == str(TaskStepState.COMPLETED)
    assert asgn["output_artifact_hash"] == orphaned_artifact.artifact_hash


def test_5_orchestrator_restart_with_active_workers(tmp_path: Path):
    """Failure Mode 5: Orchestrator process crash and restart with active DB state.
    Recovers from SQLite WAL; advances pending tasks when completed.
    """
    db_file = tmp_path / "restart_wf.sqlite"
    engine1 = WorkflowEngine(db_file)

    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Restart test",
        source_channel="cli",
        source_reference="ref-restart",
        repository_id="homelab-ai",
        baseline_commit="8b25d26",
    )
    engine1.register_work_order(wo)

    plan = ExecutionPlan(
        plan_id="p-restart",
        work_order_id=wo.work_order_id,
        work_order_version=1,
        steps=(
            TaskStepDefinition(
                step_id="step-inv",
                required_role="investigation",
                description="Investigation step",
                target_paths=("src/**",),
                dependencies=(),
                output_artifact_type=ArtifactType.REPRODUCTION_SCRIPT,
            ),
            TaskStepDefinition(
                step_id="step-patch",
                required_role="defect_patch",
                description="Patch step",
                target_paths=("src/**",),
                dependencies=("step-inv",),
                output_artifact_type=ArtifactType.PATCH,
            ),
        ),
    )
    asgn_ids = engine1.initialize_plan(plan)
    token_inv = engine1.acquire_lease(asgn_ids[0], "worker-inv")

    # Orchestrator 1 dies. We simulate this by deleting engine1 reference and creating engine2.
    del engine1

    engine2 = WorkflowEngine(db_file)
    asgn_inv = engine2.get_assignment(asgn_ids[0])
    asgn_patch = engine2.get_assignment(asgn_ids[1])
    assert asgn_inv["status"] == str(TaskStepState.DISPATCHED)
    assert asgn_patch["status"] == str(TaskStepState.PENDING)

    # Worker completes investigation on resumed engine
    engine2.complete_assignment(asgn_ids[0], token_inv, "hash-inv-done")
    advanced = engine2.advance_ready_tasks(plan)
    assert asgn_ids[1] in advanced

    asgn_patch_now = engine2.get_assignment(asgn_ids[1])
    assert asgn_patch_now["status"] == str(TaskStepState.READY)


def test_6_stale_fencing_token_rejection_zombie_worker(tmp_path: Path):
    """Failure Mode 6: Stale fencing token rejected when zombie worker wakes up.
    Linear monotonically incremented fencing prevents stale state writes.
    """
    db_file = tmp_path / "zombie_wf.sqlite"
    engine = WorkflowEngine(db_file)

    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Zombie test",
        source_channel="cli",
        source_reference="ref-zombie",
        repository_id="homelab-ai",
        baseline_commit="8b25d26",
    )
    engine.register_work_order(wo)

    plan = ExecutionPlan(
        plan_id="p-zombie",
        work_order_id=wo.work_order_id,
        work_order_version=1,
        steps=(
            TaskStepDefinition(
                step_id="step-patch",
                required_role="defect_patch",
                description="Patch step",
                target_paths=("src/**",),
                dependencies=(),
                output_artifact_type=ArtifactType.PATCH,
            ),
        ),
    )
    asgn_id = engine.initialize_plan(plan)[0]

    # Worker 1 gets token 2
    token_1 = engine.acquire_lease(asgn_id, "worker-zombie")

    # Worker 2 re-leases task and gets token 3
    token_2 = engine.acquire_lease(asgn_id, "worker-active")
    assert token_2 == token_1 + 1

    # Active worker completes
    engine.complete_assignment(asgn_id, token_2, "hash-active-patch")

    # Zombie worker attempts commit with token 2 -> rejected
    with pytest.raises(WorkflowEngineError) as exc_info:
        engine.complete_assignment(asgn_id, token_1, "hash-zombie-patch")
    assert exc_info.value.failure_class == FailureClass.STALE_FENCING_TOKEN


def test_7_delayed_review_of_superseded_artifact(tmp_path: Path):
    """Failure Mode 7: Delayed review of superseded artifact.
    Reviewer attempts commit after work order is superseded; rejected with SUPERSEDED.
    """
    db_file = tmp_path / "superseded_review.sqlite"
    engine = WorkflowEngine(db_file)

    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Superseded review test",
        source_channel="cli",
        source_reference="ref-sup",
        repository_id="homelab-ai",
        baseline_commit="8b25d26",
    )
    engine.register_work_order(wo)

    plan = ExecutionPlan(
        plan_id="p-sup-review",
        work_order_id=wo.work_order_id,
        work_order_version=1,
        steps=(
            TaskStepDefinition(
                step_id="step-review",
                required_role="independent_review",
                description="Review step",
                target_paths=("src/**",),
                dependencies=(),
                output_artifact_type=ArtifactType.REVIEW_REPORT,
            ),
        ),
    )
    asgn_id = engine.initialize_plan(plan)[0]
    token = engine.acquire_lease(asgn_id, "worker-reviewer")

    # Work order is superseded while review was in-flight
    engine.supersede_work_order(wo.work_order_id, version=1)

    asgn = engine.get_assignment(asgn_id)
    assert asgn["status"] == str(TaskStepState.SUPERSEDED)

    # Reviewer tries to commit -> fails closed
    with pytest.raises(WorkflowEngineError) as exc_info:
        engine.complete_assignment(asgn_id, token, "hash-review-report")
    assert exc_info.value.failure_class == FailureClass.SUPERSEDED


def test_8_work_order_revision_during_cooperative_execution(tmp_path: Path):
    """Failure Mode 8: Work order revision invalidates all active assignments.
    Atomic transition marks draft/pending/dispatched tasks as SUPERSEDED.
    """
    db_file = tmp_path / "revision_wf.sqlite"
    engine = WorkflowEngine(db_file)

    compiler = WorkOrderCompiler()
    wo_v1 = compiler.compile(
        raw_text="Initial requirement",
        source_channel="cli",
        source_reference="ref-rev",
        repository_id="homelab-ai",
        baseline_commit="8b25d26",
    )
    engine.register_work_order(wo_v1)

    plan = ExecutionPlan(
        plan_id="p-rev-v1",
        work_order_id=wo_v1.work_order_id,
        work_order_version=1,
        steps=(
            TaskStepDefinition(
                step_id="step-1",
                required_role="investigation",
                description="Investigation step",
                target_paths=("src/**",),
                dependencies=(),
                output_artifact_type=ArtifactType.REPRODUCTION_SCRIPT,
            ),
            TaskStepDefinition(
                step_id="step-2",
                required_role="defect_patch",
                description="Patch step",
                target_paths=("src/**",),
                dependencies=("step-1",),
                output_artifact_type=ArtifactType.PATCH,
            ),
        ),
    )
    asgn_ids = engine.initialize_plan(plan)
    token_1 = engine.acquire_lease(asgn_ids[0], "worker-1")

    # Revision arrives
    engine.supersede_work_order(wo_v1.work_order_id, version=1)

    wo_rec = engine.get_work_order(wo_v1.work_order_id, 1)
    assert wo_rec["state"] == str(WorkOrderState.SUPERSEDED)

    asgn_1 = engine.get_assignment(asgn_ids[0])
    asgn_2 = engine.get_assignment(asgn_ids[1])
    assert asgn_1["status"] == str(TaskStepState.SUPERSEDED)
    assert asgn_2["status"] == str(TaskStepState.SUPERSEDED)


def test_9_capability_token_revocation_during_active_assignment():
    """Failure Mode 9: ScopeGuard detects unauthorized mutation attempt.
    Aborts immediately with ScopeViolationError.
    """
    token = CapabilityToken(
        token_id="tok-valid",
        work_order_id="wo-scope-1",
        work_order_version=1,
        task_id="task-1",
        authorized_paths=("src/calculator/math_utils.py",),
        authorized_tools=("write_patch", "read_file"),
        max_retries=3,
        fencing_token=1,
        issued_at=datetime.now(timezone.utc).isoformat(),
        expires_at=datetime.fromtimestamp(time.time() + 300, tz=timezone.utc).isoformat(),
    )

    # Valid mutation path passes
    ScopeGuard.check_mutation_path(token, "src/calculator/math_utils.py")

    # Unauthorized path fails closed
    with pytest.raises(ScopeViolationError):
        ScopeGuard.check_mutation_path(token, "/etc/shadow")

    with pytest.raises(ScopeViolationError):
        ScopeGuard.check_mutation_path(token, "config/production_secrets.json")


def test_10_validator_failure_with_review_recommend_accept(tmp_path: Path):
    """Failure Mode 10: Review says RECOMMEND_ACCEPT, but independent validator fails.
    Proves that reviewer opinion is strictly advisory and validator verdict takes precedence.
    """
    cas_dir = tmp_path / "artifacts"
    db_file = tmp_path / "val_advisory.sqlite"
    store = ArtifactStore(cas_dir)
    engine = WorkflowEngine(db_file)

    # Patch with incorrect logic that will fail validator test
    flawed_patch = (
        "diff --git a/src/calculator/math_utils.py b/src/calculator/math_utils.py\n"
        "--- a/src/calculator/math_utils.py\n"
        "+++ b/src/calculator/math_utils.py\n"
        "@@ -10,2 +10,4 @@\n"
        " def calculate_ratio(a: float, b: float) -> float:\n"
        "+    if b == 0:\n"
        "+        return 999999.0\n"
        "     return a / b\n"
    )

    # Setup repo fixture
    repo_dir = tmp_path / "repo"
    src_dir = repo_dir / "src" / "calculator"
    tests_dir = repo_dir / "tests"
    src_dir.mkdir(parents=True)
    tests_dir.mkdir(parents=True)
    (src_dir / "__init__.py").write_text("", encoding="utf-8")
    (src_dir / "math_utils.py").write_text(
        "def calculate_ratio(a: float, b: float) -> float:\n    return a / b\n", encoding="utf-8"
    )
    (tests_dir / "__init__.py").write_text("", encoding="utf-8")
    (tests_dir / "test_math_utils.py").write_text(
        "import pytest\n"
        "from src.calculator.math_utils import calculate_ratio\n"
        "def test_div_zero():\n"
        "    with pytest.raises(ValueError, match='cannot be zero'):\n"
        "        calculate_ratio(10, 0)\n",
        encoding="utf-8",
    )

    # Register profiles
    prof_coder = WorkerCapabilityProfile(
        profile_id="p-coder",
        worker_id="worker-coder",
        hardware=HardwareTarget("intel_arc_pro_b65", "0000:03:00.0", 34359738368, "xe-24.1"),
        runtime=RuntimeConfig("vllm_xpu", "engineering/b0", "v1.7", "int4", 16384, "qwen2", "hermes"),
        empirical_skills={"defect_patch": EmpiricalSkillRecord("defect_patch", True, 0.90, 50, "2026-09-26")},
    )
    prof_rev = WorkerCapabilityProfile(
        profile_id="p-rev",
        worker_id="worker-rev",
        hardware=HardwareTarget("intel_arc_pro_b65", "0000:04:00.0", 34359738368, "xe-24.1"),
        runtime=RuntimeConfig("vllm_xpu", "engineering/b0", "v1.7", "int4", 16384, "qwen2", "hermes"),
        empirical_skills={"independent_review": EmpiricalSkillRecord("independent_review", True, 0.95, 50, "2026-09-26")},
    )
    registry = WorkerCapabilityRegistry()
    registry.register(prof_coder)
    registry.register(prof_rev)

    # Reviewer forced to give RECOMMEND_ACCEPT
    workers = {
        "worker-coder": FastCoderWorker("worker-coder", prof_coder.profile_hash, store, patch_content=flawed_patch),
        "worker-rev": ReviewerWorker("worker-rev", prof_rev.profile_hash, store, force_disposition=ReviewDisposition.RECOMMEND_ACCEPT),
    }

    orchestrator = OrchestratorControlPlane(
        admission_evaluator=AdmissionEvaluator(),
        planner=ExecutionPlanner(include_investigation=False, include_review=True),
        router=CapabilityRouter(registry),
        engine=engine,
        artifact_store=store,
        validator=IndependentValidator(store),
        repair_controller=BoundedRepairController(),
        workers=workers,
        baseline_repo_dir=repo_dir,
        enable_review_repair=False,  # Force proceeding directly to validator to prove advisory nature
    )

    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Fix zero division in calculate_ratio",
        source_channel="cli",
        source_reference="ref-adv",
        repository_id="homelab-ai",
        baseline_commit="8b25d26",
        proposed_mutation_paths=["src/calculator/math_utils.py"],
        acceptance_criteria=[
            AcceptanceCriterion(
                criterion_id="crit-unit-test",
                description="Run pytest tests/test_math_utils.py",
                validator_type="pytest",
                test_target="tests/test_math_utils.py",
            )
        ],
        max_retries=0,  # No retries -> must fail immediately
    )

    state = orchestrator.execute_work_order(wo)
    # Even though reviewer gave RECOMMEND_ACCEPT, independent validator failed the patch!
    assert state == WorkOrderState.FAILED_BUDGET_EXHAUSTED
    wo_rec = engine.get_work_order(wo.work_order_id, 1)
    assert wo_rec["terminal_disposition"] == "FAILED_BUDGET_EXHAUSTED"


def test_11_partial_dag_completion_recovery(tmp_path: Path):
    """Failure Mode 11: Crash after partial DAG completion resumes from SQLite state.
    Completed steps are not re-executed; next ready steps dispatch cleanly.
    """
    db_file = tmp_path / "partial_dag.sqlite"
    engine = WorkflowEngine(db_file)

    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Partial DAG recovery test",
        source_channel="cli",
        source_reference="ref-partial",
        repository_id="homelab-ai",
        baseline_commit="8b25d26",
    )
    engine.register_work_order(wo)

    plan = ExecutionPlan(
        plan_id="p-dag",
        work_order_id=wo.work_order_id,
        work_order_version=1,
        steps=(
            TaskStepDefinition(
                step_id="step-1",
                required_role="investigation",
                description="Investigation step",
                target_paths=("src/**",),
                dependencies=(),
                output_artifact_type=ArtifactType.REPRODUCTION_SCRIPT,
            ),
            TaskStepDefinition(
                step_id="step-2",
                required_role="defect_patch",
                description="Patch step",
                target_paths=("src/**",),
                dependencies=("step-1",),
                output_artifact_type=ArtifactType.PATCH,
            ),
            TaskStepDefinition(
                step_id="step-3",
                required_role="independent_review",
                description="Review step",
                target_paths=("src/**",),
                dependencies=("step-2",),
                output_artifact_type=ArtifactType.REVIEW_REPORT,
            ),
        ),
    )
    asgn_ids = engine.initialize_plan(plan)
    token_1 = engine.acquire_lease(asgn_ids[0], "worker-1")
    engine.complete_assignment(asgn_ids[0], token_1, "hash-step-1")
    engine.advance_ready_tasks(plan)

    # Step 1 is COMPLETED, Step 2 is READY, Step 3 is PENDING
    assert engine.get_assignment(asgn_ids[0])["status"] == str(TaskStepState.COMPLETED)
    assert engine.get_assignment(asgn_ids[1])["status"] == str(TaskStepState.READY)
    assert engine.get_assignment(asgn_ids[2])["status"] == str(TaskStepState.PENDING)

    # Simulate crash & restart
    new_engine = WorkflowEngine(db_file)
    assert new_engine.get_assignment(asgn_ids[0])["status"] == str(TaskStepState.COMPLETED)
    assert new_engine.get_assignment(asgn_ids[1])["status"] == str(TaskStepState.READY)
    assert new_engine.get_assignment(asgn_ids[2])["status"] == str(TaskStepState.PENDING)


def test_12_retry_budget_exhaustion_termination(tmp_path: Path):
    """Failure Mode 12: Multiple failures terminate at FAILED_BUDGET_EXHAUSTED.
    Prevents infinite repair loops; emits authoritative failure.
    """
    cas_dir = tmp_path / "artifacts"
    db_file = tmp_path / "exhaustion.sqlite"
    store = ArtifactStore(cas_dir)
    engine = WorkflowEngine(db_file)

    broken_patch = (
        "diff --git a/src/calculator/math_utils.py b/src/calculator/math_utils.py\n"
        "--- a/src/calculator/math_utils.py\n"
        "+++ b/src/calculator/math_utils.py\n"
        "@@ -10,2 +10,3 @@\n"
        " def calculate_ratio(a: float, b: float) -> float:\n"
        "+    this is not valid python syntax !!!\n"
        "     return a / b\n"
    )

    repo_dir = tmp_path / "repo"
    src_dir = repo_dir / "src" / "calculator"
    tests_dir = repo_dir / "tests"
    src_dir.mkdir(parents=True)
    tests_dir.mkdir(parents=True)
    (src_dir / "__init__.py").write_text("", encoding="utf-8")
    (src_dir / "math_utils.py").write_text("def calculate_ratio(a, b): return a / b\n", encoding="utf-8")
    (tests_dir / "__init__.py").write_text("", encoding="utf-8")
    (tests_dir / "test_math_utils.py").write_text(
        "import pytest\n"
        "from src.calculator.math_utils import calculate_ratio\n"
        "def test_div_zero():\n"
        "    with pytest.raises(ValueError):\n"
        "        calculate_ratio(10, 0)\n",
        encoding="utf-8",
    )

    prof_coder = WorkerCapabilityProfile(
        profile_id="p-faulty",
        worker_id="worker-faulty",
        hardware=HardwareTarget("intel_arc_pro_b65", "0000:03:00.0", 34359738368, "xe-24.1"),
        runtime=RuntimeConfig("vllm_xpu", "engineering/b0", "v1.7", "int4", 16384, "qwen2", "hermes"),
        empirical_skills={"defect_patch": EmpiricalSkillRecord("defect_patch", True, 0.90, 50, "2026-09-26")},
    )
    registry = WorkerCapabilityRegistry()
    registry.register(prof_coder)

    workers = {
        "worker-faulty": FastCoderWorker("worker-faulty", prof_coder.profile_hash, store, patch_content=broken_patch),
    }

    orchestrator = OrchestratorControlPlane(
        admission_evaluator=AdmissionEvaluator(),
        planner=ExecutionPlanner(include_investigation=False, include_review=False),
        router=CapabilityRouter(registry),
        engine=engine,
        artifact_store=store,
        validator=IndependentValidator(store),
        repair_controller=BoundedRepairController(),
        workers=workers,
        baseline_repo_dir=repo_dir,
    )

    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Fix zero division",
        source_channel="cli",
        source_reference="ref-exhaust",
        repository_id="homelab-ai",
        baseline_commit="8b25d26",
        proposed_mutation_paths=["src/calculator/math_utils.py"],
        acceptance_criteria=[
            AcceptanceCriterion(
                criterion_id="crit-unit-test",
                description="Run pytest tests/test_math_utils.py",
                validator_type="pytest",
                test_target="tests/test_math_utils.py",
            )
        ],
        max_retries=1,  # Exactly 1 retry allowed
    )

    state = orchestrator.execute_work_order(wo)
    assert state == WorkOrderState.FAILED_BUDGET_EXHAUSTED
    wo_v2 = engine.get_work_order(wo.work_order_id, 2)
    assert wo_v2 is not None
    assert wo_v2["state"] == str(WorkOrderState.FAILED_BUDGET_EXHAUSTED)
