"""Execution planner: Decomposes work orders into verifiable DAG execution plans."""
from __future__ import annotations

import uuid

from autonomous_engineering.core.types import ArtifactType
from autonomous_engineering.planning.models import ExecutionPlan, TaskStepDefinition
from autonomous_engineering.work_order.models import WorkOrder


class PlanningError(RuntimeError):
    pass


class ExecutionPlanner:
    """Decomposes an admitted WorkOrder into a DAG of specialized task steps.

    Invariants:
    - Planning proposes task decomposition only; it NEVER grants capabilities.
    - Preserves exact mutation scope from the WorkOrder.
    """

    def create_plan(self, work_order: WorkOrder) -> ExecutionPlan:
        plan_id = f"plan-{uuid.uuid4().hex[:12]}"
        paths = work_order.authorization.authorized_mutation_paths

        # Standard specialized DAG for engineering defect repair:
        # 1. investigate: investigate root cause and generate reproduction evidence
        # 2. defect_patch: author code patch within bounded mutation scope
        # 3. independent_validation: execute pre-registered acceptance suite
        steps = (
            TaskStepDefinition(
                step_id="step-investigate",
                required_role="investigation",
                description="Investigate baseline defect and reproduce failure",
                target_paths=paths,
                dependencies=(),
                output_artifact_type=ArtifactType.REPRODUCTION_SCRIPT,
            ),
            TaskStepDefinition(
                step_id="step-patch",
                required_role="defect_patch",
                description="Synthesize code patch to fix defect",
                target_paths=paths,
                dependencies=("step-investigate",),
                output_artifact_type=ArtifactType.PATCH,
            ),
            TaskStepDefinition(
                step_id="step-validate",
                required_role="independent_validation",
                description="Independently execute registered acceptance tests",
                target_paths=paths,
                dependencies=("step-patch",),
                output_artifact_type=ArtifactType.VALIDATION_VERDICT,
            ),
        )

        return ExecutionPlan(
            plan_id=plan_id,
            work_order_id=work_order.work_order_id,
            work_order_version=work_order.version,
            steps=steps,
        )
