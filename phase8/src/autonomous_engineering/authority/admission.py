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
    - Rejects work orders for un-onboarded repositories or violations of protected/authorized paths.
    """

    def __init__(
        self,
        default_token_ttl_seconds: int = 3600,
        onboarding_manager: Any = None,
    ) -> None:
        self.default_token_ttl_seconds = default_token_ttl_seconds
        self.onboarding_manager = onboarding_manager

    def evaluate(
        self,
        work_order: WorkOrder,
        human_approval_present: bool = True,
        now: datetime | None = None,
    ) -> AdmissionDecision:
        current_time = now or datetime.now(timezone.utc)

        # Invariant: Repository onboarding and scope validation (if onboarding manager configured)
        if self.onboarding_manager is not None:
            repo_id = (
                work_order.intent.target_repo.repository_id
                if getattr(work_order, "intent", None) and getattr(work_order.intent, "target_repo", None)
                else getattr(getattr(work_order, "contract", None), "repository_id", None)
            )
            if not repo_id or not self.onboarding_manager.is_onboarded(repo_id):
                return AdmissionDecision(
                    admitted=False,
                    reason=f"Repository '{repo_id}' has not completed onboarding or has been offboarded",
                )
            try:
                paths = [str(p) for p in work_order.authorization.authorized_mutation_paths]
                self.onboarding_manager.validate_work_order_scope(repo_id, paths)
            except Exception as e:
                return AdmissionDecision(
                    admitted=False,
                    reason=f"Repository contract violation: {e}",
                )

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
            baseline_commit=work_order.intent.target_repo.baseline_commit,
            contract_hash=work_order.contract_hash,
            authorized_paths=work_order.authorization.authorized_mutation_paths,
            authorized_tools=("read_file", "write_patch", "run_local_test"),
            max_retries=work_order.budget.max_retries,
            fencing_token=work_order.state.fencing_token,
            issued_at=issued_at,
            expires_at=expires_at,
            max_output_bytes=1_000_000,
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
