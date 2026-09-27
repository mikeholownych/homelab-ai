"""Tests for Multi-Repository Orchestration, Dependency DAG, and Concurrency."""
import tempfile
from pathlib import Path
import pytest

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.authority.admission import AdmissionEvaluator
from autonomous_engineering.core.types import WorkOrderState
from autonomous_engineering.planning.planner import ExecutionPlanner
from autonomous_engineering.repair.controller import BoundedRepairController
from autonomous_engineering.repository.onboarding import (
    RepositoryContract,
    RepositoryOnboardingManager,
)
from autonomous_engineering.router.evidence_router import EvidenceBasedRouter
from autonomous_engineering.service.multi_repo_service import (
    DependencyCycleError,
    DependencyFailedError,
    MultiRepoConcurrencyManager,
    MultiRepoEngineeringService,
    TaskDependencyManager,
    TaskSchedulingBlockedError,
)
from autonomous_engineering.validator.independent import IndependentValidator
from autonomous_engineering.workflow.engine import WorkflowEngine
from autonomous_engineering.workflow.hardened_pipeline import HardenedRealRepoPipeline
from autonomous_engineering.work_order.compiler import WorkOrderCompiler


def test_dependency_dag_cycle_detection():
    """Verifies that cycles and self-dependencies are detected and rejected prior to execution."""
    mgr = TaskDependencyManager()

    # Self-dependency
    with pytest.raises(DependencyCycleError, match="cannot depend on itself"):
        mgr.register_task("task-1", dependencies=["task-1"])

    # Valid linear chain
    mgr.register_task("task-A", dependencies=[])
    mgr.register_task("task-B", dependencies=["task-A"])
    mgr.register_task("task-C", dependencies=["task-B"])

    # Cycle: task-A depending on task-C
    with pytest.raises(DependencyCycleError, match="creates a cyclic dependency"):
        mgr.register_task("task-D", dependencies=["task-C"])
        # Now closing the loop
        mgr.register_task("task-loop", dependencies=["task-B"])
        # Direct cycle attempt
        mgr.register_task("task-cycle-head", dependencies=["task-C"])
        # Intentionally introduce cycle
        mgr2 = TaskDependencyManager()
        mgr2.register_task("X", dependencies=["Y"])
        mgr2.register_task("Y", dependencies=["X"])


