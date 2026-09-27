import pytest
from autonomous_engineering.physical_qualification.physical_evaluator import (
    PhysicalInferenceEvaluator,
    PhysicalEvaluationState,
)


def test_endpoint_health():
    evaluator = PhysicalInferenceEvaluator()
    res = evaluator.check_resident_endpoint_health()
    assert res.healthy is True
    assert "engineering/b0" in res.details


def test_alternative_candidate_blocked_without_authorization():
    evaluator = PhysicalInferenceEvaluator()
    # Without explicit human authorization, evaluating an alternative model that requires swap is blocked
    res = evaluator.evaluate_alternative_candidate(
        candidate_id="CAND-QWEN2.5-7B-AWQ",
        model_identifier="Qwen/Qwen2.5-7B-Instruct-AWQ",
        has_explicit_human_authorization=False,
    )
    assert res.state == PhysicalEvaluationState.BLOCKED_PENDING_MAINTENANCE_AUTHORIZATION
    assert "BLOCKED" in res.message


def test_trade_off_analysis():
    evaluator = PhysicalInferenceEvaluator()
    res = evaluator.analyze_comparative_trade_offs(
        ctrl_prompt_tokens=859,
        cand_prompt_tokens=501,
        ctrl_comp_tokens=282,
        cand_comp_tokens=441,
        ctrl_lat=12.73,
        cand_lat=16.20,
        ctrl_acc=100.0,
        cand_acc=100.0,
    )
    assert res.prompt_token_delta_pct == -41.7
    assert res.completion_token_delta_pct == 56.4
    assert res.latency_delta_pct == 27.3
    assert "TRADE_OFF" in res.trade_off_classification
