"""Contract tests for Empirical Capability Registry and Dynamic Routing on B65 Workers."""
import pytest

from autonomous_engineering.core.types import ArtifactType, WorkerHealthStatus
from autonomous_engineering.planning.models import TaskStepDefinition
from autonomous_engineering.registry.models import (
    EmpiricalSkillRecord,
    HardwareTarget,
    RuntimeConfig,
    WorkerCapabilityProfile,
)
from autonomous_engineering.registry.registry import WorkerCapabilityRegistry
from autonomous_engineering.router.router import CapabilityRouter, RoutingError


@pytest.fixture
def populated_registry() -> WorkerCapabilityRegistry:
    reg = WorkerCapabilityRegistry()

    hw_b65_0 = HardwareTarget(
        device_type="intel_arc_pro_b65",
        pci_slot="0000:03:00.0",
        vram_bytes=17179869184,
        driver_version="24.26.29735",
    )
    hw_b65_1 = HardwareTarget(
        device_type="intel_arc_pro_b65",
        pci_slot="0000:04:00.0",
        vram_bytes=17179869184,
        driver_version="24.26.29735",
    )

    # Worker A (Card 0): High-speed patch synthesizer
    prof_a = WorkerCapabilityProfile(
        profile_id="prof-b65-0-qwen-fp8",
        worker_id="worker-b65-0",
        hardware=hw_b65_0,
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
            "defect_patch": EmpiricalSkillRecord("defect_patch", True, 0.92, 50, "2026-09-25"),
            "investigation": EmpiricalSkillRecord("investigation", True, 0.85, 30, "2026-09-25"),
            "independent_review": EmpiricalSkillRecord("independent_review", True, 0.70, 20, "2026-09-25"),
        },
        health_status=WorkerHealthStatus.HEALTHY,
    )

    # Worker B (Card 1): Deep reasoning & architecture review specialist
    prof_b = WorkerCapabilityProfile(
        profile_id="prof-b65-1-deepseek-bf16",
        worker_id="worker-b65-1",
        hardware=hw_b65_1,
        runtime=RuntimeConfig(
            engine="ipex_llm",
            model_name="DeepSeek-Coder-V2-Lite-Instruct",
            model_revision="7e128fa",
            quantization="bf16",
            context_window=65536,
            chat_template="deepseek",
            tool_parser="custom",
        ),
        empirical_skills={
            "defect_patch": EmpiricalSkillRecord("defect_patch", True, 0.75, 40, "2026-09-25"),
            "investigation": EmpiricalSkillRecord("investigation", True, 0.94, 60, "2026-09-25"),
            "independent_review": EmpiricalSkillRecord("independent_review", True, 0.95, 80, "2026-09-25"),
        },
        health_status=WorkerHealthStatus.HEALTHY,
    )

    reg.register(prof_a)
    reg.register(prof_b)
    return reg


def test_router_selects_best_empirical_worker_for_role(populated_registry: WorkerCapabilityRegistry):
    router = CapabilityRouter(populated_registry)

    # Defect patch task: Worker A has 0.92 vs Worker B's 0.75 -> Worker A selected
    patch_step = TaskStepDefinition(
        step_id="step-patch",
        required_role="defect_patch",
        description="Write patch",
        target_paths=("src/**",),
        dependencies=(),
        output_artifact_type=ArtifactType.PATCH,
    )
    decision = router.route(patch_step)
    assert decision.selected_worker_id == "worker-b65-0"
    assert decision.fallback_applied is False

    # Review task: Worker B has 0.95 vs Worker A's 0.70 -> Worker B selected
    review_step = TaskStepDefinition(
        step_id="step-review",
        required_role="independent_review",
        description="Review patch",
        target_paths=("src/**",),
        dependencies=(),
        output_artifact_type=ArtifactType.REVIEW,
    )
    review_decision = router.route(review_step)
    assert review_decision.selected_worker_id == "worker-b65-1"
    assert review_decision.fallback_applied is False


def test_router_enforces_independence_constraint(populated_registry: WorkerCapabilityRegistry):
    router = CapabilityRouter(populated_registry)

    # Suppose Worker B was the author of the patch.
    # When routing independent_review, Worker B MUST be excluded, even though it has a higher score!
    review_step = TaskStepDefinition(
        step_id="step-review",
        required_role="independent_review",
        description="Review patch",
        target_paths=("src/**",),
        dependencies=(),
        output_artifact_type=ArtifactType.REVIEW,
    )
    decision = router.route(review_step, exclude_worker_ids={"worker-b65-1"})
    assert decision.selected_worker_id == "worker-b65-0"


def test_router_fallback_when_worker_unhealthy(populated_registry: WorkerCapabilityRegistry):
    router = CapabilityRouter(populated_registry)
    # Mark Worker A degraded/offline
    populated_registry.set_health("worker-b65-0", WorkerHealthStatus.OFFLINE)

    patch_step = TaskStepDefinition(
        step_id="step-patch",
        required_role="defect_patch",
        description="Write patch",
        target_paths=("src/**",),
        dependencies=(),
        output_artifact_type=ArtifactType.PATCH,
    )
    # Worker A is offline; Router must route to healthy Worker B
    decision = router.route(patch_step)
    assert decision.selected_worker_id == "worker-b65-1"


def test_router_fails_closed_when_no_worker_meets_criteria(populated_registry: WorkerCapabilityRegistry):
    router = CapabilityRouter(populated_registry)

    rare_step = TaskStepDefinition(
        step_id="step-quantum",
        required_role="quantum_hardware_emulation",
        description="Quantum step",
        target_paths=("src/**",),
        dependencies=(),
        output_artifact_type=ArtifactType.LOG,
    )
    with pytest.raises(RoutingError, match="No qualified worker available"):
        router.route(rare_step)
