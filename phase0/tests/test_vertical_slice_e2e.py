"""End-to-End Vertical Slice Tests for Autonomous Engineering System."""
from pathlib import Path
import pytest

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.authority.admission import AdmissionEvaluator
from autonomous_engineering.core.types import (
    ArtifactType,
    ValidationStatus,
    WorkerHealthStatus,
    WorkOrderState,
)
from autonomous_engineering.interface.adapter import HumanInterfaceAdapter
from autonomous_engineering.orchestrator import OrchestratorControlPlane
from autonomous_engineering.planning.planner import ExecutionPlanner
from autonomous_engineering.registry.models import (
    EmpiricalSkillRecord,
    HardwareTarget,
    RuntimeConfig,
    WorkerCapabilityProfile,
)
from autonomous_engineering.registry.registry import WorkerCapabilityRegistry
from autonomous_engineering.repair.controller import BoundedRepairController
from autonomous_engineering.router.router import CapabilityRouter
from autonomous_engineering.validator.independent import IndependentValidator
from autonomous_engineering.workers.simulated import (
    FastCoderWorker,
    FaultyWorker,
    InvestigatorWorker,
)
from autonomous_engineering.workflow.engine import WorkflowEngine
from autonomous_engineering.work_order.compiler import WorkOrderCompiler
from autonomous_engineering.work_order.models import AcceptanceCriterion


@pytest.fixture
def repo_fixture_path() -> Path:
    base = Path(__file__).parent.parent / "fixtures" / "sample_repo"
    assert base.exists()
    return base


