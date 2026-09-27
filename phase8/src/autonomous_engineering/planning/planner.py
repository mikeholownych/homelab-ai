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

    def __init__(
        self,
        include_investigation: bool = True,
        include_review: bool = False,
        primary_role: str = "defect_patch",
    ) -> None:
        self.include_investigation = include_investigation
        self.include_review = include_review
        self.primary_role = primary_role

    def create_plan(self, work_order: WorkOrder) -> ExecutionPlan:
        plan_id = f"plan-{uuid.uuid4().hex[:12]}"
        paths = work_order.authorization.authorized_mutation_paths

        # Determine primary author role if not explicitly customized
        author_role = self.primary_role
        if work_order.intent and hasattr(work_order.intent, "metadata") and work_order.intent.metadata:
            author_role = work_order.intent.metadata.get("author_role", author_role)

        # Standard specialized DAG for engineering defect repair:
        # 1. investigate (optional): investigate root cause and generate reproduction evidence
        # 2. defect_patch / implementation: author code patch within bounded mutation scope
        # 3. independent_review (optional): review candidate patch and produce advisory report
        # 4. independent_validation: execute pre-registered acceptance suite
        steps: list[TaskStepDefinition] = []
        if self.include_investigation:
            steps.append(
                TaskStepDefinition(
                    step_id="step-investigate",
                    required_role="investigation",
                    description="Investigate baseline defect and reproduce failure",
                    target_paths=paths,
                    dependencies=(),
                    output_artifact_type=ArtifactType.REPRODUCTION_SCRIPT,
                )
            )

        patch_desc = (
            f"Fix defect: {work_order.intent.normalized_objective}. Requirement: {work_order.source_instruction.raw_text}"
            if work_order.intent and work_order.source_instruction
            else f"Execute {author_role} to synthesize code patch"
        )
        steps.append(
            TaskStepDefinition(
                step_id="step-patch",
                required_role=author_role,
                description=patch_desc,
                target_paths=paths,
                dependencies=("step-investigate",) if self.include_investigation else (),
                output_artifact_type=ArtifactType.PATCH,
            )
        )

        val_dependencies: tuple[str, ...] = ("step-patch",)
        if self.include_review:
            steps.append(
                TaskStepDefinition(
                    step_id="step-review",
                    required_role="independent_review",
                    description="Perform independent code review of candidate patch against requirements",
                    target_paths=paths,
                    dependencies=("step-patch",),
                    output_artifact_type=ArtifactType.REVIEW_REPORT,
                )
            )
            val_dependencies = ("step-review",)

        steps.append(
            TaskStepDefinition(
                step_id="step-validate",
                required_role="independent_validation",
                description="Independently execute registered acceptance tests",
                target_paths=paths,
                dependencies=val_dependencies,
                output_artifact_type=ArtifactType.VALIDATION_VERDICT,
            )
        )

        return ExecutionPlan(
            plan_id=plan_id,
            work_order_id=work_order.work_order_id,
            work_order_version=work_order.version,
            steps=tuple(steps),
        )
