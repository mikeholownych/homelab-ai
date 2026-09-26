"""Phase 2 Representative Engineering Task Cohort and Matched Control Comparison.

Evaluates four distinct engineering task classes in contained workspaces:
1. Defect Repair (calculate_moving_average)
2. Multi-File Implementation (order processing & discounts)
3. Meaningful Test Development (token validation test suite)
4. Maintainability & Refactoring (currency formatter deduplication)

Also performs a matched comparative benchmark between Single-Worker Control
and Multi-Worker Cooperative workflows.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import pytest

from autonomous_engineering.artifacts.models import ArtifactRecord
from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.authority.admission import AdmissionEvaluator
from autonomous_engineering.authority.guard import ScopeGuard
from autonomous_engineering.authority.tokens import CapabilityToken
from autonomous_engineering.core.types import (
    ArtifactType,
    FailureClass,
    TaskStepState,
    ValidationStatus,
    WorkOrderState,
)
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
from autonomous_engineering.review.models import (
    FindingSeverity,
    ReviewDisposition,
    ReviewFinding,
    ReviewReport,
)
from autonomous_engineering.router.router import CapabilityRouter
from autonomous_engineering.validator.independent import IndependentValidator
from autonomous_engineering.workers.simulated import (
    FastCoderWorker,
    InvestigatorWorker,
    IterativeWorker,
    MultiFileWorker,
    RefactorWorker,
    RepairWorker,
    ReviewerWorker,
    TestDevWorker,
)
from autonomous_engineering.workflow.engine import WorkflowEngine
from autonomous_engineering.work_order.compiler import WorkOrderCompiler
from autonomous_engineering.work_order.models import AcceptanceCriterion


def setup_profiles() -> tuple[WorkerCapabilityRegistry, WorkerCapabilityProfile, WorkerCapabilityProfile]:
    registry = WorkerCapabilityRegistry()
    author_prof = WorkerCapabilityProfile(
        profile_id="prof-author-b65-0",
        worker_id="worker-b65-0",
        hardware=HardwareTarget("intel_arc_pro_b65", "0000:03:00.0", 34359738368, "xe-24.1"),
        runtime=RuntimeConfig("vllm_xpu", "engineering/b0", "v1.7", "int4", 16384, "qwen2", "hermes"),
        empirical_skills={
            "investigation": EmpiricalSkillRecord("investigation", True, 0.95, 40, "2026-09-26"),
            "defect_patch": EmpiricalSkillRecord("defect_patch", True, 0.92, 50, "2026-09-26"),
            "implementation": EmpiricalSkillRecord("implementation", True, 0.88, 50, "2026-09-26"),
            "test_development": EmpiricalSkillRecord("test_development", True, 0.89, 40, "2026-09-26"),
            "maintainability_refactor": EmpiricalSkillRecord("maintainability_refactor", True, 0.94, 40, "2026-09-26"),
            "bounded_repair": EmpiricalSkillRecord("bounded_repair", True, 0.90, 50, "2026-09-26"),
        },
    )
    reviewer_prof = WorkerCapabilityProfile(
        profile_id="prof-reviewer-b65-1",
        worker_id="worker-b65-1",
        hardware=HardwareTarget("intel_arc_pro_b65", "0000:04:00.0", 34359738368, "xe-24.1"),
        runtime=RuntimeConfig("vllm_xpu", "engineering/b0", "v1.7", "int4", 16384, "qwen2", "hermes"),
        empirical_skills={
            "independent_review": EmpiricalSkillRecord("independent_review", True, 0.96, 60, "2026-09-26"),
        },
    )
    registry.register(author_prof)
    registry.register(reviewer_prof)
    return registry, author_prof, reviewer_prof


def test_cohort_task1_defect_repair(tmp_path: Path):
    """Cohort Task 1: Defect Repair.
    Resolves moving average edge-case handling in stats_utils.py.
    """
    repo_src = Path("phase2/fixtures/disposable_repo")
    repo_dst = tmp_path / "task1_repo"
    shutil.copytree(repo_src, repo_dst)

    cas_dir = tmp_path / "artifacts"
    db_file = tmp_path / "task1_wf.sqlite"
    store = ArtifactStore(cas_dir)
    engine = WorkflowEngine(db_file)
    registry, author_prof, reviewer_prof = setup_profiles()

    patch_content = (
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

    workers = {
        "worker-b65-0": FastCoderWorker("worker-b65-0", author_prof.profile_hash, store, patch_content=patch_content),
        "worker-b65-1": ReviewerWorker("worker-b65-1", reviewer_prof.profile_hash, store),
    }

    orchestrator = OrchestratorControlPlane(
        admission_evaluator=AdmissionEvaluator(),
        planner=ExecutionPlanner(include_investigation=False, include_review=True, primary_role="defect_patch"),
        router=CapabilityRouter(registry),
        engine=engine,
        artifact_store=store,
        validator=IndependentValidator(store),
        repair_controller=BoundedRepairController(),
        workers=workers,
        baseline_repo_dir=repo_dst,
    )

    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Fix moving average to validate negative window and handle window_size > len(data)",
        source_channel="cli",
        source_reference="cohort-task-1",
        repository_id="homelab-ai",
        baseline_commit="8b25d26",
        proposed_mutation_paths=["src/stats_utils.py"],
        acceptance_criteria=[
            AcceptanceCriterion(
                criterion_id="crit-task1-pytest",
                description="Run pytest tests/test_stats_utils.py",
                validator_type="pytest",
                test_target="tests/test_stats_utils.py",
            )
        ],
    )

    state = orchestrator.execute_work_order(wo)
    assert state == WorkOrderState.ACCEPTED

    wo_rec = engine.get_work_order(wo.work_order_id, 1)
    assert wo_rec["state"] == str(WorkOrderState.ACCEPTED)
    assert wo_rec["terminal_disposition"] == "ACCEPTED"


def test_cohort_task2_multi_file_implementation(tmp_path: Path):
    """Cohort Task 2: Multi-File Implementation.
    Corrects order subtotal discount logic across order model and processor modules.
    """
    repo_src = Path("phase2/fixtures/cohort/multi_file_repo")
    repo_dst = tmp_path / "task2_repo"
    shutil.copytree(repo_src, repo_dst)

    cas_dir = tmp_path / "artifacts"
    db_file = tmp_path / "task2_wf.sqlite"
    store = ArtifactStore(cas_dir)
    engine = WorkflowEngine(db_file)
    registry, author_prof, reviewer_prof = setup_profiles()

    patch_content = (
        "diff --git a/src/processor.py b/src/processor.py\n"
        "--- a/src/processor.py\n"
        "+++ b/src/processor.py\n"
        "@@ -12,2 +12,2 @@\n"
        "-    discounted_subtotal = subtotal + discount\n"
        "+    discounted_subtotal = subtotal - discount\n"
    )

    workers = {
        "worker-b65-0": MultiFileWorker("worker-b65-0", author_prof.profile_hash, store, patch_content=patch_content),
        "worker-b65-1": ReviewerWorker("worker-b65-1", reviewer_prof.profile_hash, store),
    }

    orchestrator = OrchestratorControlPlane(
        admission_evaluator=AdmissionEvaluator(),
        planner=ExecutionPlanner(include_investigation=False, include_review=True, primary_role="implementation"),
        router=CapabilityRouter(registry),
        engine=engine,
        artifact_store=store,
        validator=IndependentValidator(store),
        repair_controller=BoundedRepairController(),
        workers=workers,
        baseline_repo_dir=repo_dst,
    )

    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Correct order processing discount calculation so discounts are subtracted",
        source_channel="cli",
        source_reference="cohort-task-2",
        repository_id="homelab-ai",
        baseline_commit="8b25d26",
        proposed_mutation_paths=["src/processor.py", "src/discounts.py"],
        acceptance_criteria=[
            AcceptanceCriterion(
                criterion_id="crit-task2-pytest",
                description="Run pytest tests/test_processor.py",
                validator_type="pytest",
                test_target="tests/test_processor.py",
            )
        ],
    )

    state = orchestrator.execute_work_order(wo)
    assert state == WorkOrderState.ACCEPTED

    wo_rec = engine.get_work_order(wo.work_order_id, 1)
    assert wo_rec["state"] == str(WorkOrderState.ACCEPTED)
    assert wo_rec["terminal_disposition"] == "ACCEPTED"


def test_cohort_task3_meaningful_test_development(tmp_path: Path):
    """Cohort Task 3: Meaningful Test Development.
    Authors test suite specifying bearer token validation rules.
    """
    repo_src = Path("phase2/fixtures/cohort/test_dev_repo")
    repo_dst = tmp_path / "task3_repo"
    shutil.copytree(repo_src, repo_dst)

    cas_dir = tmp_path / "artifacts"
    db_file = tmp_path / "task3_wf.sqlite"
    store = ArtifactStore(cas_dir)
    engine = WorkflowEngine(db_file)
    registry, author_prof, reviewer_prof = setup_profiles()

    test_patch = (
        "--- a/tests/test_token_utils.py\n"
        "+++ b/tests/test_token_utils.py\n"
        "@@ -0,0 +1,22 @@\n"
        "+from src.token_utils import validate_bearer_token\n"
        "+\n"
        "+\n"
        "+def test_valid_token():\n"
        "+    assert validate_bearer_token('Bearer abc123xyz') == 'abc123xyz'\n"
        "+\n"
        "+\n"
        "+def test_invalid_prefix():\n"
        "+    assert validate_bearer_token('Basic abc123xyz') is None\n"
        "+    assert validate_bearer_token('bearer abc123xyz') is None\n"
        "+\n"
        "+\n"
        "+def test_empty_or_whitespace():\n"
        "+    assert validate_bearer_token(None) is None\n"
        "+    assert validate_bearer_token('') is None\n"
        "+    assert validate_bearer_token('Bearer ') is None\n"
        "+    assert validate_bearer_token('Bearer    ') is None\n"
        "+\n"
        "+\n"
        "+def test_internal_whitespace():\n"
        "+    assert validate_bearer_token('Bearer abc 123') is None\n"
        "+    assert validate_bearer_token('Bearer abc\\n123') is None\n"
    )

    workers = {
        "worker-b65-0": TestDevWorker("worker-b65-0", author_prof.profile_hash, store, patch_content=test_patch),
        "worker-b65-1": ReviewerWorker("worker-b65-1", reviewer_prof.profile_hash, store),
    }

    orchestrator = OrchestratorControlPlane(
        admission_evaluator=AdmissionEvaluator(),
        planner=ExecutionPlanner(include_investigation=False, include_review=True, primary_role="test_development"),
        router=CapabilityRouter(registry),
        engine=engine,
        artifact_store=store,
        validator=IndependentValidator(store),
        repair_controller=BoundedRepairController(),
        workers=workers,
        baseline_repo_dir=repo_dst,
    )

    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Author meaningful unit tests for token validation utility in tests/test_token_utils.py",
        source_channel="cli",
        source_reference="cohort-task-3",
        repository_id="homelab-ai",
        baseline_commit="8b25d26",
        proposed_mutation_paths=["tests/test_token_utils.py"],
        acceptance_criteria=[
            AcceptanceCriterion(
                criterion_id="crit-task3-pytest",
                description="Run pytest tests/test_token_utils.py",
                validator_type="pytest",
                test_target="tests/test_token_utils.py",
            )
        ],
    )

    state = orchestrator.execute_work_order(wo)
    assert state == WorkOrderState.ACCEPTED

    wo_rec = engine.get_work_order(wo.work_order_id, 1)
    assert wo_rec["state"] == str(WorkOrderState.ACCEPTED)
    assert wo_rec["terminal_disposition"] == "ACCEPTED"


def test_cohort_task4_maintainability_refactoring(tmp_path: Path):
    """Cohort Task 4: Maintainability and Deduplication.
    Refactors currency formatting boilerplate while preserving all behavioral tests.
    """
    repo_src = Path("phase2/fixtures/cohort/maintainability_repo")
    repo_dst = tmp_path / "task4_repo"
    shutil.copytree(repo_src, repo_dst)

    cas_dir = tmp_path / "artifacts"
    db_file = tmp_path / "task4_wf.sqlite"
    store = ArtifactStore(cas_dir)
    engine = WorkflowEngine(db_file)
    registry, author_prof, reviewer_prof = setup_profiles()

    workers = {
        "worker-b65-0": RefactorWorker("worker-b65-0", author_prof.profile_hash, store),
        "worker-b65-1": ReviewerWorker("worker-b65-1", reviewer_prof.profile_hash, store),
    }

    orchestrator = OrchestratorControlPlane(
        admission_evaluator=AdmissionEvaluator(),
        planner=ExecutionPlanner(include_investigation=False, include_review=True, primary_role="maintainability_refactor"),
        router=CapabilityRouter(registry),
        engine=engine,
        artifact_store=store,
        validator=IndependentValidator(store),
        repair_controller=BoundedRepairController(),
        workers=workers,
        baseline_repo_dir=repo_dst,
    )

    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Deduplicate repetitive formatting logic in currency_formatters.py while maintaining test suite",
        source_channel="cli",
        source_reference="cohort-task-4",
        repository_id="homelab-ai",
        baseline_commit="8b25d26",
        proposed_mutation_paths=["src/currency_formatters.py"],
        acceptance_criteria=[
            AcceptanceCriterion(
                criterion_id="crit-task4-pytest",
                description="Run pytest tests/test_currency_formatters.py",
                validator_type="pytest",
                test_target="tests/test_currency_formatters.py",
            )
        ],
    )

    state = orchestrator.execute_work_order(wo)
    assert state == WorkOrderState.ACCEPTED

    wo_rec = engine.get_work_order(wo.work_order_id, 1)
    assert wo_rec["state"] == str(WorkOrderState.ACCEPTED)
    assert wo_rec["terminal_disposition"] == "ACCEPTED"


def test_matched_control_vs_cooperative_comparison(tmp_path: Path):
    """Gate 7: Matched Comparison between Single-Worker Control and Multi-Worker Cooperative.

    Scenario: An author initially produces a flawed patch containing a defect.
    A) Single-Worker Control:
       - No reviewer.
       - Dispatches flawed patch directly to validator.
       - Validator fails; author must repair with test diagnostic logs alone.
       - Requires multiple repair cycles to resolve.
    B) Multi-Worker Cooperative:
       - Reviewer catches defect and produces structured ReviewReport with concrete findings.
       - Repair worker uses reviewer findings to fix issue before/during repair.
       - Achieves higher first-pass defect detection and clean acceptance.
    """
    # Flawed patch that adds discount instead of subtracting
    flawed_patch = (
        "diff --git a/src/processor.py b/src/processor.py\n"
        "--- a/src/processor.py\n"
        "+++ b/src/processor.py\n"
        "@@ -11,2 +11,2 @@\n"
        "-    discounted_subtotal = subtotal + discount\n"
        "+    discounted_subtotal = subtotal + discount  # Still buggy!\n"
    )
    # Correct repaired patch
    repaired_patch = (
        "diff --git a/src/processor.py b/src/processor.py\n"
        "--- a/src/processor.py\n"
        "+++ b/src/processor.py\n"
        "@@ -11,2 +11,2 @@\n"
        "-    discounted_subtotal = subtotal + discount\n"
        "+    discounted_subtotal = subtotal - discount\n"
    )

    registry, author_prof, reviewer_prof = setup_profiles()

    # --- Part A: Single-Worker Control Execution ---
    repo_ctrl = tmp_path / "repo_ctrl"
    shutil.copytree(Path("phase2/fixtures/cohort/multi_file_repo"), repo_ctrl)
    store_ctrl = ArtifactStore(tmp_path / "artifacts_ctrl")
    engine_ctrl = WorkflowEngine(tmp_path / "wf_ctrl.sqlite")

    ctrl_worker = IterativeWorker(
        "worker-b65-0",
        author_prof.profile_hash,
        store_ctrl,
        patches=[flawed_patch, repaired_patch],
    )

    # In control mode, we use Single-Worker: include_review=False
    ctrl_workers = {"worker-b65-0": ctrl_worker}
    ctrl_orchestrator = OrchestratorControlPlane(
        admission_evaluator=AdmissionEvaluator(),
        planner=ExecutionPlanner(include_investigation=False, include_review=False, primary_role="defect_patch"),
        router=CapabilityRouter(registry),
        engine=engine_ctrl,
        artifact_store=store_ctrl,
        validator=IndependentValidator(store_ctrl),
        repair_controller=BoundedRepairController(),
        workers=ctrl_workers,
        baseline_repo_dir=repo_ctrl,
    )

    compiler = WorkOrderCompiler()
    wo_ctrl = compiler.compile(
        raw_text="Fix discount calculation in processor",
        source_channel="cli",
        source_reference="ctrl-run",
        repository_id="homelab-ai",
        baseline_commit="8b25d26",
        proposed_mutation_paths=["src/processor.py"],
        acceptance_criteria=[
            AcceptanceCriterion(
                criterion_id="crit-ctrl-pytest",
                description="Run pytest tests/test_processor.py",
                validator_type="pytest",
                test_target="tests/test_processor.py",
            )
        ],
        max_retries=1,
    )

    ctrl_state = ctrl_orchestrator.execute_work_order(wo_ctrl)
    assert ctrl_state == WorkOrderState.ACCEPTED

    # Control execution required 2 versions (v1 failed validation -> repaired on v2)
    wo_ctrl_v1 = engine_ctrl.get_work_order(wo_ctrl.work_order_id, 1)
    wo_ctrl_v2 = engine_ctrl.get_work_order(wo_ctrl.work_order_id, 2)
    assert wo_ctrl_v1["state"] == str(WorkOrderState.SUPERSEDED)
    assert wo_ctrl_v2["state"] == str(WorkOrderState.ACCEPTED)

    # --- Part B: Multi-Worker Cooperative Execution ---
    repo_coop = tmp_path / "repo_coop"
    shutil.copytree(Path("phase2/fixtures/cohort/multi_file_repo"), repo_coop)
    store_coop = ArtifactStore(tmp_path / "artifacts_coop")
    engine_coop = WorkflowEngine(tmp_path / "wf_coop.sqlite")

    coop_worker = IterativeWorker(
        "worker-b65-0",
        author_prof.profile_hash,
        store_coop,
        patches=[flawed_patch, repaired_patch],
    )
    coop_reviewer = ReviewerWorker(
        "worker-b65-1",
        reviewer_prof.profile_hash,
        store_coop,
    )

    coop_workers = {
        "worker-b65-0": coop_worker,
        "worker-b65-1": coop_reviewer,
    }

    coop_orchestrator = OrchestratorControlPlane(
        admission_evaluator=AdmissionEvaluator(),
        planner=ExecutionPlanner(include_investigation=False, include_review=True, primary_role="defect_patch"),
        router=CapabilityRouter(registry),
        engine=engine_coop,
        artifact_store=store_coop,
        validator=IndependentValidator(store_coop),
        repair_controller=BoundedRepairController(),
        workers=coop_workers,
        baseline_repo_dir=repo_coop,
        enable_review_repair=True,
    )

    wo_coop = compiler.compile(
        raw_text="Fix discount calculation in processor",
        source_channel="cli",
        source_reference="coop-run",
        repository_id="homelab-ai",
        baseline_commit="8b25d26",
        proposed_mutation_paths=["src/processor.py"],
        acceptance_criteria=[
            AcceptanceCriterion(
                criterion_id="crit-coop-pytest",
                description="Run pytest tests/test_processor.py",
                validator_type="pytest",
                test_target="tests/test_processor.py",
            )
        ],
        max_retries=1,
    )

    coop_state = coop_orchestrator.execute_work_order(wo_coop)
    assert coop_state == WorkOrderState.ACCEPTED

    wo_coop_v1 = engine_coop.get_work_order(wo_coop.work_order_id, 1)
    wo_coop_v2 = engine_coop.get_work_order(wo_coop.work_order_id, 2)
    assert wo_coop_v1["state"] == str(WorkOrderState.SUPERSEDED)
    assert wo_coop_v2["state"] == str(WorkOrderState.ACCEPTED)

    # Verify that in cooperative execution, a structured ReviewReport was produced and captured
    review_assignments = [
        a for a in engine_coop.list_assignments(wo_coop.work_order_id, 1)
        if a["required_role"] == "independent_review"
    ]
    assert len(review_assignments) == 1
    rev_asgn = review_assignments[0]
    assert rev_asgn["status"] == str(TaskStepState.COMPLETED)
    assert rev_asgn["output_artifact_hash"] is not None

    rev_content = json.loads(store_coop.get(rev_asgn["output_artifact_hash"]).decode("utf-8"))
    assert rev_content["disposition"] == "RECOMMEND_REVISE"
    assert len(rev_content["findings"]) > 0
    assert "subtotal + discount" in rev_content["findings"][0]["description"].lower() or "adds discount" in rev_content["findings"][0]["description"].lower()
