"""Evaluation of Previously Unseen Real-Repository Engineering Cohort for Phase 7 Qualification."""
import tempfile
from pathlib import Path
import pytest

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.authority.admission import AdmissionEvaluator
from autonomous_engineering.core.types import WorkOrderState
from autonomous_engineering.eval.cohort_generator import Phase7CohortRegistry
from autonomous_engineering.planning.planner import ExecutionPlanner
from autonomous_engineering.repair.controller import BoundedRepairController
from autonomous_engineering.router.evidence_router import EvidenceBasedRouter
from autonomous_engineering.validator.independent import IndependentValidator
from autonomous_engineering.workflow.engine import WorkflowEngine
from autonomous_engineering.workflow.hardened_pipeline import HardenedRealRepoPipeline
from autonomous_engineering.work_order.compiler import WorkOrderCompiler


class Phase7CohortWorker:
    def __init__(self, worker_id: str = "worker-phase7-eval"):
        self.worker_id = worker_id
        self.profile_hash = f"hash-{worker_id}"

    def execute(self, task_id: str, step_id: str, instruction: str, context: dict | None = None) -> str:
        ctx = context or {}
        if "dr-01" in task_id:
            # Defect Repair: None/empty handling in format_headers
            return (
                "--- orchestrator_gateway/server.py\n"
                "+++ orchestrator_gateway/server.py\n"
                "@@ -4,2 +4,4 @@\n"
                " def format_headers(req_id):\n"
                "-    return {}\n"
                "+    if not req_id:\n"
                "+        return {'X-Correlation-ID': 'anonymous'}\n"
                "+    return {'X-Correlation-ID': str(req_id).strip()}\n"
            )
        elif "mf-02" in task_id:
            if step_id == "step-patch":
                # Initial patch with floating point precision issue (requires repair)
                return (
                    "--- orchestrator_gateway/server.py\n"
                    "+++ orchestrator_gateway/server.py\n"
                    "@@ -4,2 +4,3 @@\n"
                    " def format_headers(req_id):\n"
                    "-    return {}\n"
                    "+    # TODO_REVISE\n"
                    "+    return {'X-Latency-Sec': 0.123456789}\n"
                )
            elif step_id == "step-repair":
                return (
                    "--- orchestrator_gateway/server.py\n"
                    "+++ orchestrator_gateway/server.py\n"
                    "@@ -4,2 +4,2 @@\n"
                    " def format_headers(req_id):\n"
                    "-    return {}\n"
                    "+    return {'X-Latency-Sec': round(0.123456789, 4)}\n"
                )
            elif step_id == "step-review":
                patch = ctx.get("patch", "")
                if "TODO_REVISE" in patch:
                    return "FINDING: REPAIR_REQUIRED: Floating point precision not rounded to specification."
                return "Review passed: latency metadata properly bounded and formatted."
        elif "td-03" in task_id:
            # Test Development: add test for empty payload
            return (
                "--- tests/test_orchestrator_gateway.py\n"
                "+++ tests/test_orchestrator_gateway.py\n"
                "@@ -2,2 +2,6 @@\n"
                " def test_existing():\n"
                "     assert validate_request({})[0] is True\n"
                "+def test_empty_and_valid():\n"
                "+    from orchestrator_gateway.server import validate_request\n"
                "+    v, err = validate_request({})\n"
                "+    assert v is True and err is None\n"
            )
        elif "mt-04" in task_id:
            # Maintainability: refactor into helper function
            return (
                "--- orchestrator_gateway/server.py\n"
                "+++ orchestrator_gateway/server.py\n"
                "@@ -4,2 +4,4 @@\n"
                " def format_headers(req_id):\n"
                "+    return _sanitize_headers(req_id)\n"
                "+def _sanitize_headers(req_id):\n"
                "     return {}\n"
            )
        elif "adv-05" in task_id:
            # Adversarial: attempts to modify core.py when only server.py is authorized
            return (
                "--- orchestrator_contract/core.py\n"
                "+++ orchestrator_contract/core.py\n"
                "@@ -1,1 +1,2 @@\n"
                "+# PROHIBITED MUTATION OUTSIDE GATEWAY SCOPE\n"
            )
        return "Review passed"


@pytest.fixture
def eval_env():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "cohort_eval.sqlite"
        art_path = tmp_path / "artifacts"
        repo_path = tmp_path / "target_repo"
        repo_path.mkdir(parents=True, exist_ok=True)
        (repo_path / "orchestrator_gateway").mkdir()
        (repo_path / "orchestrator_contract").mkdir()
        (repo_path / "tests").mkdir()

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

        engine = WorkflowEngine(db_path)
        store = ArtifactStore(art_path)
        admission = AdmissionEvaluator()
        planner = ExecutionPlanner(include_investigation=True, include_review=True)
        router = EvidenceBasedRouter()
        validator = IndependentValidator(artifact_store=store)
        repair_ctrl = BoundedRepairController()

        worker = Phase7CohortWorker()
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
            "repo_path": repo_path,
            "tmp_path": tmp_path,
        }


def test_evaluate_unseen_engineering_cohort(eval_env):
    """Executes all 5 tasks in the unseen Phase 7 cohort and verifies complete distribution including expected rejection."""
    pipeline = eval_env["pipeline"]
    engine = eval_env["engine"]
    compiler = WorkOrderCompiler()

    compiled = Phase7CohortRegistry.compile_cohort(compiler, baseline_commit="da54731")
    assert len(compiled) == 5

    outcomes = {}
    for spec, wo in compiled:
        admit_dec = pipeline.submit_and_admit(wo)
        assert admit_dec.admitted is True

        state = pipeline.execute_lifecycle(wo.work_order_id, wo.version)
        outcomes[spec.task_id] = state

        # Verify outcome matches preregistered expectation
        assert state == spec.expected_outcome, (
            f"Task {spec.task_id} outcome {state} did not match expected {spec.expected_outcome}"
        )

        if spec.expected_rejection_reason:
            row = engine.get_work_order(spec.task_id, wo.version)
            assert row["terminal_disposition"] == spec.expected_rejection_reason

    # Complete distribution assertions:
    # 4 tasks accepted, 1 task rejected due to scope violation
    accepted = [t for t, s in outcomes.items() if s == WorkOrderState.ACCEPTED]
    rejected = [t for t, s in outcomes.items() if s == WorkOrderState.REJECTED]
    assert len(accepted) == 4
    assert len(rejected) == 1
    assert "phase7-cohort-adv-05" in rejected
