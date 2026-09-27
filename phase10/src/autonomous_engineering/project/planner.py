"""
Autonomous Engineering System - Phase 10
Workstream C: Project Planning and Decomposition

Converts authorized high-level engineering objectives into structured, versioned
project plans with explicit dependency DAGs. Enforces cycle detection, authority non-expansion,
and strictly prohibits planner self-authorization.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Dict, List, Optional, Set, Tuple


class ProjectPlanError(Exception):
    """Base exception for engineering project planning."""


class CyclicDependencyError(ProjectPlanError):
    """Raised when the project dependency DAG contains cycles."""


class UnauthorizedScopeExpansionError(ProjectPlanError):
    """Raised when a decomposed work order targets paths outside authorized project scope."""


class SelfAuthorizationProhibitedError(ProjectPlanError):
    """Raised when a planning agent attempts to authorize its own execution plan."""


@dataclass(frozen=True)
class ProjectWorkOrder:
    """A bounded, authorized work order belonging to a larger engineering project."""
    work_order_id: str
    title: str
    task_class: str
    target_files: List[str]
    authorized_mutation_paths: List[str]
    required_specialization: str
    prerequisite_task_ids: List[str]
    acceptance_criteria: List[str]
    resource_budget_tokens: int
    failure_policy: str = "ABORT_PROJECT"  # "ABORT_PROJECT", "ISOLATE_AND_CONTINUE", "RETRY"


@dataclass(frozen=True)
class EngineeringProjectPlan:
    """
    Authoritative, versioned project execution plan with explicit dependency DAG.
    """
    project_id: str
    plan_version: int
    objective: str
    repository_id: str
    baseline_commit: str
    authorized_project_scope: List[str]
    work_orders: List[ProjectWorkOrder]
    dependency_edges: List[Tuple[str, str]]  # (prerequisite_id, dependent_id)
    plan_digest: str
    is_human_authorized: bool = False
    authorized_by: Optional[str] = None
    created_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class EngineeringProjectPlanner:
    """
    Decomposes engineering objectives into validated, dependency-aware work orders.
    """

    def __init__(self, repository_id: str, baseline_commit: str) -> None:
        self.repository_id = repository_id
        self.baseline_commit = baseline_commit

    def create_project_plan(
        self,
        project_id: str,
        plan_version: int,
        objective: str,
        authorized_project_scope: List[str],
        work_orders: List[ProjectWorkOrder],
        dependency_edges: List[Tuple[str, str]],
    ) -> EngineeringProjectPlan:
        """
        Builds, validates, and digests an EngineeringProjectPlan.
        Enforces cycle detection and scope non-expansion invariants.
        """
        # 1. Invariant Check: Cycle Detection in Dependency Graph
        self._detect_cycles(work_orders, dependency_edges)

        # 2. Invariant Check: Authority Non-Expansion
        self._validate_scope_non_expansion(authorized_project_scope, work_orders)

        # 3. Compute Canonical Plan Digest
        plan_data = {
            "project_id": project_id,
            "plan_version": plan_version,
            "objective": objective,
            "repository_id": self.repository_id,
            "baseline_commit": self.baseline_commit,
            "authorized_project_scope": sorted(authorized_project_scope),
            "work_orders": [asdict(wo) for wo in work_orders],
            "dependency_edges": sorted(dependency_edges),
        }
        canonical_json = json.dumps(plan_data, sort_keys=True, separators=(",", ":"))
        plan_digest = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

        return EngineeringProjectPlan(
            project_id=project_id,
            plan_version=plan_version,
            objective=objective,
            repository_id=self.repository_id,
            baseline_commit=self.baseline_commit,
            authorized_project_scope=authorized_project_scope,
            work_orders=work_orders,
            dependency_edges=dependency_edges,
            plan_digest=plan_digest,
            is_human_authorized=False,
        )

    def authorize_plan(
        self,
        plan: EngineeringProjectPlan,
        authorizer_identity: str,
        authorizer_role: str,
    ) -> EngineeringProjectPlan:
        """
        Authorizes a project plan for execution.
        Strictly prohibits autonomous planning agents from self-authorizing.
        """
        if "agent" in authorizer_identity.lower() or "planner" in authorizer_role.lower():
            raise SelfAuthorizationProhibitedError(
                f"Planning agent or automated role '{authorizer_identity}' cannot authorize execution plan '{plan.project_id}'"
            )

        # Return updated plan with human authorization
        return EngineeringProjectPlan(
            project_id=plan.project_id,
            plan_version=plan.plan_version,
            objective=plan.objective,
            repository_id=plan.repository_id,
            baseline_commit=plan.baseline_commit,
            authorized_project_scope=plan.authorized_project_scope,
            work_orders=plan.work_orders,
            dependency_edges=plan.dependency_edges,
            plan_digest=plan.plan_digest,
            is_human_authorized=True,
            authorized_by=authorizer_identity,
            created_at_utc=plan.created_at_utc,
        )

    def _detect_cycles(
        self,
        work_orders: List[ProjectWorkOrder],
        edges: List[Tuple[str, str]],
    ) -> None:
        """Detects cycles using topological sort / DFS cycle check."""
        adj: Dict[str, List[str]] = {wo.work_order_id: [] for wo in work_orders}
        for prereq, dep in edges:
            if prereq not in adj or dep not in adj:
                raise ProjectPlanError(f"Edge ({prereq} -> {dep}) references unknown work order")
            adj[prereq].append(dep)

        visited: Dict[str, int] = {}  # 0: visiting, 1: visited

        def dfs(node: str, path: List[str]) -> None:
            visited[node] = 0
            for neighbor in adj.get(node, []):
                if neighbor in visited and visited[neighbor] == 0:
                    cycle_str = " -> ".join(path + [neighbor])
                    raise CyclicDependencyError(f"Cyclic dependency detected: {cycle_str}")
                if neighbor not in visited:
                    dfs(neighbor, path + [neighbor])
            visited[node] = 1

        for wo in work_orders:
            if wo.work_order_id not in visited:
                dfs(wo.work_order_id, [wo.work_order_id])

    def _validate_scope_non_expansion(
        self,
        authorized_scope: List[str],
        work_orders: List[ProjectWorkOrder],
    ) -> None:
        """
        Verifies that every work order's mutation paths are strictly within
        the authorized project scope: Union(WOScope_i) <= AuthorizedScope.
        """
        norm_auth = [p.strip("./").rstrip("/") for p in authorized_scope]

        for wo in work_orders:
            for path in wo.authorized_mutation_paths:
                norm_p = path.strip("./").rstrip("/")
                is_covered = any(
                    norm_p == a or norm_p.startswith(f"{a}/")
                    for a in norm_auth
                )
                if not is_covered:
                    raise UnauthorizedScopeExpansionError(
                        f"Work order '{wo.work_order_id}' targets path '{path}' which exceeds authorized project scope: {authorized_scope}"
                    )
