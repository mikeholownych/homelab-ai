"""Bounded Repair Controller and Failure Classifier."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any

from autonomous_engineering.artifacts.models import ArtifactRecord
from autonomous_engineering.core.types import FailureClass, WorkOrderState
from autonomous_engineering.validator.independent import ValidationVerdict
from autonomous_engineering.work_order.models import (
    Budget,
    HistoryEntry,
    WorkOrder,
    WorkOrderStateRecord,
)


@dataclass(frozen=True)
class FailureClassification:
    failure_class: FailureClass
    diagnostic_summary: str
    root_cause_hint: str


class BoundedRepairController:
    """Classifies validation failures and produces bounded repair work orders."""

    @staticmethod
    def classify_failure(verdict: ValidationVerdict) -> FailureClassification:
        logs = verdict.diagnostic_logs

        if "SyntaxError" in logs or "IndentationError" in logs or "is not valid python syntax" in logs:
            return FailureClassification(
                failure_class=FailureClass.SYNTAX_OR_COMPILATION_ERROR,
                diagnostic_summary="Syntactic or indentation defect in submitted patch",
                root_cause_hint="Check Python grammar and indentation in modified code",
            )
        if "ScopeViolationError" in logs or "Unauthorized mutation" in logs:
            return FailureClassification(
                failure_class=FailureClass.SCOPE_VIOLATION,
                diagnostic_summary="Attempted file mutation outside authorized scope",
                root_cause_hint="Restrict modifications strictly to authorized_mutation_paths",
            )
        if "CollectionError" in logs or "ImportError" in logs or "ModuleNotFoundError" in logs:
            return FailureClassification(
                failure_class=FailureClass.TEST_COLLECTION_ERROR,
                diagnostic_summary="Test runner collection or import failure",
                root_cause_hint="Verify imports and module structure",
            )
        if "AssertionError" in logs or "FAILED" in logs:
            # Extract failed assertion line if present
            match = re.search(r"E\s+(ValueError|AssertionError|TypeError):?\s*(.*)", logs)
            detail = match.group(0) if match else "Assertion expectation failed"
            return FailureClassification(
                failure_class=FailureClass.ASSERTION_ERROR,
                diagnostic_summary=f"Assertion failure: {detail}",
                root_cause_hint="Adjust implementation logic to satisfy expected assertion",
            )
        if "timed out" in logs.lower() or "timeout" in logs.lower():
            return FailureClassification(
                failure_class=FailureClass.TIMEOUT,
                diagnostic_summary="Execution or validation exceeded allotted deadline",
                root_cause_hint="Optimize code execution or investigate infinite loop",
            )

        return FailureClassification(
            failure_class=FailureClass.MALFORMED_OUTPUT,
            diagnostic_summary="Validation failed with unclassified output",
            root_cause_hint="Inspect full diagnostic log for root cause",
        )

    def prepare_repair_work_order(
        self,
        current_wo: WorkOrder,
        failed_artifact: ArtifactRecord,
        verdict: ValidationVerdict,
    ) -> WorkOrder | None:
        """Create a bounded repair work order if budget permits, or None if budget exhausted."""
        now_iso = datetime.now(timezone.utc).isoformat()
        classification = self.classify_failure(verdict)

        repair_count = sum(
            1 for h in current_wo.history if "repair" in h.change_reason.lower()
        )
        remaining = current_wo.budget.max_retries - repair_count - 1

        if remaining < 0:
            # Budget exhausted
            return None

        new_version = current_wo.version + 1
        new_history = list(current_wo.history)
        new_history.append(
            HistoryEntry(
                version=new_version,
                timestamp=now_iso,
                change_reason=f"Bounded repair for {classification.failure_class}: {classification.diagnostic_summary} (remaining retries: {remaining})",
                author="system-repair-controller",
            )
        )

        return WorkOrder(
            work_order_id=current_wo.work_order_id,
            version=new_version,
            predecessor_hash=current_wo.contract_hash,
            created_at=now_iso,
            source_instruction=current_wo.source_instruction,
            intent=current_wo.intent,
            ambiguities=current_wo.ambiguities,
            authorization=current_wo.authorization,
            acceptance=current_wo.acceptance,
            dependencies=current_wo.dependencies,
            budget=Budget(
                max_retries=current_wo.budget.max_retries,
                max_wallclock_seconds=current_wo.budget.max_wallclock_seconds,
                escalation_policy=current_wo.budget.escalation_policy,
            ),
            state=WorkOrderStateRecord(
                current_stage=WorkOrderState.DRAFT,
                terminal_disposition=None,
                fencing_token=current_wo.state.fencing_token + 1,
            ),
            history=tuple(new_history),
        )
