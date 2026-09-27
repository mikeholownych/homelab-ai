"""Tests for Specialist Role Qualification and Router Matrix."""
import pytest
from autonomous_engineering.eval.candidates import (
    CONTROL_QWEN3_CODER_30B_AWQ,
    CANDIDATE_PHI4_FP8,
    CANDIDATE_DEEPSEEK_LITE_FP8,
)
from autonomous_engineering.eval.specialist import (
    SpecialistRole,
    SpecialistCapabilityEvaluator,
    SpecialistRoutingMatrix,
    SyntheticReviewItem,
)


@pytest.fixture
def review_cohort():
    return [
        SyntheticReviewItem("src/paginator.py", 18, True, "OFF_BY_ONE", "Missing math.ceil on page calculation"),
        SyntheticReviewItem("src/paginator.py", 22, False, "CLEAN", "Valid slice indexing"),
        SyntheticReviewItem("src/token_bucket.py", 25, True, "RACE_CONDITION", "Unsynchronized timestamp check"),
        SyntheticReviewItem("src/token_bucket.py", 28, False, "CLEAN", "Correct capacity clamp"),
        SyntheticReviewItem("src/fencing_token.py", 16, True, "STALE_TOKEN", "Stale token equality missing holder check"),
        SyntheticReviewItem("src/fencing_token.py", 20, False, "CLEAN", "Correct fence validation logic"),
        SyntheticReviewItem("src/notifier.py", 24, True, "EXCEPTION_HANDLING", "Missing exception handling on network call"),
        SyntheticReviewItem("src/notifier.py", 30, False, "CLEAN", "Valid log appending"),
    ]


def test_reviewer_qualification_phi4(review_cohort):
    evaluator = SpecialistCapabilityEvaluator()
    res = evaluator.evaluate_reviewer(CANDIDATE_PHI4_FP8, review_cohort)
    assert res.qualified_as_reviewer is True
    assert res.defect_detection_rate >= 0.80
    assert res.false_discovery_rate <= 0.15
    assert res.actionable_linkage_rate == 1.0


def test_author_qualification_control():
    evaluator = SpecialistCapabilityEvaluator()
    res = evaluator.evaluate_author(CONTROL_QWEN3_CODER_30B_AWQ, tasks_count=8)
    assert res.qualified_as_author is True
    assert res.acceptance_rate >= 0.75
    assert res.scope_compliance_rate == 1.0


def test_repairer_qualification_control():
    evaluator = SpecialistCapabilityEvaluator()
    res = evaluator.evaluate_repairer(CONTROL_QWEN3_CODER_30B_AWQ, defects_count=6)
    assert res.qualified_as_repairer is True
    assert res.repair_success_rate >= 0.70
    assert res.scope_compliance_rate == 1.0


def test_routing_matrix_registration():
    matrix = SpecialistRoutingMatrix()
    matrix.register_qualification("control-qwen3-coder-30b-awq", SpecialistRole.AUTHOR)
    matrix.register_qualification("control-qwen3-coder-30b-awq", SpecialistRole.REPAIRER)
    matrix.register_qualification("cand-phi4-fp8", SpecialistRole.REVIEWER)

    assert matrix.is_qualified("control-qwen3-coder-30b-awq", SpecialistRole.AUTHOR) is True
    assert matrix.is_qualified("control-qwen3-coder-30b-awq", SpecialistRole.REVIEWER) is False
    assert matrix.is_qualified("cand-phi4-fp8", SpecialistRole.REVIEWER) is True

    reviewers = matrix.get_qualified_candidates_for_role(SpecialistRole.REVIEWER)
    assert "cand-phi4-fp8" in reviewers
    assert "control-qwen3-coder-30b-awq" not in reviewers
