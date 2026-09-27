"""Capability-Aware Router with Independence Constraints."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from autonomous_engineering.planning.models import TaskStepDefinition
from autonomous_engineering.registry.models import WorkerCapabilityProfile
from autonomous_engineering.registry.registry import WorkerCapabilityRegistry


class RoutingError(RuntimeError):
    pass


@dataclass(frozen=True)
class RoutingDecision:
    selected_worker_id: str
    assigned_role: str
    worker_profile: WorkerCapabilityProfile
    fallback_applied: bool = False
    reason: str = ""


class CapabilityRouter:
    """Selects qualified workers based on empirical evidence and separation of concerns.

    Invariants:
    - Routing recommendations do not grant authority.
    - Independence constraint: author worker cannot be independent reviewer/validator.
    - Deterministic fallback when no worker satisfies criteria.
    """

    def __init__(self, registry: WorkerCapabilityRegistry) -> None:
        self.registry = registry

    def route(
        self,
        task_step: TaskStepDefinition,
        exclude_worker_ids: set[str] | None = None,
        min_pass_rate: float = 0.5,
        require_deployed_evidence: bool = False,
    ) -> RoutingDecision:
        excluded = exclude_worker_ids or set()
        required_role = task_step.required_role

        candidates = self.registry.get_qualified_workers(
            skill_name=required_role,
            min_pass_rate=min_pass_rate,
            require_deployed_evidence=require_deployed_evidence,
        )

        # Filter by independence constraint
        independent_candidates = [c for c in candidates if c.worker_id not in excluded]

        if not independent_candidates:
            # Deterministic fallback logic:
            # Check if any worker has skill even if pass rate is lower (e.g. 0.3)
            fallback_candidates = [
                c for c in self.registry.get_qualified_workers(
                    required_role, min_pass_rate=0.0, require_deployed_evidence=require_deployed_evidence
                )
                if c.worker_id not in excluded
            ]
            if fallback_candidates:
                chosen = fallback_candidates[0]
                return RoutingDecision(
                    selected_worker_id=chosen.worker_id,
                    assigned_role=required_role,
                    worker_profile=chosen,
                    fallback_applied=True,
                    reason=f"Fallback worker selected: pass rate below threshold {min_pass_rate}",
                )
            raise RoutingError(
                f"No qualified worker available for role '{required_role}' (excluded: {excluded})"
            )

        # Select highest ranking candidate
        selected = independent_candidates[0]
        pass_rate = selected.empirical_skills[required_role].measured_pass_rate
        return RoutingDecision(
            selected_worker_id=selected.worker_id,
            assigned_role=required_role,
            worker_profile=selected,
            fallback_applied=False,
            reason=f"Qualified worker matched with empirical pass rate {pass_rate:.2f}",
        )
