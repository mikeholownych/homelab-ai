"""Tests for Persistent Engineering Service, Unattended Queueing, and Crash Recovery."""
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
from autonomous_engineering.workflow.real_repo_pipeline import RealRepoEngineeringPipeline
from autonomous_engineering.work_order.compiler import WorkOrderCompiler


class SimpleWorker:
    def __init__(self, worker_id: str):
        self.worker_id = worker_id
        self.profile_hash = f"hash-{worker_id}"

    def execute(self, task_id: str, step_id: str, instruction: str, context: dict | None = None) -> str:
        if step_id == "step-patch":
            return "--- src/mod.py\n+++ src/mod.py\n@@ -1,1 +1,2 @@\n+# added\n"
        return "Review passed"


@pytest.fixture
def service_env():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "service.sqlite"
        art_path = tmp_path / "artifacts"
        repo_path = tmp_path / "repo"
        repo_path.mkdir(parents=True, exist_ok=True)
        (repo_path / "src").mkdir()
        (repo_path / "tests").mkdir()
        (repo_path / "src" / "mod.py").write_text("def fn(): pass\n")
        (repo_path / "tests" / "test_mod.py").write_text("def test_fn(): pass\n")

        engine = WorkflowEngine(db_path)
        store = ArtifactStore(art_path)
        admission = AdmissionEvaluator()
        planner = ExecutionPlanner()
        router = EvidenceBasedRouter()
        validator = IndependentValidator(artifact_store=store)
        repair_ctrl = BoundedRepairController()

        worker = SimpleWorker("worker-b65-0")
        workers = {
            "control-qwen3-coder-30b-awq": worker,
            "worker-b65-0": worker,
        }

        pipeline = RealRepoEngineeringPipeline(
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

        service = PersistentEngineeringService(
            engine=engine,
            artifact_store=store,
            pipeline=pipeline,
            poll_interval_seconds=0.05,
        )

        yield {
            "service": service,
            "engine": engine,
            "pipeline": pipeline,
            "tmp_path": tmp_path,
        }


def test_persistent_service_process_queue(service_env):
    service = service_env["service"]
    pipeline = service_env["pipeline"]
    engine = service_env["engine"]

    compiler = WorkOrderCompiler()
    wo1 = compiler.compile(
        raw_text="Task 1",
        source_channel="cli",
        source_reference="sess-q-1",
        repository_id="repo-1",
        baseline_commit="commit-1",
        proposed_mutation_paths=["src/mod.py"],
    )
    pipeline.submit_and_admit(wo1)

    wo2 = compiler.compile(
        raw_text="Task 2",
        source_channel="cli",
        source_reference="sess-q-2",
        repository_id="repo-1",
        baseline_commit="commit-1",
        proposed_mutation_paths=["src/mod.py"],
    )
    pipeline.submit_and_admit(wo2)

    # Process queue
    processed = service.process_pending_work_orders()
    assert processed == 2
    assert service.metrics.total_work_orders_processed == 2
    assert service.metrics.accepted_work_orders == 2


def test_service_crash_and_restart_recovery(service_env):
    service = service_env["service"]
    engine = service_env["engine"]
    pipeline = service_env["pipeline"]

    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Crash recovery task",
        source_channel="cli",
        source_reference="sess-crash",
        repository_id="repo-crash",
        baseline_commit="commit-1",
        proposed_mutation_paths=["src/mod.py"],
    )
    pipeline.submit_and_admit(wo)
    asgn = pipeline._find_or_create_assignment(wo.work_order_id, wo.version, "step-patch")

    # Simulate an abandoned lease by a worker process that died
    token = engine.acquire_lease(asgn["assignment_id"], "worker-dead", lease_seconds=1)
    time.sleep(1.05)  # Lease expires

    # Service restarts and runs crash recovery
    recovered = service._recover_stale_leases_on_startup()
    assert recovered == 1
    assert service.metrics.leases_recovered == 1

    # Stale worker attempts to commit using expired/superseded token
    with pytest.raises(WorkflowEngineError, match="Stale fencing token|not found|revoked"):
        engine.complete_assignment(asgn["assignment_id"], token, output_artifact_hash="hash_patch_stale")