def test_vertical_slice_end_to_end_disconnected_success(
    tmp_path: Path, repo_fixture_path: Path
):
    """Executes the full 10-step vertical slice with interface disconnection.

    1. Ingest via interface adapter.
    2. Interface disconnects.
    3. Orchestrator executes admission, planning, leasing, synthesis, and validation.
    4. Terminal disposition ACCEPTED committed to durable SQLite store.
    5. Interface re-attaches, retrieves status and complete tamper-evident evidence bundle.
    """
    db_path = tmp_path / "orchestrator.sqlite"
    art_path = tmp_path / "artifacts"

    engine = WorkflowEngine(db_path)
    store = ArtifactStore(art_path)
    interface = HumanInterfaceAdapter(engine, store)

    # 1. Populate Worker Capability Registry
    registry = WorkerCapabilityRegistry()
    hw_b65 = HardwareTarget(
        device_type="intel_arc_pro_b65",
        pci_slot="0000:03:00.0",
        vram_bytes=17179869184,
        driver_version="24.26.29735",
    )
    prof_coder = WorkerCapabilityProfile(
        profile_id="prof-b65-0",
        worker_id="worker-b65-0",
        hardware=hw_b65,
        runtime=RuntimeConfig(
            engine="vllm_xpu",
            model_name="Qwen/Qwen2.5-Coder-32B-Instruct",
            model_revision="c8942b0",
            quantization="fp8",
            context_window=32768,
            chat_template="chatml",
            tool_parser="hermes",
        ),
        empirical_skills={
            "defect_patch": EmpiricalSkillRecord("defect_patch", True, 0.95, 50, "2026-09-25"),
            "investigation": EmpiricalSkillRecord("investigation", True, 0.88, 30, "2026-09-25"),
            "independent_validation": EmpiricalSkillRecord("independent_validation", True, 0.90, 40, "2026-09-25"),
        },
        health_status=WorkerHealthStatus.HEALTHY,
    )
    prof_inv = WorkerCapabilityProfile(
        profile_id="prof-b65-1",
        worker_id="worker-b65-1",
        hardware=hw_b65,
        runtime=RuntimeConfig(
            engine="ipex_llm",
            model_name="DeepSeek-Coder-V2-Lite",
            model_revision="7e128fa",
            quantization="bf16",
            context_window=65536,
            chat_template="deepseek",
            tool_parser="custom",
        ),
        empirical_skills={
            "investigation": EmpiricalSkillRecord("investigation", True, 0.96, 60, "2026-09-25"),
            "defect_patch": EmpiricalSkillRecord("defect_patch", True, 0.70, 20, "2026-09-25"),
            "independent_validation": EmpiricalSkillRecord("independent_validation", True, 0.85, 30, "2026-09-25"),
        },
        health_status=WorkerHealthStatus.HEALTHY,
    )
    registry.register(prof_coder)
    registry.register(prof_inv)

    # 2. Setup workers
    valid_patch = (
        "diff --git a/src/calculator/math_utils.py b/src/calculator/math_utils.py\n"
        "--- a/src/calculator/math_utils.py\n"
        "+++ b/src/calculator/math_utils.py\n"
        "@@ -6,2 +6,4 @@\n"
        " def calculate_ratio(a: float, b: float) -> float:\n"
        "+    if b == 0:\n"
        "+        raise ValueError('Denominator cannot be zero')\n"
        "     return a / b\n"
    )
    workers = {
        "worker-b65-0": FastCoderWorker("worker-b65-0", prof_coder.profile_hash, store, valid_patch),
        "worker-b65-1": InvestigatorWorker("worker-b65-1", prof_inv.profile_hash, store),
    }

    # 3. Setup control plane
    admission_evaluator = AdmissionEvaluator()
    planner = ExecutionPlanner()
    router = CapabilityRouter(registry)
    validator = IndependentValidator(store)
    repair_controller = BoundedRepairController()

    orchestrator = OrchestratorControlPlane(
        admission_evaluator=admission_evaluator,
        planner=planner,
        router=router,
        engine=engine,
        artifact_store=store,
        validator=validator,
        repair_controller=repair_controller,
        workers=workers,
        baseline_repo_dir=repo_fixture_path,
    )

    # 4. Human Interface submits work order
    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Fix zero division error in calculate_ratio when denominator is 0",
        source_channel="opencode_cli",
        source_reference="session-disconnected-001",
        repository_id="homelab-ai",
        baseline_commit="1aa374a",
        proposed_mutation_paths=["src/calculator/math_utils.py"],
        acceptance_criteria=[
            AcceptanceCriterion(
                criterion_id="crit-unit-test",
                description="Run pytest tests/test_math_utils.py",
                validator_type="pytest",
                test_target="tests/test_math_utils.py",
                required=True,
            )
        ],
    )
    receipt = interface.submit_work_order(wo)
    assert receipt.work_order_id == wo.work_order_id

    # 5. Interface disconnects
    interface.disconnect()

    # 6. Orchestrator executes asynchronously to terminal completion
    final_state = orchestrator.execute_work_order(wo, human_approval_present=True)
    assert final_state == WorkOrderState.ACCEPTED

    # 7. Interface reconnects and queries status and evidence bundle
    interface.reconnect()
    status_report = interface.query_status(wo.work_order_id, 1)
    assert status_report is not None
    assert status_report.state == WorkOrderState.ACCEPTED
    assert status_report.terminal_disposition == "ACCEPTED"

    # Export evidence bundle
    bundle = interface.export_evidence_bundle(wo.work_order_id, 1)
    assert bundle["terminal_disposition"] == "ACCEPTED"
    assert len(bundle["assignments"]) == 3  # investigate, patch, validate
    assert len(bundle["artifacts"]) >= 2   # reproduction script, patch, validation verdict


