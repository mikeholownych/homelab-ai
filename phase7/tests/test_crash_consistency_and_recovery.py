"""Tests for Crash Consistency, Recovery, and Monotonic Fencing Across 11 Lifecycle Boundaries."""
import tempfile
import time
from pathlib import Path
import pytest

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.authority.admission import AdmissionEvaluator
from autonomous_engineering.core.types import TaskStepState, WorkOrderState
from autonomous_engineering.planning.planner import ExecutionPlanner
from autonomous_engineering.repair.controller import BoundedRepairController
from autonomous_engineering.router.evidence_router import EvidenceBasedRouter
from autonomous_engineering.service.engineering_service import PersistentEngineeringService
from autonomous_engineering.validator.independent import IndependentValidator
from autonomous_engineering.workflow.engine import WorkflowEngine, WorkflowEngineError
from autonomous_engineering.workflow.hardened_pipeline import (
    HardenedRealRepoPipeline,
    LifecycleBoundary,
    LifecycleInjectedCrashError,
)
from autonomous_engineering.work_order.compiler import WorkOrderCompiler


class CrashWorker:
    __test__ = False

    def __init__(self, worker_id: str):
        self.worker_id = worker_id
        self.profile_hash = f"hash-{worker_id}"

    def execute(self, task_id: str, step_id: str, instruction: str, context: dict | None = None) -> str:
        if step_id == "step-patch":
            return (
                "--- orchestrator_gateway/server.py\n"
                "+++ orchestrator_gateway/server.py\n"
                "@@ -1,3 +1,4 @@\n"
                " def validate_request(payload):\n"
                "+    # crash test\n"
                "     return True, None\n"
            )
        elif step_id == "step-repair":
            return (
                "--- orchestrator_gateway/server.py\n"
                "+++ orchestrator_gateway/server.py\n"
                "@@ -1,3 +1,4 @@\n"
                " def validate_request(payload):\n"
                "+    # crash repaired\n"
                "     return True, None\n"
            )
        elif step_id == "step-review":
            if "require_repair" in str(context) or "repair" in task_id:
                return "FINDING: REPAIR_REQUIRED: Test review finding"
            return "Review passed"
        return "Review passed"


@pytest.fixture
def crash_env():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "crash_test.sqlite"
        art_path = tmp_path / "artifacts"
        repo_path = tmp_path / "repo"
        repo_path.mkdir(parents=True, exist_ok=True)
        (repo_path / "orchestrator_gateway").mkdir()
        (repo_path / "tests").mkdir()
        (repo_path / "orchestrator_gateway" / "server.py").write_text(
            "def validate_request(payload):\n    return True, None\n"
        )
        (repo_path / "tests" / "test_gateway.py").write_text(
            "from orchestrator_gateway.server import validate_request\n"
            "def test_v(): assert validate_request({})[0] is True\n"
        )

        engine = WorkflowEngine(db_path)
        store = ArtifactStore(art_path)
        admission = AdmissionEvaluator()
        planner = ExecutionPlanner(include_investigation=True, include_review=True)
        router = EvidenceBasedRouter()
        validator = IndependentValidator(artifact_store=store)
        repair_ctrl = BoundedRepairController()

        worker = CrashWorker("worker-b65-0")
        workers = {
            "control-qwen3-coder-30b-awq": worker,
            "worker-b65-0": worker,
            "cand-phi4-fp8": worker,
            "worker-phi4": worker,
        }

        pipeline = HardenedRealRepoPipeline(
            engine=engine,
            artifact_store=store,
            admission_evaluator=admission,
            planner=planner,
            router=router,
            validator=validator,
            repair_controller=repair_ctrl,
            workers=workers,
            target_repo_dir=repo_path,
        )

        yield {
            "pipeline": pipeline,
            "engine": engine,
            "store": store,
            "tmp_path": tmp_path,
            "repo_path": repo_path,
        }


