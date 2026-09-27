"""Tests for Real-Repository Engineering Pipeline with Bounded Repair and CAS Export."""
import json
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
from autonomous_engineering.workflow.real_repo_pipeline import RealRepoEngineeringPipeline
from autonomous_engineering.work_order.compiler import WorkOrderCompiler


class MockRealRepoWorker:
    def __init__(self, worker_id: str, patch_content: str = "", repair_content: str = "") -> None:
        self.worker_id = worker_id
        self.profile_hash = f"hash-{worker_id}"
        self.patch_content = patch_content
        self.repair_content = repair_content

    def execute(self, task_id: str, step_id: str, instruction: str, context: dict | None = None) -> str:
        if step_id == "step-patch":
            return self.patch_content
        elif step_id == "step-repair":
            return self.repair_content or self.patch_content
        elif step_id == "step-review":
            # If the patch has not yet been repaired, report a finding triggering repair
            patch = (context or {}).get("patch", "")
            if "TODO_REVISE" in patch:
                return "FINDING: REPAIR_REQUIRED: Header sanitization missing in proposed patch."
            return "Review passed: patch strictly conforms to authorized path scope and acceptance criteria."
        return "OK"


@pytest.fixture
def real_repo_pipeline_env():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "test_engine.sqlite"
        art_path = tmp_path / "artifacts"
        repo_path = tmp_path / "repo"
        repo_path.mkdir(parents=True, exist_ok=True)
        (repo_path / "orchestrator_gateway").mkdir()
        (repo_path / "tests").mkdir()

        # Fixture repository modeling orchestrator_gateway
        (repo_path / "orchestrator_gateway" / "server.py").write_text(
            "def handle_request(req):\n    return {'status': 200}\n"
        )
        (repo_path / "tests" / "test_server.py").write_text(
            "from orchestrator_gateway.server import handle_request\n"
            "def test_handle():\n"
            "    res = handle_request({})\n"
            "    assert res['status'] == 200\n"
        )

        engine = WorkflowEngine(db_path)
        store = ArtifactStore(art_path)
        admission = AdmissionEvaluator()
        planner = ExecutionPlanner(include_investigation=True, include_review=True)
        router = EvidenceBasedRouter()
        validator = IndependentValidator(artifact_store=store)
        repair_ctrl = BoundedRepairController()

        patch_1 = (
            "--- orchestrator_gateway/server.py\n"
            "+++ orchestrator_gateway/server.py\n"
            "@@ -1,2 +1,3 @@\n"
            " def handle_request(req):\n"
            "+    # TODO_REVISE\n"
            "     return {'status': 200}\n"
        )
        patch_repaired = (
            "--- orchestrator_gateway/server.py\n"
            "+++ orchestrator_gateway/server.py\n"
            "@@ -1,2 +1,3 @@\n"
            " def handle_request(req):\n"
            "+    req_id = req.get('id', 'anon')\n"
            "     return {'status': 200}\n"
        )

        author_worker = MockRealRepoWorker(
            worker_id="worker-b65-0",
            patch_content=patch_1,
            repair_content=patch_repaired,
        )
        reviewer_worker = MockRealRepoWorker(worker_id="worker-phi4")

        workers = {
            "control-qwen3-coder-30b-awq": author_worker,
            "worker-b65-0": author_worker,
            "cand-phi4-fp8": reviewer_worker,
            "worker-phi4": reviewer_worker,
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

        yield {
            "pipeline": pipeline,
            "engine": engine,
            "store": store,
            "repo_path": repo_path,
            "tmp_path": tmp_path,
        }


def test_real_repo_pipeline_lifecycle_with_repair_and_cas_export(real_repo_pipeline_env):
    pipeline = real_repo_pipeline_env["pipeline"]
    tmp_path = real_repo_pipeline_env["tmp_path"]

    # 1. Submit work order
    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Harden gateway request handling and add correlation tracking",
        source_channel="cli",
        source_reference="sess-real-1",
        repository_id="aihost-gateway",
        baseline_commit="commit-base-001",
        proposed_mutation_paths=["orchestrator_gateway/server.py"],
    )

    admission = pipeline.submit_and_admit(wo)
    assert admission.admitted is True

    # 2. Execute full lifecycle (exercises investigation, review finding, bounded repair, validation, disposition)
    state = pipeline.execute_lifecycle(wo.work_order_id, wo.version)
    assert state == WorkOrderState.ACCEPTED

    # 3. Export CAS deliverable bundle
    export_dir = tmp_path / "exports" / wo.work_order_id
    bundle = pipeline.export_deliverable(wo.work_order_id, wo.version, export_dir)

    assert bundle.work_order_id == wo.work_order_id
    assert len(bundle.deliverable_hash) == 64
    assert (export_dir / "deliverable.patch").exists()
    assert (export_dir / "review_report.json").exists()
    assert (export_dir / "routing_decisions.json").exists()
    assert (export_dir / "INTEGRATION_GUIDE.md").exists()
    assert (export_dir / "manifest.sha256").exists()
    assert "orchestrator_gateway/server.py" in bundle.changed_files
