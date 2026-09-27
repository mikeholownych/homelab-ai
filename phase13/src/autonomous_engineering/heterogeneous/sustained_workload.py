"""Sustained Engineering Workload and Multi-Agent Orchestration Engine for Phase 13.

Models and executes representative multi-stage autonomous engineering projects
with concurrent specialist and lead agent handoffs, dependency tracking,
queue dynamics, and project-level acceptance.
"""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Optional, Tuple

from autonomous_engineering.heterogeneous.specialist_contracts import TaskClass


class ProjectStage(str, Enum):
    INVESTIGATION = "INVESTIGATION"
    PLANNING = "PLANNING"
    IMPLEMENTATION = "IMPLEMENTATION"
    TEST_GENERATION = "TEST_GENERATION"
    STRUCTURED_OUTPUT = "STRUCTURED_OUTPUT"
    SECURITY_AUDIT = "SECURITY_AUDIT"
    INTEGRATION = "INTEGRATION"
    PROJECT_ACCEPTANCE = "PROJECT_ACCEPTANCE"


@dataclass
class EngineeringWorkItem:
    work_id: str
    project_id: str
    stage: ProjectStage
    task_class: TaskClass
    title: str
    dependencies: List[str]
    context_tokens: int
    target_role: str  # "lead" or "specialist"
    is_completed: bool = False
    accepted: bool = False
    assigned_worker: Optional[str] = None
    elapsed_time: float = 0.0


@dataclass
class EngineeringProject:
    project_id: str
    name: str
    items: List[EngineeringWorkItem]
    status: str = "PENDING"
    completed_items: int = 0
    total_latency: float = 0.0
    accepted: bool = False


def create_representative_project(project_id: str, name: str) -> EngineeringProject:
    """Creates a realistic, dependency-aware autonomous engineering project."""
    items = [
        # Stage 1: Investigation & Planning (Lead Model / 30B)
        EngineeringWorkItem(
            work_id=f"{project_id}-01",
            project_id=project_id,
            stage=ProjectStage.INVESTIGATION,
            task_class=TaskClass.ARCHITECTURAL_PLANNING,
            title="Repository Architecture & Call-Graph Investigation",
            dependencies=[],
            context_tokens=18500,
            target_role="lead",
        ),
        EngineeringWorkItem(
            work_id=f"{project_id}-02",
            project_id=project_id,
            stage=ProjectStage.PLANNING,
            task_class=TaskClass.ARCHITECTURAL_PLANNING,
            title="Dependency DAG & Rollback Boundary Plan",
            dependencies=[f"{project_id}-01"],
            context_tokens=12000,
            target_role="lead",
        ),
        # Stage 2: Core Multi-File Implementation (Lead Model / 30B)
        EngineeringWorkItem(
            work_id=f"{project_id}-03",
            project_id=project_id,
            stage=ProjectStage.IMPLEMENTATION,
            task_class=TaskClass.MULTI_FILE_IMPLEMENTATION,
            title="Core Service Refactoring & State Machine Engine",
            dependencies=[f"{project_id}-02"],
            context_tokens=15400,
            target_role="lead",
        ),
        # Stage 3: Specialist Offloads (Specialist Model / 7B in Hetero; Lead in Baseline)
        EngineeringWorkItem(
            work_id=f"{project_id}-04",
            project_id=project_id,
            stage=ProjectStage.TEST_GENERATION,
            task_class=TaskClass.TEST_GENERATION,
            title="Branch-Complete Unit & Regression Test Suite",
            dependencies=[f"{project_id}-03"],
            context_tokens=4200,
            target_role="specialist",
        ),
        EngineeringWorkItem(
            work_id=f"{project_id}-05",
            project_id=project_id,
            stage=ProjectStage.STRUCTURED_OUTPUT,
            task_class=TaskClass.STRUCTURED_OUTPUT,
            title="OpenAPI 3.1 Contract & JSON Delivery Manifest",
            dependencies=[f"{project_id}-03"],
            context_tokens=3100,
            target_role="specialist",
        ),
        EngineeringWorkItem(
            work_id=f"{project_id}-06",
            project_id=project_id,
            stage=ProjectStage.SECURITY_AUDIT,
            task_class=TaskClass.SECURITY_REVIEW,
            title="Static Application Security Testing & Scope Verification",
            dependencies=[f"{project_id}-03"],
            context_tokens=3800,
            target_role="specialist",
        ),
        # Stage 4: Integration & Project-Level Acceptance (Lead Model / 30B)
        EngineeringWorkItem(
            work_id=f"{project_id}-07",
            project_id=project_id,
            stage=ProjectStage.INTEGRATION,
            task_class=TaskClass.PROJECT_INTEGRATION,
            title="End-to-End Multi-Stage Integration & Build Contract",
            dependencies=[f"{project_id}-04", f"{project_id}-05", f"{project_id}-06"],
            context_tokens=22000,
            target_role="lead",
        ),
        EngineeringWorkItem(
            work_id=f"{project_id}-08",
            project_id=project_id,
            stage=ProjectStage.PROJECT_ACCEPTANCE,
            task_class=TaskClass.PROJECT_INTEGRATION,
            title="Independent Project Validator & Supervisor Sign-off",
            dependencies=[f"{project_id}-07"],
            context_tokens=14000,
            target_role="lead",
        ),
    ]
    return EngineeringProject(project_id=project_id, name=name, items=items)
