import pytest

from autonomous_engineering.optimization.registry import (
    CandidateConfiguration,
    CandidateNotFoundError,
    DuplicateCandidateError,
    ExecutionMode,
    InvalidCandidateConfigurationError,
    OptimizationCandidateRegistry,
)


def test_candidate_registration_and_digest():
    reg = OptimizationCandidateRegistry()
    ctrl = reg.register_protected_control()

    assert ctrl.candidate_id == "control-b0-qwen3-coder-awq-tp1-v1"
    digest = ctrl.compute_canonical_digest()
    assert len(digest) == 64

    retrieved = reg.get_candidate("control-b0-qwen3-coder-awq-tp1-v1")
    assert retrieved.candidate_id == ctrl.candidate_id
    assert retrieved.execution_mode == ExecutionMode.PHYSICAL


def test_duplicate_candidate_rejected():
    reg = OptimizationCandidateRegistry()
    reg.register_protected_control()

    with pytest.raises(DuplicateCandidateError):
        reg.register_protected_control()


def test_incomplete_candidate_rejected():
    reg = OptimizationCandidateRegistry()
    bad_cand = CandidateConfiguration(
        candidate_id="bad-1",
        model_identifier="",  # Missing!
        model_revision="rev",
        quantization="",  # Missing!
        inference_backend="vllm",
        runtime_parameters={},
        agent_profile_id="",
        agent_profile_version="1.0.0",
        agent_profile_digest="",
        context_strategy_version="v1",
        reasoning_allocation_policy="p1",
        tool_adapter_version="v1",
        physical_resource_requirements={},
        evaluation_corpus_version="1.0.0",
        execution_mode=ExecutionMode.SIMULATED,
    )
    with pytest.raises(InvalidCandidateConfigurationError):
        reg.register_candidate(bad_cand)
