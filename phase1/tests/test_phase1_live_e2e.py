"""End-to-End Live Model Controlled Execution Test for Phase 1.

Demonstrates complete vertical slice with untrusted live model worker:
1. Canonical WorkOrder submitted through HumanInterfaceAdapter.
2. Interface disconnects (session independence).
3. AdmissionEvaluator admits work order and issues CapabilityToken.
4. ExecutionPlanner creates DAG without granted capabilities.
5. CapabilityRouter dispatches step-patch to LiveModelWorker.
6. LiveModelWorker connects to local inference gateway (engineering/b0), synthesizes patch.
7. Patch captured as immutable artifact in ArtifactStore.
8. IndependentValidator verifies patch inside isolated BwrapSandbox (no network, readonly root).
9. WorkflowEngine atomically commits terminal disposition ACCEPTED with monotonic fencing.
10. Interface reconnects and verifies complete tamper-evident evidence bundle.
11. Baseline repository remains pristine (no unauthorized side effects).
"""
from pathlib import Path
import shutil
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
    EvidenceSource,
    HardwareTarget,
    RuntimeConfig,
    WorkerCapabilityProfile,
)
from autonomous_engineering.registry.registry import WorkerCapabilityRegistry
from autonomous_engineering.repair.controller import BoundedRepairController
from autonomous_engineering.router.router import CapabilityRouter
from autonomous_engineering.validator.independent import IndependentValidator
from autonomous_engineering.workers.live_adapter import LiveModelWorker
from autonomous_engineering.workflow.engine import WorkflowEngine
from autonomous_engineering.work_order.compiler import WorkOrderCompiler
from autonomous_engineering.work_order.models import AcceptanceCriterion


@pytest.fixture
def repo_fixture_path() -> Path:
    base = Path(__file__).parent.parent / "fixtures" / "disposable_repo"
    assert base.exists()
    return base


