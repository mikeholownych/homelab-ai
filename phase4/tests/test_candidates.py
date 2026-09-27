"""Tests for Phase 4 Candidate Manifests and Hardware Resource Envelopes."""
import pytest
from autonomous_engineering.eval.candidates import (
    CONTROL_QWEN3_CODER_30B_AWQ,
    CANDIDATE_QWEN25_32B_AWQ,
    CANDIDATE_DEEPSEEK_LITE_FP8,
    CANDIDATE_PHI4_FP8,
    CANDIDATE_REGISTRY,
    get_candidate,
    list_candidates,
    CandidateManifest,
)


def test_control_baseline_manifest():
    ctrl = CONTROL_QWEN3_CODER_30B_AWQ
    assert ctrl.candidate_id == "control-qwen3-coder-30b-awq"
    assert ctrl.is_control_baseline is True
    assert ctrl.architecture_type == "moe"
    assert ctrl.quantization_format == "awq-4bit"
    assert ctrl.context_window_limit >= 16384
    assert ctrl.validate_resource_envelope() is True
    assert len(ctrl.manifest_hash) == 64


def test_candidate_inventory_completeness():
    cands = list_candidates()
    assert len(cands) == 4
    cand_ids = {c.candidate_id for c in cands}
    assert "control-qwen3-coder-30b-awq" in cand_ids
    assert "cand-qwen25-32b-awq" in cand_ids
    assert "cand-deepseek-lite-fp8" in cand_ids
    assert "cand-phi4-fp8" in cand_ids


def test_resource_envelope_boundaries():
    valid_cand = CANDIDATE_PHI4_FP8
    assert valid_cand.validate_resource_envelope(max_vram_per_card_gb=31.89) is True

    # Oversized candidate exceeding physical B65 VRAM
    oversized = CandidateManifest(
        candidate_id="cand-oversized-70b",
        model_repository="meta-llama/Llama-3-70B",
        model_revision="abc1234",
        architecture_type="dense",
        parameter_count_total=70.0,
        parameter_count_active=70.0,
        quantization_format="fp16",
        serving_runtime="vllm-xpu",
        topology="tp1_single_card",
        context_window_limit=16384,
        tool_call_parser="hermes",
        vram_budget_gb=70.0,  # Exceeds 31.89 GB
        host_ram_reserve_gb=8.0,
    )
    assert oversized.validate_resource_envelope(max_vram_per_card_gb=31.89) is False

    # Low host RAM reserve candidate
    low_reserve = CandidateManifest(
        candidate_id="cand-low-reserve",
        model_repository="test/test-model",
        model_revision="abc1234",
        architecture_type="dense",
        parameter_count_total=7.0,
        parameter_count_active=7.0,
        quantization_format="int4",
        serving_runtime="vllm-xpu",
        topology="tp1_single_card",
        context_window_limit=16384,
        tool_call_parser="hermes",
        vram_budget_gb=10.0,
        host_ram_reserve_gb=4.0,  # Below 8.0 GB min reserve
    )
    assert low_reserve.validate_resource_envelope() is False


def test_get_candidate_lookup():
    assert get_candidate("cand-phi4-fp8") == CANDIDATE_PHI4_FP8
    with pytest.raises(KeyError):
        get_candidate("non-existent-candidate")