def test_crash_at_all_lifecycle_boundaries(crash_env):
    """Verifies that injecting hard crashes at any of the 11 lifecycle boundaries fails safely without state corruption."""
    pipeline = crash_env["pipeline"]
    engine = crash_env["engine"]
    compiler = WorkOrderCompiler()

    boundaries = list(LifecycleBoundary)
    assert len(boundaries) == 11

    for idx, boundary in enumerate(boundaries):
        task_id = f"crash-task-{idx:02d}-{boundary.value.lower()}"
        wo = compiler.compile(
            raw_text=f"Crash test at boundary {boundary.value}",
            source_channel="cli",
            source_reference=f"sess-{task_id}",
            repository_id="aihost",
            baseline_commit="da54731",
            proposed_mutation_paths=["orchestrator_gateway/server.py"],
        )
        object.__setattr__(wo, "work_order_id", task_id)
        pipeline.submit_and_admit(wo)

        # Register crash hook
        def crash_hook(w_id, ver):
            raise LifecycleInjectedCrashError(f"Simulated hard crash at boundary: {boundary.value}")

        pipeline.clear_crash_hooks()
        pipeline.register_crash_hook(boundary, crash_hook)

        # Execution should raise LifecycleInjectedCrashError
        if boundary in (LifecycleBoundary.DURING_EXPORT, LifecycleBoundary.POST_EXPORT_PRE_ACK):
            # These occur during export_deliverable
            pipeline.clear_crash_hooks()
            state = pipeline.execute_lifecycle(wo.work_order_id, wo.version)
            assert state == WorkOrderState.ACCEPTED
            # Now register hook for export
            pipeline.register_crash_hook(boundary, crash_hook)
            with pytest.raises(LifecycleInjectedCrashError):
                pipeline.export_deliverable(wo.work_order_id, wo.version, crash_env["tmp_path"] / f"exp_{task_id}")
        else:
            with pytest.raises(LifecycleInjectedCrashError):
                pipeline.execute_lifecycle(wo.work_order_id, wo.version)

        # Verify crash consistency: work order remains in valid state (not silently corrupted)
        row = engine.get_work_order(task_id, 1)
        assert row is not None
        assert row["state"] in (str(WorkOrderState.ADMITTED), str(WorkOrderState.ACCEPTED))


def test_startup_lease_reclaim_and_fencing(crash_env):
    """Verifies service startup reclaims abandoned leases and increments fencing token to reject zombie commits."""
    pipeline = crash_env["pipeline"]
    engine = crash_env["engine"]
    store = crash_env["store"]
    compiler = WorkOrderCompiler()

    wo = compiler.compile(
        raw_text="Test abandoned lease recovery",
        source_channel="cli",
        source_reference="sess-recover",
        repository_id="aihost",
        baseline_commit="da54731",
        proposed_mutation_paths=["orchestrator_gateway/server.py"],
    )
    object.__setattr__(wo, "work_order_id", "wo-abandoned-01")
    pipeline.submit_and_admit(wo)

    asgn = pipeline._find_or_create_assignment("wo-abandoned-01", 1, "step-patch")
    asgn_id = asgn["assignment_id"]
    
    # Worker 1 acquires lease with 1 second expiry
    stale_token = engine.acquire_lease(asgn_id, "zombie-worker", lease_seconds=1)
    time.sleep(1.05)  # Lease expires

    # Start persistent service (simulating daemon restart after crash)
    service = PersistentEngineeringService(
        engine=engine,
        artifact_store=store,
        pipeline=pipeline,
        poll_interval_seconds=0.1,
    )
    recovered = service._recover_stale_leases_on_startup()
    assert recovered >= 1

    # Stale zombie worker attempts to commit using old token
    with pytest.raises(WorkflowEngineError, match="Stale fencing token"):
        engine.complete_assignment(asgn_id, stale_token, "hash_zombie_patch")