def test_vertical_slice_bounded_repair_and_revalidation(
    tmp_path: Path, repo_fixture_path: Path
):
    """Executes a scenario where the initial worker produces an invalid patch,

    the validator rejects it, the repair controller synthesizes a bounded repair,
    and a qualified worker repairs it, leading to independent acceptance.
    """
    db_path = tmp_path / "orchestrator_repair.sqlite"
    art_path = tmp_path / "artifacts"

    engine = WorkflowEngine(db_path)
    store = ArtifactStore(art_path)

    registry = WorkerCapabilityRegistry()
    hw_b65 = HardwareTarget(
        device_type="intel_arc_pro_b65",
        pci_slot="0000:03:00.0",
        vram_bytes=17179869184,
        driver_version="24.26.29735",
    )
    prof_flawed = WorkerCapabilityProfile(
        profile_id="prof-flawed",
        worker_id="worker-flawed",
        hardware=hw_b65,
        runtime=RuntimeConfig(
            engine="vllm_xpu",
            model_name="Experimental-Candidate",
            model_revision="exp1",
            quantization="fp8",
            context_window=32768,
            chat_template="chatml",
            tool_parser="hermes",
        ),
        empirical_skills={
            "defect_patch": EmpiricalSkillRecord("defect_patch", True, 0.90, 50, "2026-09-25"),
            "investigation": EmpiricalSkillRecord("investigation", True, 0.90, 50, "2026-09-25"),
        },
        health_status=WorkerHealthStatus.HEALTHY,
    )
    registry.register(prof_flawed)

    # Initially, worker-flawed produces flawed patch
    flawed_worker = FaultyWorker(
        worker_id="worker-flawed",
        profile_hash=prof_flawed.profile_hash,
        artifact_store=store,
        flaw_type="wrong_logic",
    )
    inv_worker = InvestigatorWorker(
        worker_id="worker-flawed",
        profile_hash=prof_flawed.profile_hash,
        artifact_store=store,
    )

    workers = {
        "worker-flawed": flawed_worker,
    }

    orchestrator = OrchestratorControlPlane(
        admission_evaluator=AdmissionEvaluator(),
        planner=ExecutionPlanner(),
        router=CapabilityRouter(registry),
        engine=engine,
        artifact_store=store,
        validator=IndependentValidator(store),
        repair_controller=BoundedRepairController(),
        workers=workers,
        baseline_repo_dir=repo_fixture_path,
    )

    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Fix zero division in calculate_ratio",
        source_channel="test",
        source_reference="repair-test",
        repository_id="homelab-ai",
        baseline_commit="1aa374a",
        proposed_mutation_paths=["src/calculator/math_utils.py"],
        max_retries=2,
        acceptance_criteria=[
            AcceptanceCriterion(
                criterion_id="crit-unit-test",
                description="Run pytest tests/test_math_utils.py",
                validator_type="pytest",
                test_target="tests/test_math_utils.py",
                required=True,
            )
        ],
    )

    # For the second attempt (repair), switch worker to synthesize the correct patch
    correct_patch = (
        "diff --git a/src/calculator/math_utils.py b/src/calculator/math_utils.py\n"
        "--- a/src/calculator/math_utils.py\n"
        "+++ b/src/calculator/math_utils.py\n"
        "@@ -6,2 +6,4 @@\n"
        " def calculate_ratio(a: float, b: float) -> float:\n"
        "+    if b == 0:\n"
        "+        raise ValueError('Denominator cannot be zero')\n"
        "     return a / b\n"
    )

    original_execute = flawed_worker.execute
    patch_calls = 0

    def dynamic_execute(*args, **kwargs):
        nonlocal patch_calls
        step = kwargs.get("step") or (args[1] if len(args) > 1 else None)
        if step and step.output_artifact_type == ArtifactType.PATCH:
            patch_calls += 1
            if patch_calls > 1:
                # On repair attempt, produce correct patch
                fast_coder = FastCoderWorker(
                    "worker-flawed", prof_flawed.profile_hash, store, correct_patch
                )
                return fast_coder.execute(*args, **kwargs)
        return original_execute(*args, **kwargs)

    flawed_worker.execute = dynamic_execute  # type: ignore

    final_state = orchestrator.execute_work_order(wo, human_approval_present=True)
    assert final_state == WorkOrderState.ACCEPTED

    # Version 1 was superseded
    v1_rec = engine.get_work_order(wo.work_order_id, 1)
    assert v1_rec is not None
    assert v1_rec["state"] == str(WorkOrderState.SUPERSEDED)

    # Version 2 was ACCEPTED
    v2_rec = engine.get_work_order(wo.work_order_id, 2)
    assert v2_rec is not None
    assert v2_rec["state"] == str(WorkOrderState.ACCEPTED)
    assert v2_rec["terminal_disposition"] == "ACCEPTED"
