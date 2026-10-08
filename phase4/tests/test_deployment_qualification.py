"""Tests for Deployment Qualification and Interface Protocol."""
import pytest
from autonomous_engineering.eval.candidates import (
    CONTROL_QWEN3_CODER_30B_AWQ,
    CANDIDATE_PHI4_FP8,
    CandidateManifest,
)
from autonomous_engineering.eval.deployment_qual import DeploymentQualifier


def test_qualify_valid_candidate():
    qualifier = DeploymentQualifier(physical_vram_limit_gb=31.89, min_host_ram_reserve_gb=4.0)
    res = qualifier.qualify_candidate(CANDIDATE_PHI4_FP8)
    assert res.passed is True
    assert res.interface_compatible is True
    assert res.tool_call_fidelity == 1.0
    assert res.context_limit_supported == 16384
    assert len(res.disqualification_reasons) == 0


def test_reject_invalid_tool_parser():
    invalid_parser_cand = CandidateManifest(
        candidate_id="cand-invalid-parser",
        model_repository="test/custom-model",
        model_revision="hash1",
        architecture_type="dense",
        parameter_count_total=8.0,
        parameter_count_active=8.0,
        quantization_format="int4",
        serving_runtime="vllm-xpu",
        topology="tp1_single_card",
        context_window_limit=16384,
        tool_call_parser="unknown_custom_parser",
        vram_budget_gb=12.0,
        host_ram_reserve_gb=8.0,
    )
    qualifier = DeploymentQualifier(min_host_ram_reserve_gb=4.0)
    res = qualifier.qualify_candidate(invalid_parser_cand)
    assert res.passed is False
    assert any("Unsupported tool parser" in r for r in res.disqualification_reasons)


def test_live_endpoint_qualification_check():
    # Test with live control candidate pointing to local gateway
    from pathlib import Path

    token_file = Path("/home/mike/.config/opencode/t5820-client-token")
    token = token_file.read_text().strip() if token_file.exists() else None

    qualifier = DeploymentQualifier(min_host_ram_reserve_gb=4.0)
    res = qualifier.qualify_candidate(
        CONTROL_QWEN3_CODER_30B_AWQ,
        live_endpoint="http://127.0.0.1:18010/v1",
        auth_token=token,
    )
    # The control candidate passes qualification
    assert res.passed is True
    if token:
        assert res.live_endpoint_verified is True
