import pytest

from autonomous_engineering.capabilities.registry import (
    ModelCapabilityRecord,
    ModelCapabilityRegistry,
    ModelExecutionTier,
    QualificationKey,
    QualificationStatus,
)
from autonomous_engineering.classifier.classifier import (
    FailureConsequence,
    ReasoningComplexity,
    UncertaintyLevel,
    WorkloadRequirements,
)
from autonomous_engineering.profiles.registry import VersionedAgentProfileRegistry
from autonomous_engineering.resources.manager import PhysicalInferenceResourceManager
from autonomous_engineering.scheduler.scheduler import (
    CapabilityAwareModelScheduler,
    NoQualifiedCandidateError,
)


def test_scheduler_hard_gate_unqualified_fails_closed():
    profile_reg = VersionedAgentProfileRegistry()
    cap_reg = ModelCapabilityRegistry()
    res_mgr = PhysicalInferenceResourceManager()

    scheduler = CapabilityAwareModelScheduler(profile_reg, cap_reg, res_mgr)

    reqs = WorkloadRequirements(
        workload_id="req-unqual-01",
        version="1.0.0",
        task_class="unsupported_quantum_computing",
        required_specializations=["repo-investigator"],
        reasoning_complexity=ReasoningComplexity.MEDIUM,
        context_demand_tokens=8192,
        required_tools=["read_file"],
        expected_execution_cost=2.0,
        failure_consequence=FailureConsequence.LOW,
        mandatory_validation_suites=["syntax_ast"],
        uncertainty_level=UncertaintyLevel.LOW,
        resource_constraints={},
    )

    with pytest.raises(NoQualifiedCandidateError):
        scheduler.schedule_operation(
            work_order_id="wo-001",
            requirements=reqs,
            target_specialization="repo-investigator",
        )


def test_scheduler_selects_qualified_candidate_with_least_cost():
    profile_reg = VersionedAgentProfileRegistry()
    cap_reg = ModelCapabilityRegistry()
    res_mgr = PhysicalInferenceResourceManager()

    # Qualify engineering/b0 for defect_repair
    investigator = profile_reg.get_profile("repo-investigator", "1.0.0")
    key = QualificationKey(
        profile_digest=investigator.compute_digest(),
        model_revision="qwen3-coder-30b-awq-v1",
        inference_config_digest="default-awq-config-v1",
        workload_class="defect_repair",
        qualification_suite_version="v1",
    )
    cap_reg.record_qualification(
        key=key,
        status=QualificationStatus.QUALIFIED,
        evaluation_run_id="run-b0-qual",
        acceptance_rate=1.0,
        average_repair_count=0.2,
        passed_validation_suites=["syntax_ast"],
        evidence_digest="sha256-b0-qual",
    )

    scheduler = CapabilityAwareModelScheduler(profile_reg, cap_reg, res_mgr)

    reqs = WorkloadRequirements(
        workload_id="req-qual-02",
        version="1.0.0",
        task_class="defect_repair",
        required_specializations=["repo-investigator"],
        reasoning_complexity=ReasoningComplexity.LOW,
        context_demand_tokens=8192,
        required_tools=["read_file"],
        expected_execution_cost=1.0,
        failure_consequence=FailureConsequence.LOW,
        mandatory_validation_suites=["syntax_ast"],
        uncertainty_level=UncertaintyLevel.LOW,
        resource_constraints={},
    )

    decision = scheduler.schedule_operation(
        work_order_id="wo-002",
        requirements=reqs,
        target_specialization="repo-investigator",
    )

    assert decision.selected_model_identifier == "engineering/b0"
    assert decision.assigned_worker_id in ["vllm-xpu-tp1-worker1", "vllm-xpu-tp1-worker2"]
    assert decision.total_expected_cost > 0.0
