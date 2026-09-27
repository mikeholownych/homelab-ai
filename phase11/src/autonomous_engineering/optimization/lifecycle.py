"""
Autonomous Engineering System - Phase 11
Workstream I: Qualification and Promotion Lifecycle Manager

Enforces the formal state machine:
REGISTERED -> ELIGIBLE -> EVALUATING -> EVALUATED -> QUALIFIED -> PROMOTION_PENDING -> PROMOTED
plus terminal REJECTED and REVOKED states.
Strictly requires explicit human authorization and verified rollback plans before promotion.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple


class QualificationState(str, Enum):
    REGISTERED = "REGISTERED"
    ELIGIBLE = "ELIGIBLE"
    EVALUATING = "EVALUATING"
    EVALUATED = "EVALUATED"
    QUALIFIED = "QUALIFIED"
    PROMOTION_PENDING = "PROMOTION_PENDING"
    PROMOTED = "PROMOTED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class LifecycleError(Exception):
    """Base exception for qualification lifecycle transitions."""


class InvalidStateTransitionError(LifecycleError):
    """Raised when an illegal state transition is attempted."""


class UnauthorizedPromotionError(LifecycleError):
    """Raised when promotion is attempted by an automated agent or lacks human authorization."""


class MissingRollbackPlanError(LifecycleError):
    """Raised when promotion is requested without a verified rollback plan."""


@dataclass(frozen=True)
class CandidateQualificationRecord:
    """An immutable audit record of a candidate configuration's qualification state."""
    candidate_id: str
    state: QualificationState
    candidate_digest: str
    corpus_version: str
    evaluation_digest: str
    authorized_by: Optional[str]
    rollback_plan: Optional[str]
    history: List[Dict[str, str]]
    updated_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class CandidateQualificationLifecycle:
    """
    State machine governing model and agent qualification.
    Enforces fail-closed evaluation, immutable evidence binding, and operator promotion authority.
    """

    def __init__(self) -> None:
        self._records: Dict[str, CandidateQualificationRecord] = {}

    def register_candidate(
        self,
        candidate_id: str,
        candidate_digest: str,
        corpus_version: str,
    ) -> CandidateQualificationRecord:
        """Initializes lifecycle record in REGISTERED state."""
        rec = CandidateQualificationRecord(
            candidate_id=candidate_id,
            state=QualificationState.REGISTERED,
            candidate_digest=candidate_digest,
            corpus_version=corpus_version,
            evaluation_digest="",
            authorized_by=None,
            rollback_plan=None,
            history=[{"state": QualificationState.REGISTERED.value, "time": datetime.now(timezone.utc).isoformat()}],
        )
        self._records[candidate_id] = rec
        return rec

    def advance_to_eligible(self, candidate_id: str) -> CandidateQualificationRecord:
        """Transitions REGISTERED -> ELIGIBLE after schema and precondition validation."""
        rec = self._get_record(candidate_id)
        if rec.state != QualificationState.REGISTERED:
            raise InvalidStateTransitionError(f"Cannot advance to ELIGIBLE from state {rec.state}")
        return self._transition(rec, QualificationState.ELIGIBLE, "Schema and preconditions verified")

    def start_evaluation(self, candidate_id: str) -> CandidateQualificationRecord:
        """Transitions ELIGIBLE -> EVALUATING when evaluation campaign starts."""
        rec = self._get_record(candidate_id)
        if rec.state != QualificationState.ELIGIBLE:
            raise InvalidStateTransitionError(f"Cannot start evaluation from state {rec.state}")
        return self._transition(rec, QualificationState.EVALUATING, "Assigned to evaluation campaign")

    def record_evaluation_complete(
        self,
        candidate_id: str,
        evaluation_digest: str,
        qualifies: bool,
        rationale: str,
    ) -> CandidateQualificationRecord:
        """Transitions EVALUATING -> EVALUATED (or REJECTED) upon completion of evaluation suite."""
        rec = self._get_record(candidate_id)
        if rec.state != QualificationState.EVALUATING:
            raise InvalidStateTransitionError(f"Cannot complete evaluation from state {rec.state}")

        next_state = QualificationState.QUALIFIED if qualifies else QualificationState.REJECTED
        new_hist = list(rec.history)
        new_hist.append({"state": next_state.value, "time": datetime.now(timezone.utc).isoformat(), "rationale": rationale})

        updated = CandidateQualificationRecord(
            candidate_id=rec.candidate_id,
            state=next_state,
            candidate_digest=rec.candidate_digest,
            corpus_version=rec.corpus_version,
            evaluation_digest=evaluation_digest,
            authorized_by=rec.authorized_by,
            rollback_plan=rec.rollback_plan,
            history=new_hist,
        )
        self._records[candidate_id] = updated
        return updated

    def propose_promotion(
        self,
        candidate_id: str,
        rollback_plan: str,
    ) -> CandidateQualificationRecord:
        """Transitions QUALIFIED -> PROMOTION_PENDING with attached rollback plan."""
        rec = self._get_record(candidate_id)
        if rec.state != QualificationState.QUALIFIED:
            raise InvalidStateTransitionError(f"Cannot propose promotion for candidate in state {rec.state}")
        if not rollback_plan or "patch -p1 -R" not in rollback_plan and "rollback" not in rollback_plan.lower():
            raise MissingRollbackPlanError("Promotion proposal must include a verified rollback plan")

        new_hist = list(rec.history)
        new_hist.append({"state": QualificationState.PROMOTION_PENDING.value, "time": datetime.now(timezone.utc).isoformat()})

        updated = CandidateQualificationRecord(
            candidate_id=rec.candidate_id,
            state=QualificationState.PROMOTION_PENDING,
            candidate_digest=rec.candidate_digest,
            corpus_version=rec.corpus_version,
            evaluation_digest=rec.evaluation_digest,
            authorized_by=None,
            rollback_plan=rollback_plan,
            history=new_hist,
        )
        self._records[candidate_id] = updated
        return updated

    def promote(
        self,
        candidate_id: str,
        authorizer_identity: str,
        authorizer_role: str,
    ) -> CandidateQualificationRecord:
        """
        Transitions PROMOTION_PENDING -> PROMOTED upon explicit human authorization.
        Strictly prohibits autonomous planning agents from self-promoting.
        """
        rec = self._get_record(candidate_id)
        if rec.state != QualificationState.PROMOTION_PENDING:
            raise InvalidStateTransitionError(f"Cannot promote candidate in state {rec.state}")

        # Human Authorization Gate
        if "agent" in authorizer_identity.lower() or "planner" in authorizer_role.lower() or "automated" in authorizer_role.lower():
            raise UnauthorizedPromotionError(
                f"Automated role or agent '{authorizer_identity}' is strictly prohibited from authorizing candidate promotion"
            )

        new_hist = list(rec.history)
        new_hist.append({
            "state": QualificationState.PROMOTED.value,
            "time": datetime.now(timezone.utc).isoformat(),
            "authorized_by": authorizer_identity,
        })

        updated = CandidateQualificationRecord(
            candidate_id=rec.candidate_id,
            state=QualificationState.PROMOTED,
            candidate_digest=rec.candidate_digest,
            corpus_version=rec.corpus_version,
            evaluation_digest=rec.evaluation_digest,
            authorized_by=authorizer_identity,
            rollback_plan=rec.rollback_plan,
            history=new_hist,
        )
        self._records[candidate_id] = updated
        return updated

    def revoke(self, candidate_id: str, reason: str) -> CandidateQualificationRecord:
        """Transitions any active state -> REVOKED."""
        rec = self._get_record(candidate_id)
        return self._transition(rec, QualificationState.REVOKED, reason)

    def get_record(self, candidate_id: str) -> CandidateQualificationRecord:
        """Retrieves qualification record for candidate."""
        return self._get_record(candidate_id)

    def _get_record(self, candidate_id: str) -> CandidateQualificationRecord:
        rec = self._records.get(candidate_id)
        if not rec:
            raise LifecycleError(f"No qualification record for candidate '{candidate_id}'")
        return rec

    def _transition(
        self,
        rec: CandidateQualificationRecord,
        new_state: QualificationState,
        rationale: str,
    ) -> CandidateQualificationRecord:
        new_hist = list(rec.history)
        new_hist.append({"state": new_state.value, "time": datetime.now(timezone.utc).isoformat(), "rationale": rationale})
        updated = CandidateQualificationRecord(
            candidate_id=rec.candidate_id,
            state=new_state,
            candidate_digest=rec.candidate_digest,
            corpus_version=rec.corpus_version,
            evaluation_digest=rec.evaluation_digest,
            authorized_by=rec.authorized_by,
            rollback_plan=rec.rollback_plan,
            history=new_hist,
        )
        self._records[rec.candidate_id] = updated
        return updated
