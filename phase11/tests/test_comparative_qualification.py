import pytest

from autonomous_engineering.core.types import ValidationStatus
from autonomous_engineering.optimization.comparative import (
    ComparativeQualificationManager,
    ComparisonVerdict,
)
from autonomous_engineering.optimization.evaluator import FailureCategory, TaskEvaluationResult
from autonomous_engineering.optimization.registry import CandidateConfiguration, ExecutionMode


@pytest.fixture
def configs():
    ctrl = CandidateConfiguration(
        candidate_id="ctrl-1",
        model_identifier="engineering/b0",
        model_revision="r1",
        quantization="AWQ",
        inference_backend="vllm",
        runtime_parameters={},
        agent_profile_id="p1",
        agent_profile_version="1.0",
        agent_profile_digest="d1",
        context_strategy_version="c1",
        reasoning_allocation_policy="r1",
        tool_adapter_version="t1",
        physical_resource_requirements={},
        evaluation_corpus_version="1.0",
        execution_mode=ExecutionMode.PHYSICAL,
    )
    cand = CandidateConfiguration(
        candidate_id="cand-1",
        model_identifier="engineering/b0",
        model_revision="r1",
        quantization="AWQ",
        inference_backend="vllm",
        runtime_parameters={},
        agent_profile_id="p1",
        agent_profile_version="1.1",
        agent_profile_digest="d2",
        context_strategy_version="c2",
        reasoning_allocation_policy="r2",
        tool_adapter_version="t2",
        physical_resource_requirements={},
        evaluation_corpus_version="1.0",
        execution_mode=ExecutionMode.PHYSICAL,
    )
    return ctrl, cand


def _make_res(tid, cid, acc=True, tok=1000, dur=1.0, wclass="defect_repair"):
    return TaskEvaluationResult(
        task_id=tid,
        candidate_id=cid,
        workload_class=wclass,
        execution_mode=ExecutionMode.PHYSICAL,
        acceptance_status=ValidationStatus.ACCEPTED if acc else ValidationStatus.REJECTED,
        is_expected_outcome=acc,
        first_pass=True,
        repair_attempts=0,
        completion_time_s=dur,
        ttft_ms=50.0,
        decode_throughput_tps=30.0,
        input_tokens=tok // 2,
        output_tokens=tok // 2,
        context_cost_tokens=tok // 2,
        validation_cost_s=0.1,
        peak_vram_mb=12800,
        failure_category=FailureCategory.NONE if acc else FailureCategory.VALIDATOR_REJECTION,
        raw_trace_hash="hash" * 16,
        audit_trail={},
    )


def test_comparative_promotion_recommended(configs):
    ctrl_cfg, cand_cfg = configs
    mgr = ComparativeQualificationManager(min_sample_size=12, min_efficiency_gain_pct=10.0)

    # 12 tasks: candidate saves 20% tokens and preserves 100% acceptance
    ctrl_res = [_make_res(f"t{i}", "ctrl-1", acc=True, tok=1000, dur=1.0) for i in range(12)]
    cand_res = [_make_res(f"t{i}", "cand-1", acc=True, tok=800, dur=0.8) for i in range(12)]

    report = mgr.compare_candidates(ctrl_res, cand_res, cand_cfg, ctrl_cfg)
    assert report.verdict == ComparisonVerdict.PROMOTION_RECOMMENDED
    assert report.candidate_acceptance_rate == 1.0
    assert report.mean_token_efficiency_gain_pct >= 20.0
    assert len(report.report_digest) == 64


def test_comparative_retained_on_degraded_acceptance(configs):
    ctrl_cfg, cand_cfg = configs
    mgr = ComparativeQualificationManager(min_sample_size=12, min_efficiency_gain_pct=10.0)

    # Candidate uses fewer tokens but fails 2 tasks
    ctrl_res = [_make_res(f"t{i}", "ctrl-1", acc=True, tok=1000, dur=1.0) for i in range(12)]
    cand_res = [_make_res(f"t{i}", "cand-1", acc=(i < 10), tok=500, dur=0.5) for i in range(12)]

    report = mgr.compare_candidates(ctrl_res, cand_res, cand_cfg, ctrl_cfg)
    assert report.verdict == ComparisonVerdict.CONTROL_RETAINED


def test_comparative_early_stop_on_security_violation(configs):
    ctrl_cfg, cand_cfg = configs
    mgr = ComparativeQualificationManager(min_sample_size=12, min_efficiency_gain_pct=10.0)

    # Task 0 is an adversarial scope test. Candidate erroneously accepted it!
    ctrl_res = [_make_res("t0", "ctrl-1", acc=False, tok=100, dur=0.1, wclass="adversarial_scope")]
    cand_res = [_make_res("t0", "cand-1", acc=True, tok=100, dur=0.1, wclass="adversarial_scope")]

    report = mgr.compare_candidates(ctrl_res, cand_res, cand_cfg, ctrl_cfg)
    assert report.verdict == ComparisonVerdict.EARLY_STOP_DEFECT
    assert report.security_violations_count == 1
