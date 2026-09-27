"""Tests for Adversarial Work-Order Authority, Dynamic Scope Revisions, and Point-of-Use Verification."""
import tempfile
from pathlib import Path
import pytest

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.authority.admission import AdmissionEvaluator
from autonomous_engineering.core.types import (
    ArtifactType,
    RevisionKind,
    TaskStepState,
    WorkOrderState,
)
from autonomous_engineering.planning.models import ExecutionPlan, TaskStepDefinition
from autonomous_engineering.planning.planner import ExecutionPlanner
from autonomous_engineering.repair.controller import BoundedRepairController
from autonomous_engineering.router.evidence_router import EvidenceBasedRouter
from autonomous_engineering.validator.independent import IndependentValidator
from autonomous_engineering.workflow.engine import WorkflowEngine, WorkflowEngineError
from autonomous_engineering.workflow.hardened_pipeline import (
    HardenedRealRepoPipeline,
    ScopeViolationError,
)
from autonomous_engineering.work_order.compiler import WorkOrderCompiler
from autonomous_engineering.work_order.versioning import WorkOrderRevisionManager


class AdversarialWorker:
    def __init__(self, out_of_scope: bool = False):
        self.worker_id = "worker-adversarial"
        self.profile_hash = "hash-adv"
        self.out_of_scope = out_of_scope

    def execute(self, task_id: str, step_id: str, instruction: str, context: dict | None = None) -> str:
        if step_id == "step-patch":
            if self.out_of_scope:
                # Malicious patch modifying unauthorized orchestrator_contract/core.py
                return (
                    "--- orchestrator_contract/core.py\n"
                    "+++ orchestrator_contract/core.py\n"
                    "@@ -1,1 +1,2 @@\n"
                    "+# UNAUTHORIZED MUTATION\n"
                )
            return (
                "--- orchestrator_gateway/server.py\n"
                "+++ orchestrator_gateway/server.py\n"
                "@@ -1,2 +1,3 @@\n"
                " def validate_request(payload):\n"
                "+    # authorized\n"
                "     return True, None\n"
            )
        return "Review passed"


@pytest.fixture
def adv_env():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "adv.sqlite"
        art_path = tmp_path / "artifacts"
        repo_path = tmp_path / "repo"
        repo_path.mkdir(parents=True, exist_ok=True)
        (repo_path / "orchestrator_gateway").mkdir()
        (repo_path / "orchestrator_contract").mkdir()
        (repo_path / "tests").mkdir()
        (repo_path / "orchestrator_gateway" / "server.py").write_text("def validate_request(payload):\n    return True, None\n")
        (repo_path / "orchestrator_contract" / "core.py").write_text("def parse_contract(): pass\n")
        (repo_path / "tests" / "test_gateway.py").write_text("def test_ok(): pass\n")

        engine = WorkflowEngine(db_path)
        store = ArtifactStore(art_path)
        admission = AdmissionEvaluator()
        planner = ExecutionPlanner()
        router = EvidenceBasedRouter()
        validator = IndependentValidator(artifact_store=store)
        repair_ctrl = BoundedRepairController()

        yield {
            "engine": engine,
            "store": store,
            "admission": admission,
            "planner": planner,
            "router": router,
            "validator": validator,
            "repair_ctrl": repair_ctrl,
            "repo_path": repo_path,
            "tmp_path": tmp_path,
        }


def test_scope_violation_rejection(adv_env):
    """Verifies that an out-of-scope patch modification is rejected point-of-use with fail-closed status."""
    adv_worker = AdversarialWorker(out_of_scope=True)
    workers = {
        "control-qwen3-coder-30b-awq": adv_worker,
        "worker-b65-0": adv_worker,
    }
    pipeline = HardenedRealRepoPipeline(
        engine=adv_env["engine"],
        artifact_store=adv_env["store"],
        admission_evaluator=adv_env["admission"],
        planner=adv_env["planner"],
        router=adv_env["router"],
        validator=adv_env["validator"],
        repair_controller=adv_env["repair_ctrl"],
        workers=workers,
        target_repo_dir=adv_env["repo_path"],
    )

    compiler = WorkOrderCompiler()
    # Authorized strictly to orchestrator_gateway/server.py
    wo = compiler.compile(
        raw_text="Restricted mutation",
        source_channel="cli",
        source_reference="sess-adv-scope",
        repository_id="aihost",
        baseline_commit="da54731",
        proposed_mutation_paths=["orchestrator_gateway/server.py"],
    )
    object.__setattr__(wo, "work_order_id", "wo-adv-scope-01")
    pipeline.submit_and_admit(wo)

    state = pipeline.execute_lifecycle(wo.work_order_id, wo.version)
    assert state == WorkOrderState.REJECTED

    row = adv_env["engine"].get_work_order("wo-adv-scope-01", 1)
    assert row["terminal_disposition"] == "REJECTED_SCOPE_VIOLATION"


