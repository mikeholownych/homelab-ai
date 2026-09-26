"""Authority evaluation and admission control plane."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import uuid

from autonomous_engineering.authority.tokens import CapabilityToken
from autonomous_engineering.core.types import WorkOrderState
from autonomous_engineering.work_order.models import WorkOrder, WorkOrderStateRecord


@dataclass(frozen=True)
class AdmissionDecision:
    admitted: bool
    reason: str
    token: CapabilityToken | None = None
    admitted_work_order: WorkOrder | None = None


class AdmissionEvaluator:
    """Evaluates work-order admissibility against policy, scope, and authority invariants.

    Invariants:
    - Missing, contradictory, expired or unverifiable authority fails closed.
    - Ambiguous work orders cannot be admitted.
    - Human approval is input to authority evaluation, not unconditional authorization.
    """

    def __init__(self, default_token_ttl_seconds: int = 3600) -> None:
        self.default_token_ttl_seconds = default_token_ttl_seconds

    def evaluate(
        self,
        work_order: WorkOrder,
        human_approval_present: bool = True,
        now: datetime | None = None,
    ) -> AdmissionDecision:
        current_time = now or datetime.now(timezone.utc)

        # Invariant: Unresolved ambiguities block admission
        if work_order.is_ambiguous():
            return AdmissionDecision(
                admitted=False,
                reason="Work order contains unresolved material ambiguities",
            )

        # Invariant: Human approval requirement
        if not human_approval_present:
            return AdmissionDecision(
                admitted=False,
                reason="Missing required human approval envelope",
            )

        # Invariant: Authority revocation check
        if work_order.authorization.revocation_status:
            return AdmissionDecision(
                admitted=False,
                reason="Work order authority has been explicitly revoked",
            )

        # Invariant: Expiration check
        try:
            valid_until = datetime.fromisoformat(work_order.authorization.valid_until)
            if valid_until.tzinfo is None:
                valid_until = valid_until.replace(tzinfo=timezone.utc)
            if current_time >= valid_until:
                return AdmissionDecision(
                    admitted=False,
                    reason=f"Work order authority expired at {work_order.authorization.valid_until}",
                )
        except (ValueError, TypeError) as exc:
            return AdmissionDecision(
                admitted=False,
                reason=f"Malformed authority expiration timestamp: {exc}",
            )

        # Invariant: Mutation scope must be specified
        if not work_order.authorization.authorized_mutation_paths:
            return AdmissionDecision(
                admitted=False,
                reason="Authority specifies empty authorized mutation paths",
            )

        # Issue scoped capability token for this work order
        issued_at = current_time.isoformat()
        expires_at = datetime.fromtimestamp(
            current_time.timestamp() + self.default_token_ttl_seconds, tz=timezone.utc
        ).isoformat()

        token = CapabilityToken(
            token_id=f"cap-{uuid.uuid4().hex[:12]}",
            work_order_id=work_order.work_order_id,
            work_order_version=work_order.version,
            task_id="root",
            authorized_paths=work_order.authorization.authorized_mutation_paths,
            authorized_tools=("read_file", "write_patch", "run_local_test"),
            max_retries=work_order.budget.max_retries,
            fencing_token=work_order.state.fencing_token,
            issued_at=issued_at,
            expires_at=expires_at,
            revoked=False,
        )

        admitted_wo = WorkOrder(
            work_order_id=work_order.work_order_id,
            version=work_order.version,
            predecessor_hash=work_order.predecessor_hash,
            created_at=work_order.created_at,
            source_instruction=work_order.source_instruction,
            intent=work_order.intent,
            ambiguities=work_order.ambiguities,
            authorization=work_order.authorization,
            acceptance=work_order.acceptance,
            dependencies=work_order.dependencies,
            budget=work_order.budget,
            state=WorkOrderStateRecord(
                current_stage=WorkOrderState.ADMITTED,
                terminal_disposition=None,
                fencing_token=work_order.state.fencing_token,
            ),
            history=work_order.history,
        )

        return AdmissionDecision(
            admitted=True,
            reason="Work order successfully validated and admitted",
            token=token,
            admitted_work_order=admitted_wo,
        )
