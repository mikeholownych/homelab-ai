"""Execution Plan and Task Step data structures."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from autonomous_engineering.core.types import ArtifactType


@dataclass(frozen=True)
class TaskStepDefinition:
    step_id: str
    required_role: str
    description: str
    target_paths: tuple[str, ...]
    dependencies: tuple[str, ...]
    output_artifact_type: ArtifactType


@dataclass(frozen=True)
class ExecutionPlan:
    plan_id: str
    work_order_id: str
    work_order_version: int
    steps: tuple[TaskStepDefinition, ...]

    def get_step(self, step_id: str) -> TaskStepDefinition | None:
        for s in self.steps:
            if s.step_id == step_id:
                return s
        return None

    def get_prerequisites(self, step_id: str) -> list[TaskStepDefinition]:
        step = self.get_step(step_id)
        if not step:
            return []
        return [self.get_step(dep) for dep in step.dependencies if self.get_step(dep)]
