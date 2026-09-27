import pytest
from autonomous_engineering.physical_qualification.candidate_registry import (
    CandidateArtifactRegistry,
    ArtifactVerificationStatus,
)


def test_candidate_registry_defaults():
    registry = CandidateArtifactRegistry()
    ctrl = registry.get_candidate("CTRL-QWEN3-CODER-30B")
    assert ctrl is not None
    assert ctrl.status == ArtifactVerificationStatus.VERIFIED
    assert ctrl.is_resident_control is True
    assert ctrl.parameter_count_b == 30.0

    cand1 = registry.get_candidate("CAND-QWEN2.5-7B-AWQ")
    assert cand1 is not None
    assert cand1.status == ArtifactVerificationStatus.VERIFIED
    assert cand1.parameter_count_b == 7.61
    assert cand1.context_window_tokens == 32768


def test_reject_mutable_tag():
    registry = CandidateArtifactRegistry()
    art = registry.register_candidate(
        candidate_id="BAD-TAG-MODEL",
        model_identifier="some/model",
        snapshot_revision="latest",
        architecture="Qwen2ForCausalLM",
        parameter_count_b=7.0,
        active_parameter_count_b=7.0,
        quantization_format="AWQ-4bit",
        context_window_tokens=32768,
        config_sha256="42981b44892a1940c8f93bf5fb40972bc62f2c9a6c8f0d10115175e68b11396d",
        tokenizer_sha256=None,
        runtime_container_digest="docker.io/vllm/vllm-openai-xpu@sha256:abc",
        tool_call_parser="hermes",
        structured_output_engine="outlines",
    )
    assert art.status == ArtifactVerificationStatus.REJECTED_MUTABLE_TAG


def test_reject_missing_config_hash():
    registry = CandidateArtifactRegistry()
    art = registry.register_candidate(
        candidate_id="BAD-HASH-MODEL",
        model_identifier="some/model",
        snapshot_revision="4bd30395b72ea6045edd04806c4fea448d4467b3",
        architecture="Qwen2ForCausalLM",
        parameter_count_b=7.0,
        active_parameter_count_b=7.0,
        quantization_format="AWQ-4bit",
        context_window_tokens=32768,
        config_sha256="",  # Missing hash
        tokenizer_sha256=None,
        runtime_container_digest="docker.io/vllm/vllm-openai-xpu@sha256:abc",
        tool_call_parser="hermes",
        structured_output_engine="outlines",
    )
    assert art.status == ArtifactVerificationStatus.REJECTED_MISSING_CONFIG
