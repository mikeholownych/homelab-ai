"""Work-order versioning, revision management, and lineage tracking."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from autonomous_engineering.core.types import RevisionKind, WorkOrderState
from autonomous_engineering.work_order.models import (
    Acceptance,
    AcceptanceCriterion,
    Ambiguity,
    Authorization,
    HistoryEntry,
    Intent,
    SourceInstruction,
    WorkOrder,
    WorkOrderStateRecord,
)


class RevisionError(RuntimeError):
    pass


class WorkOrderRevisionManager:
    """Manages work order evolution across versions and computes invalidation impacts."""

    @staticmethod
    def create_revision(
        current_wo: WorkOrder,
        change_reason: str,
        author: str,
        revision_kind: RevisionKind = RevisionKind.CLARIFICATION,
        new_instruction_text: str | None = None,
        updated_paths: list[str] | None = None,
        updated_ambiguities: list[Ambiguity] | None = None,
        updated_authorization: Authorization | None = None,
        updated_criteria: list[AcceptanceCriterion] | None = None,
    ) -> WorkOrder:
        """Create a new version that supersedes the current work order."""
        new_version = current_wo.version + 1
        now_iso = datetime.now(timezone.utc).isoformat()

        # Update source instruction if modified
        source_inst = current_wo.source_instruction
        intent = current_wo.intent
        if new_instruction_text and new_instruction_text != source_inst.raw_text:
            source_inst = SourceInstruction(
                raw_text=new_instruction_text,
                source_channel=source_inst.source_channel,
                source_reference=f"{source_inst.source_reference}-rev{new_version}",
            )
            intent = Intent(
                normalized_objective=new_instruction_text,
                target_repo=current_wo.intent.target_repo,
            )

        auth = updated_authorization or current_wo.authorization
        if updated_paths is not None:
            auth = Authorization(
                authority_source=auth.authority_source,
                policy_version=auth.policy_version,
                valid_until=auth.valid_until,
                revocation_status=auth.revocation_status,
                authorized_mutation_paths=tuple(updated_paths),
                prohibited_operations=auth.prohibited_operations,
            )

        ambigs = tuple(updated_ambiguities) if updated_ambiguities is not None else current_wo.ambiguities
        acceptance = (
            Acceptance(criteria=tuple(updated_criteria))
            if updated_criteria is not None
            else current_wo.acceptance
        )

        new_history = list(current_wo.history)
        new_history.append(
            HistoryEntry(
                version=new_version,
                timestamp=now_iso,
                change_reason=f"[{revision_kind}] {change_reason}",
                author=author,
            )
        )

        initial_stage = (
            WorkOrderState.CANCELLED
            if revision_kind == RevisionKind.CANCELLATION
            else WorkOrderState.DRAFT
        )
        terminal_disp = "CANCELLED_BY_HUMAN" if revision_kind == RevisionKind.CANCELLATION else None

        return WorkOrder(
            work_order_id=current_wo.work_order_id,
            version=new_version,
            predecessor_hash=current_wo.contract_hash,
            created_at=now_iso,
            source_instruction=source_inst,
            intent=intent,
            ambiguities=ambigs,
            authorization=auth,
            acceptance=acceptance,
            dependencies=current_wo.dependencies,
            budget=current_wo.budget,
            state=WorkOrderStateRecord(
                current_stage=initial_stage,
                terminal_disposition=terminal_disp,
                fencing_token=current_wo.state.fencing_token + 1,
            ),
            history=tuple(new_history),
        )

    @staticmethod
    def evaluate_invalidation(
        old_wo: WorkOrder,
        new_wo: WorkOrder,
        revision_kind: RevisionKind | None = None,
    ) -> dict[str, Any]:
        """Compute the invalidation impact of a revision on existing work."""
        scope_expanded = not set(new_wo.authorization.authorized_mutation_paths).issubset(
            set(old_wo.authorization.authorized_mutation_paths)
        )
        intent_changed = old_wo.intent.normalized_objective != new_wo.intent.normalized_objective
        repo_changed = (
            old_wo.intent.target_repo.repository_id != new_wo.intent.target_repo.repository_id
            or old_wo.intent.target_repo.baseline_commit != new_wo.intent.target_repo.baseline_commit
        )
        criteria_changed = old_wo.acceptance.criteria != new_wo.acceptance.criteria
        is_cancellation = (
            revision_kind == RevisionKind.CANCELLATION
            or new_wo.state.current_stage == WorkOrderState.CANCELLED
        )

        requires_reauthorization = scope_expanded or repo_changed
        all_active_assignments_stale = True  # Any revision invalidates active in-flight assignments
        prior_artifacts_reusable = (
            not intent_changed
            and not repo_changed
            and not scope_expanded
            and not criteria_changed
            and not is_cancellation
        )

        return {
            "revision_kind": revision_kind or (
                RevisionKind.SCOPE_EXPANSION if scope_expanded else
                RevisionKind.CRITERIA_MUTATION if criteria_changed else
                RevisionKind.CLARIFICATION
            ),
            "scope_expanded": scope_expanded,
            "intent_changed": intent_changed,
            "repo_changed": repo_changed,
            "criteria_changed": criteria_changed,
            "is_cancellation": is_cancellation,
            "requires_reauthorization": requires_reauthorization,
            "all_active_assignments_stale": all_active_assignments_stale,
            "prior_artifacts_reusable": prior_artifacts_reusable,
        }
