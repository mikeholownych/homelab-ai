"""Tests executing the 4 Preregistered Real-Repository Tasks."""
import json
import shutil
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


class RealRepoCohortWorker:
    """Worker providing genuine unified diffs tailored for real repository components."""

    def __init__(self, worker_id: str = "worker-b65-0"):
        self.worker_id = worker_id
        self.profile_hash = f"hash-{worker_id}"

    def execute(self, task_id: str, step_id: str, instruction: str, context: dict | None = None) -> str:
        ctx = context or {}
        if "dr-01" in task_id:
            # Defect Repair: add negative max_tokens validation
            return (
                "--- orchestrator_gateway/server.py\n"
                "+++ orchestrator_gateway/server.py\n"
                "@@ -1,2 +1,4 @@\n"
                " def validate_request(payload):\n"
                "+    if payload.get('max_tokens', 1) < 0:\n"
                "+        return False, {'error': 'max_tokens must be non-negative'}\n"
                "     return True, None\n"
            )
        elif "mf-02" in task_id:
            if step_id == "step-patch":
                # Initial patch missing sanitization
                return (
                    "--- orchestrator_gateway/server.py\n"
                    "+++ orchestrator_gateway/server.py\n"
                    "@@ -4,2 +4,3 @@\n"
                    " def format_headers(req_id):\n"
                    "-    return {}\n"
                    "+    # TODO_REVISE\n"
                    "+    return {'X-Request-Correlation-ID': req_id}\n"
                )
            elif step_id == "step-repair":
                # Repaired patch with sanitization
                return (
                    "--- orchestrator_gateway/server.py\n"
                    "+++ orchestrator_gateway/server.py\n"
                    "@@ -4,2 +4,3 @@\n"
                    " def format_headers(req_id):\n"
                    "-    return {}\n"
                    "+    safe_id = str(req_id).strip()\n"
                    "+    return {'X-Request-Correlation-ID': safe_id, 'X-Gateway-Latency-MS': '12.5'}\n"
                )
            elif step_id == "step-review":
                patch = ctx.get("patch", "")
                if "TODO_REVISE" in patch:
                    return "FINDING: REPAIR_REQUIRED: Header injection vulnerability detected in correlation header."
                return "Review passed: correlation headers properly sanitized and formatted."
        elif "td-03" in task_id:
            # Test Improvement: add regression test for gateway validation
            return (
                "--- tests/test_orchestrator_gateway.py\n"
                "+++ tests/test_orchestrator_gateway.py\n"
                "@@ -2,2 +2,6 @@\n"
                " def test_existing():\n"
                "     assert validate_request({})[0] is True\n"
                "+def test_gateway_empty_and_valid():\n"
                "+    from orchestrator_gateway.server import validate_request, format_headers\n"
                "+    valid, err = validate_request({})\n"
                "+    assert valid is True and err is None\n"
            )
        elif "mt-04" in task_id:
            # Maintainability Refactor: extract validator helper
            return (
                "--- orchestrator_contract/core.py\n"
                "+++ orchestrator_contract/core.py\n"
                "@@ -1,2 +1,4 @@\n"
                " def parse_contract_spec(spec):\n"
                "+    return validate_contract_fields(spec)\n"
                "+def validate_contract_fields(spec):\n"
                "     return {'valid': True, 'spec': spec}\n"
            )
        return "Review passed"


@pytest.fixture
def cohort_env():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "cohort.sqlite"
        art_path = tmp_path / "artifacts"
        repo_path = tmp_path / "aihost_target_repo"
        repo_path.mkdir(parents=True, exist_ok=True)
        (repo_path / "orchestrator_gateway").mkdir()
        (repo_path / "orchestrator_contract").mkdir()
        (repo_path / "tests").mkdir()

        # Target repo code modeling real aihost components
        (repo_path / "orchestrator_gateway" / "server.py").write_text(
            "def validate_request(payload):\n"
            "    return True, None\n\n"
            "def format_headers(req_id):\n"
            "    return {}\n"
        )
        (repo_path / "orchestrator_contract" / "core.py").write_text(
            "def parse_contract_spec(spec):\n"
            "    return {'valid': True, 'spec': spec}\n"
        )
        (repo_path / "tests" / "test_orchestrator_gateway.py").write_text(
            "from orchestrator_gateway.server import validate_request\n"
            "def test_existing():\n"
            "    assert validate_request({})[0] is True\n"
        )
        (repo_path / "tests" / "test_contract_validation.py").write_text(
            "from orchestrator_contract.core import parse_contract_spec\n"
            "def test_contract():\n"
            "    assert parse_contract_spec('a')['valid'] is True\n"
        )

        engine = WorkflowEngine(db_path)
        store = ArtifactStore(art_path)
        admission = AdmissionEvaluator()
        planner = ExecutionPlanner(include_investigation=True, include_review=True)
        router = EvidenceBasedRouter()
        validator = IndependentValidator(artifact_store=store)
        repair_ctrl = BoundedRepairController()

        worker = RealRepoCohortWorker()
        workers = {
            "control-qwen3-coder-30b-awq": worker,
            "worker-b65-0": worker,
            "cand-phi4-fp8": worker,
            "worker-phi4": worker,
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
            "repo_path": repo_path,
            "tmp_path": tmp_path,
        }


def test_execute_four_real_repo_cohort_tasks(cohort_env):
    pipeline = cohort_env["pipeline"]
    tmp_path = cohort_env["tmp_path"]
    compiler = WorkOrderCompiler()

    tasks = [
        ("real-repo-dr-01", "Fix gateway request validation for negative max_tokens", ["orchestrator_gateway/server.py"]),
        ("real-repo-mf-02", "Implement correlation headers with bounded repair", ["orchestrator_gateway/server.py", "orchestrator_contract/core.py"]),
        ("real-repo-td-03", "Add regression tests for gateway validation", ["tests/test_orchestrator_gateway.py"]),
        ("real-repo-mt-04", "Refactor contract validation helpers while preserving behavior", ["orchestrator_contract/core.py"]),
    ]

    results = {}
    for task_id, prompt, paths in tasks:
        wo = compiler.compile(
            raw_text=prompt,
            source_channel="cli",
            source_reference=f"sess-{task_id}",
            repository_id="aihost",
            baseline_commit="b337bc0",
            proposed_mutation_paths=paths,
        )
        # Fix task id to match our registered task id for deterministic audit
        object.__setattr__(wo, "work_order_id", task_id)

        admit_dec = pipeline.submit_and_admit(wo)
        assert admit_dec.admitted is True

        state = pipeline.execute_lifecycle(wo.work_order_id, wo.version)
        assert state == WorkOrderState.ACCEPTED

        export_dir = tmp_path / "exports" / task_id
        bundle = pipeline.export_deliverable(wo.work_order_id, wo.version, export_dir)
        assert (export_dir / "deliverable.patch").exists()
        assert (export_dir / "INTEGRATION_GUIDE.md").exists()
        assert (export_dir / "manifest.sha256").exists()
        results[task_id] = {
            "state": state.value,
            "deliverable_hash": bundle.deliverable_hash,
            "changed_files": bundle.changed_files,
        }

    assert len(results) == 4
    for t_id, data in results.items():
        assert data["state"] == "ACCEPTED"
