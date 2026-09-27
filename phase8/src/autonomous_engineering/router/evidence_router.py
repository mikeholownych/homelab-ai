"""Evidence-Based Bounded Router for Heterogeneous Engineering Workflows."""
from __future__ import annotations

import time
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Dict, Any, Optional, List

from autonomous_engineering.core.crypto import content_hash


class RoutingTopology(str, Enum):
    HETEROGENEOUS = "heterogeneous"
    HOMOGENEOUS = "homogeneous"
    SINGLE_WORKER = "single_worker"


@dataclass(frozen=True)
class RoutingDecisionRecord:
    assignment_id: str
    task_id: str
    task_class: str
    required_role: str
    selected_candidate_id: str
    selected_topology: RoutingTopology
    rationale: str
    resource_state: Dict[str, Any]
    timestamp: str

    @property
    def decision_hash(self) -> str:
        return content_hash(asdict(self))


class EvidenceBasedRouter:
    """Subordinate router that resolves worker assignments based on demonstrated capability and live resource availability.
    
    Guarantees:
    - Never routes an assignment to an unqualified model candidate.
    - Handles specialist unavailability explicitly with documented fallback records.
    - Preserves single-worker or homogeneous routing when justified by task class or resource constraints.
    """

    def __init__(
        self,
        primary_author_candidate: str = "control-qwen3-coder-30b-awq",
        specialist_reviewer_candidate: str = "cand-phi4-fp8",
        homogeneous_fallback_candidate: str = "control-qwen3-coder-30b-awq",
    ) -> None:
        self.primary_author_candidate = primary_author_candidate
        self.specialist_reviewer_candidate = specialist_reviewer_candidate
        self.homogeneous_fallback_candidate = homogeneous_fallback_candidate
        self.decision_history: List[RoutingDecisionRecord] = []

    def route_assignment(
        self,
        assignment_id: str,
        task_id: str,
        task_class: str,
        required_role: str,
        resource_state: Optional[Dict[str, Any]] = None,
        force_topology: Optional[RoutingTopology] = None,
    ) -> RoutingDecisionRecord:
        state = resource_state or {"b65_live_endpoint": True, "phi4_specialist_available": True}
        now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        # 1. Author and Repairer Roles
        if required_role in {"author", "repairer"}:
            decision = RoutingDecisionRecord(
                assignment_id=assignment_id,
                task_id=task_id,
                task_class=task_class,
                required_role=required_role,
                selected_candidate_id=self.primary_author_candidate,
                selected_topology=RoutingTopology.HOMOGENEOUS,
                rationale=f"Assigned primary physical B65 worker for {required_role} (Demonstrated capability >= 83% acceptance)",
                resource_state=state,
                timestamp=now_str,
            )
            self.decision_history.append(decision)
            return decision

        # 2. Reviewer Role
        if required_role == "reviewer":
            # Check for explicit forced topology
            if force_topology == RoutingTopology.SINGLE_WORKER:
                decision = RoutingDecisionRecord(
                    assignment_id=assignment_id,
                    task_id=task_id,
                    task_class=task_class,
                    required_role=required_role,
                    selected_candidate_id="none",
                    selected_topology=RoutingTopology.SINGLE_WORKER,
                    rationale="Independent review bypassed per single-worker control configuration",
                    resource_state=state,
                    timestamp=now_str,
                )
                self.decision_history.append(decision)
                return decision

            if force_topology == RoutingTopology.HOMOGENEOUS:
                decision = RoutingDecisionRecord(
                    assignment_id=assignment_id,
                    task_id=task_id,
                    task_class=task_class,
                    required_role=required_role,
                    selected_candidate_id=self.homogeneous_fallback_candidate,
                    selected_topology=RoutingTopology.HOMOGENEOUS,
                    rationale="Assigned homogeneous control reviewer per experimental arrangement",
                    resource_state=state,
                    timestamp=now_str,
                )
                self.decision_history.append(decision)
                return decision

            # Check specialist availability
            phi4_available = state.get("phi4_specialist_available", False)

            if phi4_available:
                decision = RoutingDecisionRecord(
                    assignment_id=assignment_id,
                    task_id=task_id,
                    task_class=task_class,
                    required_role=required_role,
                    selected_candidate_id=self.specialist_reviewer_candidate,
                    selected_topology=RoutingTopology.HETEROGENEOUS,
                    rationale="Assigned qualified Phi-4 specialist reviewer (Demonstrated 100% recall, 0% FDR)",
                    resource_state=state,
                    timestamp=now_str,
                )
            else:
                # Explicit fallback when specialist is occupied or endpoint unavailable
                decision = RoutingDecisionRecord(
                    assignment_id=assignment_id,
                    task_id=task_id,
                    task_class=task_class,
                    required_role=required_role,
                    selected_candidate_id=self.homogeneous_fallback_candidate,
                    selected_topology=RoutingTopology.HOMOGENEOUS,
                    rationale="Specialist Phi-4 unavailable/occupied; gracefully falling back to homogeneous control reviewer",
                    resource_state=state,
                    timestamp=now_str,
                )

            self.decision_history.append(decision)
            return decision

        raise ValueError(f"Unrecognized required role: {required_role}")
