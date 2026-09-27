"""Tests for Deliverable Custody, Cryptographic Manifests, and TOCTOU Protection."""
import hashlib
import tempfile
from pathlib import Path
import pytest

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.authority.admission import AdmissionEvaluator
from autonomous_engineering.core.types import WorkOrderState
from autonomous_engineering.planning.planner import ExecutionPlanner
from autonomous_engineering.repair.controller import BoundedRepairController
from autonomous_engineering.router.evidence_router import EvidenceBasedRouter
from autonomous_engineering.validator.independent import IndependentValidator
from autonomous_engineering.workflow.engine import WorkflowEngine
from autonomous_engineering.workflow.hardened_pipeline import (
    HardenedRealRepoPipeline,
    TOCTOUMutationError,
)
from autonomous_engineering.work_order.compiler import WorkOrderCompiler


class DeliverableTestWorker:
    def __init__(self):
        self.worker_id = "worker-deliverable"
        self.profile_hash = "hash-deliv"

    def execute(self, task_id: str, step_id: str, instruction: str, context: dict | None = None) -> str:
        if step_id == "step-patch":
            return (
                "--- orchestrator_gateway/server.py\n"
                "+++ orchestrator_gateway/server.py\n"
                "@@ -1,2 +1,3 @@\n"
                " def validate_request(payload):\n"
                "+    # deliverable custody valid\n"
                "     return True, None\n"
            )
        return "Review passed"


@pytest.fixture
def custody_env():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "custody.sqlite"
        art_path = tmp_path / "artifacts"
        repo_path = tmp_path / "repo"
        repo_path.mkdir(parents=True, exist_ok=True)
        (repo_path / "orchestrator_gateway").mkdir()
        (repo_path / "tests").mkdir()
        (repo_path / "orchestrator_gateway" / "server.py").write_text("def validate_request(payload):\n    return True, None\n")
        (repo_path / "tests" / "test_g.py").write_text("def test_ok(): pass\n")

        engine = WorkflowEngine(db_path)
        store = ArtifactStore(art_path)
        admission = AdmissionEvaluator()
        planner = ExecutionPlanner()
        router = EvidenceBasedRouter()
        validator = IndependentValidator(artifact_store=store)
        repair_ctrl = BoundedRepairController()

        worker = DeliverableTestWorker()
        workers = {
            "control-qwen3-coder-30b-awq": worker,
            "worker-b65-0": worker,
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
            "repo_path": repo_path,
            "tmp_path": tmp_path,
        }


def test_deliverable_bundle_integrity_and_guide(custody_env):
    """Verifies that an accepted deliverable bundle has all required artifacts, hashes, and integration guide."""
    pipeline = custody_env["pipeline"]
    tmp_path = custody_env["tmp_path"]
    compiler = WorkOrderCompiler()

    wo = compiler.compile(
        raw_text="Deliverable verification",
        source_channel="cli",
        source_reference="s-deliv",
        repository_id="aihost",
        baseline_commit="da54731",
        proposed_mutation_paths=["orchestrator_gateway/server.py"],
    )
    object.__setattr__(wo, "work_order_id", "wo-deliv-01")
    pipeline.submit_and_admit(wo)

    state = pipeline.execute_lifecycle(wo.work_order_id, wo.version)
    assert state == WorkOrderState.ACCEPTED

    export_dir = tmp_path / "exports" / wo.work_order_id
    bundle = pipeline.export_deliverable(wo.work_order_id, wo.version, export_dir)

    assert Path(bundle.patch_path).exists()
    assert Path(bundle.manifest_path).exists()
    assert (Path(bundle.export_directory) / "INTEGRATION_GUIDE.md").exists()

    # Verify manifest hashes match actual artifact content
    from autonomous_engineering.core.crypto import content_hash
    manifest_lines = Path(bundle.manifest_path).read_text().splitlines()
    for line in manifest_lines:
        digest, fname = line.split()
        target_f = Path(bundle.export_directory) / fname
        assert target_f.exists()
        calc_digest = content_hash(target_f.read_bytes())
        assert digest == calc_digest, f"Manifest hash mismatch for {fname}"


def test_toctou_mutation_rejection(custody_env):
    """Verifies that if target repository changes between validation and export, deliverable export aborts."""
    pipeline = custody_env["pipeline"]
    repo_path = custody_env["repo_path"]
    tmp_path = custody_env["tmp_path"]
    compiler = WorkOrderCompiler()

    wo = compiler.compile(
        raw_text="TOCTOU mutation test",
        source_channel="cli",
        source_reference="s-toctou",
        repository_id="aihost",
        baseline_commit="da54731",
        proposed_mutation_paths=["orchestrator_gateway/server.py"],
    )
    object.__setattr__(wo, "work_order_id", "wo-toctou-01")
    pipeline.submit_and_admit(wo)

    state = pipeline.execute_lifecycle(wo.work_order_id, wo.version)
    assert state == WorkOrderState.ACCEPTED

    # Tamper with the repository after validation has succeeded
    (repo_path / "orchestrator_gateway" / "server.py").write_text("# UNAUTHORIZED TOCTOU MUTATION\n")

    # Attempting to export deliverable must detect mutation and abort
    with pytest.raises(TOCTOUMutationError, match="Target repository was mutated after validation"):
        pipeline.export_deliverable(wo.work_order_id, wo.version, tmp_path / "exports" / "toctou_fail")