def test_multi_repo_path_conflict_isolation():
    """Verifies path conflicts are scoped per repository: identical file paths in different repos do not conflict."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        repo1_dir = tmp_path / "repo1"
        repo2_dir = tmp_path / "repo2"
        repo1_dir.mkdir()
        repo2_dir.mkdir()
        (repo1_dir / "server.py").write_text("def r1(): pass\n")
        (repo2_dir / "server.py").write_text("def r2(): pass\n")

        concurrency = MultiRepoConcurrencyManager(
            max_total_concurrency=4,
            max_concurrency_per_repo=2,
        )
        compiler = WorkOrderCompiler()

        # Task 1 in Repo 1 on server.py
        wo1 = compiler.compile(
            raw_text="Task 1",
            source_channel="cli",
            source_reference="s1",
            repository_id="repo-1",
            baseline_commit="da54731",
            proposed_mutation_paths=["server.py"],
        )
        object.__setattr__(wo1, "work_order_id", "wo-r1-t1")

        # Task 2 in Repo 1 on server.py (CONCURRENT CONFLICT)
        wo2 = compiler.compile(
            raw_text="Task 2",
            source_channel="cli",
            source_reference="s2",
            repository_id="repo-1",
            baseline_commit="da54731",
            proposed_mutation_paths=["server.py"],
        )
        object.__setattr__(wo2, "work_order_id", "wo-r1-t2")

        # Task 3 in Repo 2 on server.py (DIFFERENT REPO -> NO CONFLICT)
        wo3 = compiler.compile(
            raw_text="Task 3",
            source_channel="cli",
            source_reference="s3",
            repository_id="repo-2",
            baseline_commit="da54731",
            proposed_mutation_paths=["server.py"],
        )
        object.__setattr__(wo3, "work_order_id", "wo-r2-t3")

        ws1 = concurrency.acquire_workspace(wo1, repo1_dir)
        assert ws1.workspace_dir.exists()

        # Task 2 should fail due to path lock conflict in repo-1
        can_r1_t2, conflicts_r1 = concurrency.can_acquire_paths(
            "repo-1", "wo-r1-t2", wo2.authorization.authorized_mutation_paths
        )
        assert can_r1_t2 is False
        assert conflicts_r1 == ["server.py"]

        # Task 3 in repo-2 should succeed because it is in a different repository
        can_r2_t3, conflicts_r2 = concurrency.can_acquire_paths(
            "repo-2", "wo-r2-t3", wo3.authorization.authorized_mutation_paths
        )
        assert can_r2_t3 is True
        assert conflicts_r2 == []
        ws3 = concurrency.acquire_workspace(wo3, repo2_dir)
        assert ws3.workspace_dir.exists()

        # Cleanup
        concurrency.release_workspace("wo-r1-t1", "repo-1")
        concurrency.release_workspace("wo-r2-t3", "repo-2")
        assert not ws1.workspace_dir.exists()
        assert not ws3.workspace_dir.exists()


def test_dependency_aware_execution_and_cascade():
    """Verifies that dependent tasks wait for upstream ACCEPTED, and cascade failure when upstream fails."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "multi_repo.sqlite"
        art_path = tmp_path / "artifacts"
        repo_dir = tmp_path / "aihost_repo"
        repo_dir.mkdir()
        (repo_dir / "mod.py").write_text("def ping(): return 'pong'\n")
        (repo_dir / "tests").mkdir()
        (repo_dir / "tests" / "test_mod.py").write_text("import mod\ndef test_ok(): assert mod.ping() == 'pong'\n")

        onboarding = RepositoryOnboardingManager()
        onboarding.onboard_repository(
            RepositoryContract(
                repository_id="aihost",
                remote_url="git@github.com:mikeholownych/aihost.git",
                baseline_commit="da54731",
                authorized_mutation_paths=("mod.py",),
            )
        )

        engine = WorkflowEngine(db_path)
        store = ArtifactStore(art_path)
        admission = AdmissionEvaluator(onboarding_manager=onboarding)
        planner = ExecutionPlanner()
        router = EvidenceBasedRouter()
        validator = IndependentValidator(artifact_store=store)
        repair_ctrl = BoundedRepairController()

        class MockWorker:
            def __init__(self, should_fail=False):
                self.worker_id = "worker-b65-0"
                self.profile_hash = "hash-worker"
                self.should_fail = should_fail

            def execute(self, task_id, step_id, instruction, context=None):
                if step_id == "step-patch":
                    if self.should_fail:
                        # Malformed patch that fails validation
                        return "--- mod.py\n+++ mod.py\n@@ -1,1 +1,1 @@\n-def ping(): return 'pong'\n+def ping(): invalid python syntax !!!\n"
                    return "--- mod.py\n+++ mod.py\n@@ -1,1 +1,2 @@\n def ping(): return 'pong'\n+# comment\n"
                return "Review passed"

        worker_success = MockWorker(should_fail=False)
        pipeline = HardenedRealRepoPipeline(
            engine=engine,
            artifact_store=store,
            admission_evaluator=admission,
            planner=planner,
            router=router,
            validator=validator,
            repair_controller=repair_ctrl,
            workers={"worker-b65-0": worker_success, "worker-phi4": worker_success},
            target_repo_dir=repo_dir,
        )

        service = MultiRepoEngineeringService(
            engine=engine,
            pipeline=pipeline,
            onboarding_manager=onboarding,
        )

        compiler = WorkOrderCompiler()

        # 1. Register Task A and Task B (B depends on A)
        wo_a = compiler.compile(
            raw_text="Task A",
            source_channel="cli",
            source_reference="s-a",
            repository_id="aihost",
            baseline_commit="da54731",
            proposed_mutation_paths=["mod.py"],
        )
        object.__setattr__(wo_a, "work_order_id", "task-A")

        wo_b = compiler.compile(
            raw_text="Task B",
            source_channel="cli",
            source_reference="s-b",
            repository_id="aihost",
            baseline_commit="da54731",
            proposed_mutation_paths=["mod.py"],
        )
        object.__setattr__(wo_b, "work_order_id", "task-B")

        service.submit_work_order(wo_a)
        service.submit_work_order(wo_b, dependencies=["task-A"])

        # Attempt to run Task B before Task A -> Blocked
        with pytest.raises(TaskSchedulingBlockedError, match="still pending/active"):
            service.execute_task("task-B")

        # Execute Task A -> ACCEPTED
        state_a = service.execute_task("task-A")
        assert state_a == WorkOrderState.ACCEPTED

        # Now Task B can execute -> ACCEPTED
        state_b = service.execute_task("task-B")
        assert state_b == WorkOrderState.ACCEPTED

        # 2. Test Cascade Rejection on Failed Dependency
        # Re-initialize pipeline with failing worker for Task C
        worker_fail = MockWorker(should_fail=True)
        pipeline_fail = HardenedRealRepoPipeline(
            engine=engine,
            artifact_store=store,
            admission_evaluator=admission,
            planner=planner,
            router=router,
            validator=validator,
            repair_controller=repair_ctrl,
            workers={"worker-b65-0": worker_fail, "worker-phi4": worker_fail},
            target_repo_dir=repo_dir,
        )
        service.pipeline = pipeline_fail

        wo_c = compiler.compile(
            raw_text="Task C (Failing)",
            source_channel="cli",
            source_reference="s-c",
            repository_id="aihost",
            baseline_commit="da54731",
            proposed_mutation_paths=["mod.py"],
        )
        object.__setattr__(wo_c, "work_order_id", "task-C")

        wo_d = compiler.compile(
            raw_text="Task D (Depends on C)",
            source_channel="cli",
            source_reference="s-d",
            repository_id="aihost",
            baseline_commit="da54731",
            proposed_mutation_paths=["mod.py"],
        )
        object.__setattr__(wo_d, "work_order_id", "task-D")

        service.submit_work_order(wo_c)
        service.submit_work_order(wo_d, dependencies=["task-C"])

        state_c = service.execute_task("task-C")
        assert state_c == WorkOrderState.REJECTED

        # Task D execution should cascade into REJECTED with DEPENDENCY_FAILED
        state_d = service.execute_task("task-D")
        assert state_d == WorkOrderState.REJECTED
        row_d = engine.get_work_order("task-D", 1)
        assert row_d["terminal_disposition"] == "DEPENDENCY_FAILED"