def test_cancellation_and_revocation_at_point_of_use(adv_env):
    """Verifies that supervisor cancellation invalidates active worker leases and blocks delayed commits."""
    normal_worker = AdversarialWorker(out_of_scope=False)
    workers = {
        "control-qwen3-coder-30b-awq": normal_worker,
        "worker-b65-0": normal_worker,
    }
    pipeline = HardenedRealRepoPipeline(
        engine=adv_env["engine"],
        artifact_store=adv_env["store"],
        admission_evaluator=adv_env["admission"],
        planner=adv_env["planner"],
        router=adv_env["router"],
        validator=adv_env["validator"],
        repair_controller=adv_env["repair_ctrl"],
        workers=workers,
        target_repo_dir=adv_env["repo_path"],
    )
    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Test cancellation",
        source_channel="cli",
        source_reference="sess-cancel",
        repository_id="aihost",
        baseline_commit="da54731",
        proposed_mutation_paths=["orchestrator_gateway/server.py"],
    )
    object.__setattr__(wo, "work_order_id", "wo-cancel-01")
    pipeline.submit_and_admit(wo)

    asgn = pipeline._find_or_create_assignment("wo-cancel-01", 1, "step-patch")
    asgn_id = asgn["assignment_id"]
    token = adv_env["engine"].acquire_lease(asgn_id, "worker-1", lease_seconds=60)

    # Supervisor issues cancellation
    cancel_wo = WorkOrderRevisionManager.create_revision(
        current_wo=wo,
        change_reason="Emergency operator cancellation",
        author="supervisor",
        revision_kind=RevisionKind.CANCELLATION,
    )
    adv_env["engine"].supersede_work_order(wo.work_order_id, wo.version)

    # Worker attempts to commit result using previously acquired token
    with pytest.raises(WorkflowEngineError, match="superseded"):
        adv_env["engine"].complete_assignment(asgn_id, token, "hash_patch")


def test_rapid_revisions_monotonic_fencing(adv_env):
    """Verifies that multiple rapid revisions consecutively revoke previous tokens."""
    engine = adv_env["engine"]
    compiler = WorkOrderCompiler()

    wo_v1 = compiler.compile(
        raw_text="V1",
        source_channel="cli",
        source_reference="sess-rev",
        repository_id="aihost",
        baseline_commit="da54731",
        proposed_mutation_paths=["orchestrator_gateway/server.py"],
    )
    object.__setattr__(wo_v1, "work_order_id", "wo-rapid-01")
    engine.register_work_order(wo_v1)

    plan = adv_env["planner"].create_plan(wo_v1)
    asgn_id = engine.initialize_plan(plan)[0]

    token_v1 = engine.acquire_lease(asgn_id, "w1")

    # Revision to v2
    wo_v2 = WorkOrderRevisionManager.create_revision(
        current_wo=wo_v1,
        change_reason="Revision 2",
        author="supervisor",
        revision_kind=RevisionKind.SCOPE_RESTRICTION,
    )
    engine.supersede_work_order(wo_v1.work_order_id, 1)

    # Revision to v3
    wo_v3 = WorkOrderRevisionManager.create_revision(
        current_wo=wo_v2,
        change_reason="Revision 3",
        author="supervisor",
        revision_kind=RevisionKind.CLARIFICATION,
    )

    # Ensure v1 token fails
    with pytest.raises(WorkflowEngineError, match="superseded"):
        engine.complete_assignment(asgn_id, token_v1, "hash_stale")
