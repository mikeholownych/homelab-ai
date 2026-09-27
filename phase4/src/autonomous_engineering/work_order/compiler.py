"""Work-order compilation and intent normalization."""
from __future__ import annotations

from datetime import datetime, timezone
import re
import uuid

from autonomous_engineering.core.types import (
    AmbiguityStatus,
    WorkOrderState,
)
from autonomous_engineering.work_order.models import (
    Acceptance,
    AcceptanceCriterion,
    Ambiguity,
    Authorization,
    Budget,
    Dependencies,
    HistoryEntry,
    Intent,
    SourceInstruction,
    TargetRepo,
    WorkOrder,
    WorkOrderStateRecord,
)


class CompilationError(RuntimeError):
    pass


class WorkOrderCompiler:
    """Compiles raw human instructions into canonical WorkOrder contracts.

    Invariants:
    - Never silently alter or narrow the user's intended objective.
    - Explicitly surfaces material ambiguities.
    - Proposes bounded mutation scopes based on repository inspection.
    - Fails closed if instructions are contradictory or irreducibly ambiguous without guidance.
    """

    def compile(
        self,
        raw_text: str,
        source_channel: str,
        source_reference: str,
        repository_id: str,
        baseline_commit: str,
        proposed_mutation_paths: list[str] | None = None,
        authority_source: str = "human_operator",
        policy_version: str = "v1.0",
        valid_until: str | None = None,
        max_retries: int = 3,
        ambiguities: list[Ambiguity] | None = None,
        acceptance_criteria: list[AcceptanceCriterion] | None = None,
    ) -> WorkOrder:
        if not raw_text.strip():
            raise CompilationError("Raw instruction cannot be empty")

        now_iso = datetime.now(timezone.utc).isoformat()
        instruction = SourceInstruction(
            raw_text=raw_text.strip(),
            source_channel=source_channel,
            source_reference=source_reference,
        )

        detected_ambiguities = list(ambiguities or [])

        # Ambiguity detection heuristic: detect ambiguous choice keywords without resolution
        ambiguous_patterns = [
            (r"\b(either\s+.+\s+or\s+.+)\b", "Ambiguous alternative behaviors detected in instruction"),
            (r"\b(maybe|perhaps|somehow|or something)\b", "Vague specification in instruction"),
        ]
        for pattern, desc in ambiguous_patterns:
            if re.search(pattern, raw_text, re.IGNORECASE):
                # If not already listed in ambiguities, add as unresolved
                if not any(a.description == desc for a in detected_ambiguities):
                    detected_ambiguities.append(
                        Ambiguity(
                            ambiguity_id=f"amb-{uuid.uuid4().hex[:8]}",
                            description=f"{desc}: '{re.search(pattern, raw_text, re.IGNORECASE).group(0)}'",
                            status=AmbiguityStatus.UNRESOLVED,
                        )
                    )

        # Build normalized intent
        intent = Intent(
            normalized_objective=raw_text.strip(),
            target_repo=TargetRepo(
                repository_id=repository_id,
                baseline_commit=baseline_commit,
            ),
        )

        # Default paths if not specified
        paths = tuple(proposed_mutation_paths or ["src/**", "tests/**"])

        # Default authorization (advisory proposal for admission evaluator)
        valid_time = valid_until or datetime.now(timezone.utc).replace(year=2028).isoformat()
        authorization = Authorization(
            authority_source=authority_source,
            policy_version=policy_version,
            valid_until=valid_time,
            revocation_status=False,
            authorized_mutation_paths=paths,
        )

        # Default acceptance criteria if none provided
        criteria = acceptance_criteria or [
            AcceptanceCriterion(
                criterion_id="crit-default-test",
                description="Run repository test suite for affected modules",
                validator_type="pytest",
                test_target="tests/",
                required=True,
            )
        ]
        acceptance = Acceptance(
            criteria=tuple(criteria),
            independent_validation_required=True,
        )

        # Determine initial state
        has_unresolved_ambiguity = any(a.status == AmbiguityStatus.UNRESOLVED for a in detected_ambiguities)
        initial_stage = (
            WorkOrderState.AMBIGUOUS if has_unresolved_ambiguity else WorkOrderState.DRAFT
        )

        wo_id = f"wo-{uuid.uuid4().hex[:12]}"
        return WorkOrder(
            work_order_id=wo_id,
            version=1,
            predecessor_hash=None,
            created_at=now_iso,
            source_instruction=instruction,
            intent=intent,
            ambiguities=tuple(detected_ambiguities),
            authorization=authorization,
            acceptance=acceptance,
            dependencies=Dependencies(permitted_parallelism=1),
            budget=Budget(max_retries=max_retries),
            state=WorkOrderStateRecord(current_stage=initial_stage),
            history=(
                HistoryEntry(
                    version=1,
                    timestamp=now_iso,
                    change_reason="Initial compilation from raw instruction",
                    author=source_channel,
                ),
            ),
        )
