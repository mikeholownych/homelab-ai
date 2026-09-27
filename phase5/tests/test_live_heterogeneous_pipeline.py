"""Tests for End-to-End Heterogeneous Engineering Execution Pipeline."""
import tempfile
from pathlib import Path
import pytest

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.authority.admission import AdmissionEvaluator
from autonomous_engineering.core.types import WorkOrderState
from autonomous_engineering.planning.planner import ExecutionPlanner
from autonomous_engineering.repair.controller import BoundedRepairController
from autonomous_engineering.router.evidence_router import EvidenceBasedRouter, RoutingTopology
from autonomous_engineering.validator.independent import IndependentValidator
from autonomous_engineering.workflow.engine import WorkflowEngine
from autonomous_engineering.workflow.heterogeneous_engine import HeterogeneousEngineeringPipeline
from autonomous_engineering.work_order.compiler import WorkOrderCompiler


class MockWorker:
    def __init__(self, worker_id: str, patch_content: str = "") -> None:
        self.worker_id = worker_id
        self.patch_content = patch_content

    def execute(self, task_id: str, step_id: str, instruction: str, context: dict | None = None) -> str:
        return self.patch_content


@pytest.fixture
def pipeline_env():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "test_engine.sqlite"
        art_path = tmp_path / "artifacts"
        repo_path = tmp_path / "repo"
        repo_path.mkdir(parents=True, exist_ok=True)
        (repo_path / "src").mkdir()
        (repo_path / "tests").mkdir()

        # Simple fixture repo
        (repo_path / "src" / "math_util.py").write_text("def add(a, b):\n    return a + b\n")
        (repo_path / "tests" / "test_math.py").write_text(
            "from src.math_util import add\ndef test_add():\n    assert add(1, 2) == 3\n"
        )

        engine = WorkflowEngine(db_path)
        store = ArtifactStore(art_path)
        admission = AdmissionEvaluator()
        planner = ExecutionPlanner()
        router = EvidenceBasedRouter()
        validator = IndependentValidator(artifact_store=store)
        repair_ctrl = BoundedRepairController()

        # Workers
        author_worker = MockWorker(
            worker_id="worker-b65-0",
            patch_content="--- src/math_util.py\n+++ src/math_util.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a + b\n+    return a + b\n",
        )
        phi4_worker = MockWorker(
            worker_id="worker-phi4",
        )

        workers = {
            "control-qwen3-coder-30b-awq": author_worker,
            "worker-b65-0": author_worker,
            "cand-phi4-fp8": phi4_worker,
            "worker-phi4": phi4_worker,
        }

        pipeline = HeterogeneousEngineeringPipeline(
            engine=engine,
            artifact_store=store,
            admission_evaluator=admission,
            planner=planner,
            router=router,
            validator=validator,
            repair_controller=repair_ctrl,
            workers=workers,
            baseline_repo_dir=repo_path,
        )

        yield {
            "pipeline": pipeline,
            "engine": engine,
            "store": store,
            "repo_path": repo_path,
            "tmp_path": tmp_path,
        }


def test_complete_heterogeneous_lifecycle(pipeline_env):
    pipeline = pipeline_env["pipeline"]
    repo_path = pipeline_env["repo_path"]
    tmp_path = pipeline_env["tmp_path"]

    # 1. Human Work Order Submission & Compilation
    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Fix defect in math_util.py to ensure correct addition",
        source_channel="cli",
        source_reference="sess-1",
        repository_id="test-repo",
        baseline_commit="commit-1",
        proposed_mutation_paths=["src/math_util.py"],
    )

    # 2. Admission
    admission = pipeline.submit_and_admit(wo)
    assert admission.admitted is True
    wo_id = admission.admitted_work_order.work_order_id
    version = admission.admitted_work_order.version

    # 3. Complete Heterogeneous Execution
    terminal_state = pipeline.execute_lifecycle(wo_id, version, force_topology=RoutingTopology.HETEROGENEOUS)
    assert terminal_state == WorkOrderState.ACCEPTED

    # 4. Deliverable Export
    export_dir = tmp_path / "exports" / wo_id
    bundle = pipeline.export_deliverable(wo_id, version, export_dir)

    assert bundle.work_order_id == wo_id
    assert (export_dir / "deliverable.patch").exists()
    assert (export_dir / "review_report.json").exists()
    assert (export_dir / "routing_decisions.json").exists()
    assert (export_dir / "manifest.sha256").exists()
    assert len(bundle.deliverable_hash) == 64
