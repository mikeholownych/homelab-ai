"""Contract tests for Heterogeneous Capability Registry and Routing."""
import pytest

from autonomous_engineering.core.types import ArtifactType, WorkerHealthStatus
from autonomous_engineering.planning.models import TaskStepDefinition
from autonomous_engineering.registry.models import (
    EmpiricalSkillRecord,
    EvidenceSource,
    HardwareTarget,
    RuntimeConfig,
    WorkerCapabilityProfile,
)
from autonomous_engineering.registry.registry import WorkerCapabilityRegistry
from autonomous_engineering.router.router import CapabilityRouter, RoutingError


@pytest.fixture
def sample_registry() -> WorkerCapabilityRegistry:
    registry = WorkerCapabilityRegistry()

    # Worker 1: Control worker (Qwen3-Coder baseline)
    qwen_profile = WorkerCapabilityProfile(
        profile_id="prof-qwen3-coder-control",
        worker_id="worker-qwen3-control",
        hardware=HardwareTarget(
            device_type="intel_arc_pro_b65",
            pci_slot="0000:03:00.0",
            vram_bytes=32 * 1024 * 1024 * 1024,
            driver_version="xe-24.1",
        ),
        runtime=RuntimeConfig(
            engine="vllm_xpu",
            model_name="Qwen/Qwen2.5-Coder-32B-Instruct",
            model_revision="main",
            quantization="fp8",
            context_window=32768,
            chat_template="chatml",
            tool_parser="hermes",
        ),
        empirical_skills={
            "defect_patch": EmpiricalSkillRecord(
                skill_name="defect_patch",
                verified=True,
                measured_pass_rate=0.88,
                sample_size=50,
                last_evaluated="2026-09-20T00:00:00Z",
                evidence_source=EvidenceSource.EMPIRICAL_DEPLOYED_MEASUREMENT,
            ),
            "investigation": EmpiricalSkillRecord(
                skill_name="investigation",
                verified=True,
                measured_pass_rate=0.75,
                sample_size=40,
                last_evaluated="2026-09-20T00:00:00Z",
                evidence_source=EvidenceSource.EMPIRICAL_DEPLOYED_MEASUREMENT,
            ),
        },
    )

    # Worker 2: Synthetic fixture worker (unverified on physical hardware)
    synthetic_profile = WorkerCapabilityProfile(
        profile_id="prof-b65-synthetic",
        worker_id="worker-b65-simulated",
        hardware=HardwareTarget(
            device_type="intel_arc_pro_b65",
            pci_slot="0000:04:00.0",
            vram_bytes=32 * 1024 * 1024 * 1024,
            driver_version="xe-24.1",
        ),
        runtime=RuntimeConfig(
            engine="vllm_xpu",
            model_name="engineering/b0",
            model_revision="b65-quant-v1",
            quantization="int4",
            context_window=16384,
            chat_template="qwen2",
            tool_parser="builtin",
        ),
        empirical_skills={
            "defect_patch": EmpiricalSkillRecord(
                skill_name="defect_patch",
                verified=True,
                measured_pass_rate=0.95,  # Higher pass rate, but only synthetic!
                sample_size=10,
                last_evaluated="2026-09-25T00:00:00Z",
                evidence_source=EvidenceSource.SYNTHETIC_FIXTURE,
            ),
        },
    )

    registry.register(qwen_profile)
    registry.register(synthetic_profile)
    return registry


def test_registry_distinguishes_synthetic_vs_deployed_evidence(sample_registry: WorkerCapabilityRegistry):
    # Without requiring deployed evidence, the synthetic worker ranks first due to higher pass rate (0.95 vs 0.88)
    candidates_any = sample_registry.get_qualified_workers("defect_patch", min_pass_rate=0.5, require_deployed_evidence=False)
    assert len(candidates_any) == 2
    assert candidates_any[0].worker_id == "worker-b65-simulated"
    assert candidates_any[0].empirical_skills["defect_patch"].evidence_source == EvidenceSource.SYNTHETIC_FIXTURE

    # When requiring deployed evidence, synthetic worker is excluded
    candidates_empirical = sample_registry.get_qualified_workers("defect_patch", min_pass_rate=0.5, require_deployed_evidence=True)
    assert len(candidates_empirical) == 1
    assert candidates_empirical[0].worker_id == "worker-qwen3-control"
    assert candidates_empirical[0].empirical_skills["defect_patch"].evidence_source == EvidenceSource.EMPIRICAL_DEPLOYED_MEASUREMENT


def test_router_enforces_deployed_evidence_and_independence(sample_registry: WorkerCapabilityRegistry):
    router = CapabilityRouter(sample_registry)

    step = TaskStepDefinition(
        step_id="step-defect-repair",
        required_role="defect_patch",
        description="Fix statistical utility defect",
        target_paths=("src/stats_utils.py",),
        dependencies=(),
        output_artifact_type=ArtifactType.PATCH,
    )

    # Route with require_deployed_evidence=True must select Qwen control worker
    decision = router.route(step, require_deployed_evidence=True)
    assert decision.selected_worker_id == "worker-qwen3-control"
    assert decision.assigned_role == "defect_patch"
    assert not decision.fallback_applied

    # If Qwen control worker is excluded by independence constraint, and deployed evidence is required:
    # synthetic worker cannot satisfy deployed evidence requirement -> raises RoutingError
    with pytest.raises(RoutingError, match="No qualified worker available"):
        router.route(step, exclude_worker_ids={"worker-qwen3-control"}, require_deployed_evidence=True)
