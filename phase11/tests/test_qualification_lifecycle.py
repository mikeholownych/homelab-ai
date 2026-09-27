import pytest

from autonomous_engineering.optimization.lifecycle import (
    CandidateQualificationLifecycle,
    InvalidStateTransitionError,
    MissingRollbackPlanError,
    QualificationState,
    UnauthorizedPromotionError,
)


def test_full_lifecycle_and_human_promotion():
    lc = CandidateQualificationLifecycle()
    cid = "cand-lifecycle-1"

    # 1. Register
    rec = lc.register_candidate(cid, "digest-1", "1.0.0")
    assert rec.state == QualificationState.REGISTERED

    # 2. Advance to Eligible
    rec = lc.advance_to_eligible(cid)
    assert rec.state == QualificationState.ELIGIBLE

    # 3. Start Evaluation
    rec = lc.start_evaluation(cid)
    assert rec.state == QualificationState.EVALUATING

    # 4. Evaluation Complete -> Qualified
    rec = lc.record_evaluation_complete(cid, "eval-digest-1", qualifies=True, rationale="Passed all gates")
    assert rec.state == QualificationState.QUALIFIED

    # 5. Propose Promotion with rollback plan
    rec = lc.propose_promotion(cid, rollback_plan="patch -p1 -R < candidate_rollback.patch")
    assert rec.state == QualificationState.PROMOTION_PENDING

    # 6. Human Authorization Gate: Agent cannot authorize
    with pytest.raises(UnauthorizedPromotionError):
        lc.promote(cid, authorizer_identity="planning-agent-01", authorizer_role="autonomous_agent")

    # 7. Valid Human Authorization
    rec = lc.promote(cid, authorizer_identity="lead-operator@corp.com", authorizer_role="human_principal_engineer")
    assert rec.state == QualificationState.PROMOTED
    assert rec.authorized_by == "lead-operator@corp.com"


def test_missing_rollback_plan_blocks_promotion():
    lc = CandidateQualificationLifecycle()
    cid = "cand-no-rollback"
    lc.register_candidate(cid, "digest", "1.0.0")
    lc.advance_to_eligible(cid)
    lc.start_evaluation(cid)
    lc.record_evaluation_complete(cid, "eval-digest", qualifies=True, rationale="OK")

    with pytest.raises(MissingRollbackPlanError):
        lc.propose_promotion(cid, rollback_plan="")


def test_invalid_state_transition_fails_closed():
    lc = CandidateQualificationLifecycle()
    cid = "cand-invalid"
    lc.register_candidate(cid, "digest", "1.0.0")

    # Cannot jump directly from REGISTERED to QUALIFIED
    with pytest.raises(InvalidStateTransitionError):
        lc.record_evaluation_complete(cid, "eval-digest", qualifies=True, rationale="Skip")