def test_controlled_live_execution_e2e(tmp_path: Path, repo_fixture_path: Path):
    token_path = Path("/home/mike/.config/opencode/t5820-client-token")
    if not token_path.exists():
        pytest.skip("Live client token not accessible at /home/mike/.config/opencode/t5820-client-token")

    # 1. Setup isolated ephemeral environment
    db_path = tmp_path / "orchestrator.sqlite"
    art_path = tmp_path / "artifacts"
    disposable_worktree = tmp_path / "disposable_worktree"
    shutil.copytree(repo_fixture_path, disposable_worktree)

    engine = WorkflowEngine(db_path)
    store = ArtifactStore(art_path)
    interface = HumanInterfaceAdapter(engine, store)

    # 2. Setup Worker Capability Registry with Live Model Worker Profile
    registry = WorkerCapabilityRegistry()
    hw_b65 = HardwareTarget(
        device_type="intel_arc_pro_b65",
        pci_slot="0000:03:00.0",
        vram_bytes=32 * 1024 * 1024 * 1024,
        driver_version="xe-24.1",
    )
    prof_live = WorkerCapabilityProfile(
        profile_id="prof-live-b65-0",
        worker_id="worker-live-b65-0",
        hardware=hw_b65,
        runtime=RuntimeConfig(
            engine="vllm_xpu",
            model_name="engineering/b0",
            model_revision="live-endpoint",
            quantization="int4",
            context_window=16384,
            chat_template="qwen2",
            tool_parser="hermes",
        ),
        empirical_skills={
            "defect_patch": EmpiricalSkillRecord(
                skill_name="defect_patch",
                verified=True,
                measured_pass_rate=0.92,
                sample_size=30,
                last_evaluated="2026-09-26T00:00:00Z",
                evidence_source=EvidenceSource.EMPIRICAL_DEPLOYED_MEASUREMENT,
            ),
        },
        health_status=WorkerHealthStatus.HEALTHY,
    )
    registry.register(prof_live)

    # 3. Instantiate Live Model Worker (strictly 1 worker, no concurrency)
    live_worker = LiveModelWorker(
        worker_id="worker-live-b65-0",
        profile_hash=prof_live.profile_hash,
        artifact_store=store,
        endpoint_url="http://127.0.0.1:18010/v1/chat/completions",
        token_path=token_path,
        model_name="engineering/b0",
    )
    workers = {"worker-live-b65-0": live_worker}

    # 4. Setup Control Plane components
    admission_evaluator = AdmissionEvaluator()
    planner = ExecutionPlanner(include_investigation=False)
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
        baseline_repo_dir=disposable_worktree,
    )

    # 5. Compile and Submit Canonical Work Order
    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text=(
            "Fix calculate_moving_average in src/stats_utils.py so negative window_size "
            "raises ValueError('window_size must be positive') and window_size > len(data) returns empty list []."
        ),
        source_channel="opencode_cli",
        source_reference="phase1-live-session-001",
        repository_id="homelab-ai-disposable",
        baseline_commit="8b25d26",
        proposed_mutation_paths=["src/stats_utils.py"],
        acceptance_criteria=[
            AcceptanceCriterion(
                criterion_id="crit-stats-pytest",
                description="Run pytest tests/test_stats_utils.py under bwrap containment",
                validator_type="pytest",
                test_target="tests/test_stats_utils.py",
                required=True,
            )
        ],
    )

    receipt = interface.submit_work_order(wo)
    assert receipt.work_order_id == wo.work_order_id
    assert receipt.contract_hash == wo.contract_hash

    # 6. Disconnect human interface (prove execution is independent of interface session)
    interface.disconnect()
    assert not interface._connected

    # 7. Orchestrator executes asynchronously to completion
    final_state = orchestrator.execute_work_order(wo, human_approval_present=True)
    assert final_state == WorkOrderState.ACCEPTED

    # 8. Reconnect interface and verify durable state & evidence bundle
    interface.reconnect()
    assert interface._connected

    status = interface.query_status(wo.work_order_id, wo.version)
    assert status is not None
    assert status.state == WorkOrderState.ACCEPTED
    assert status.terminal_disposition == "ACCEPTED"
    assert status.fencing_token >= 1

    # Verify assignments and audit trail
    assert len(status.assignments) >= 2  # step-patch and step-validate
    patch_assignment = next(a for a in status.assignments if a["step_id"] == "step-patch")
    validate_assignment = next(a for a in status.assignments if a["step_id"] == "step-validate")

    assert patch_assignment["fencing_token"] >= 2
    assert validate_assignment["fencing_token"] >= 2
    assert patch_assignment["status"] == "COMPLETED"
    assert patch_assignment["lease_worker"] == "worker-live-b65-0"
    assert patch_assignment["output_artifact_hash"] is not None

    assert validate_assignment["status"] == "COMPLETED"
    assert validate_assignment["lease_worker"] == "system-validator"
    assert validate_assignment["output_artifact_hash"] is not None

    # 9. Verify cryptographic evidence bundle
    bundle = interface.export_evidence_bundle(wo.work_order_id, wo.version)
    artifacts = bundle["artifacts"]
    assert len(artifacts) >= 2

    patch_record = next(a for a in artifacts if a["artifact_type"] == ArtifactType.PATCH.value)
    assert patch_record["producing_worker_id"] == "worker-live-b65-0"
    assert patch_record["metadata"]["model_name"] == "engineering/b0"
    assert patch_record["metadata"]["request_id"].startswith("req-")

    verdict_record = next(a for a in artifacts if a["artifact_type"] == ArtifactType.VALIDATION_VERDICT.value)
    assert verdict_record["producing_worker_id"] == "system-validator"
    assert verdict_record["metadata"]["all_passed"] is True

    # 10. Verify baseline fixture preservation: original fixture directory is untouched
    baseline_content = (repo_fixture_path / "src" / "stats_utils.py").read_text()
    assert "if window_size == 0:" in baseline_content  # defect still in fixture
    assert "if window_size <= 0:" not in baseline_content
