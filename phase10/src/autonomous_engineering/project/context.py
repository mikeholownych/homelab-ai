"""
Autonomous Engineering System - Phase 10
Workstream D: Durable Cross-Session Engineering Context

Provides ACID-compliant persistent context storage for multi-stage engineering projects.
Enforces session recovery invariance, strict cross-project isolation, and stale context detection.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

from autonomous_engineering.project.planner import EngineeringProjectPlan, ProjectWorkOrder


class ContextStorageError(Exception):
    """Base exception for cross-session project context errors."""


class CrossProjectLeakageError(ContextStorageError):
    """Raised when attempting to access context belonging to another project."""


class StaleProjectContextError(ContextStorageError):
    """Raised when project context binds to an obsolete baseline commit or plan version."""


@dataclass(frozen=True)
class CheckpointRecord:
    """A durable execution checkpoint recorded during multi-stage project execution."""
    checkpoint_id: str
    project_id: str
    plan_version: int
    completed_task_ids: List[str]
    in_flight_task_ids: List[str]
    intermediate_deliverable_digests: Dict[str, str]  # wo_id -> patch_digest
    state_summary: str
    created_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ProjectContextManager:
    """
    Durable, SQLite-backed project context manager preserving state across restarts.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initializes tables with Write-Ahead Logging (WAL)."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS project_plans (
                    project_id TEXT PRIMARY KEY,
                    plan_version INTEGER,
                    objective TEXT,
                    repository_id TEXT,
                    baseline_commit TEXT,
                    plan_digest TEXT,
                    is_human_authorized INTEGER,
                    plan_json TEXT,
                    created_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS intermediate_deliverables (
                    deliverable_id TEXT PRIMARY KEY,
                    project_id TEXT,
                    work_order_id TEXT,
                    patch_text TEXT,
                    patch_digest TEXT,
                    validation_status TEXT,
                    created_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint_id TEXT PRIMARY KEY,
                    project_id TEXT,
                    plan_version INTEGER,
                    completed_tasks TEXT,
                    in_flight_tasks TEXT,
                    deliverable_digests TEXT,
                    state_summary TEXT,
                    created_at TEXT
                )
                """
            )
            conn.commit()

    def save_project_plan(self, plan: EngineeringProjectPlan) -> None:
        """Persists a project plan."""
        plan_dict = asdict(plan)
        plan_json = json.dumps(plan_dict, sort_keys=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO project_plans (
                    project_id, plan_version, objective, repository_id,
                    baseline_commit, plan_digest, is_human_authorized, plan_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan.project_id,
                    plan.plan_version,
                    plan.objective,
                    plan.repository_id,
                    plan.baseline_commit,
                    plan.plan_digest,
                    1 if plan.is_human_authorized else 0,
                    plan_json,
                    plan.created_at_utc,
                ),
            )
            conn.commit()

    def get_project_plan(
        self,
        project_id: str,
        expected_commit: Optional[str] = None,
    ) -> Optional[EngineeringProjectPlan]:
        """Retrieves project plan, validating commit freshness."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT plan_json, baseline_commit FROM project_plans WHERE project_id = ?",
                (project_id,),
            ).fetchone()

        if not row:
            return None

        plan_json, baseline_commit = row
        if expected_commit and baseline_commit != expected_commit:
            raise StaleProjectContextError(
                f"Project plan for '{project_id}' is at commit '{baseline_commit}', but caller requested '{expected_commit}'"
            )

        data = json.loads(plan_json)
        work_orders = [ProjectWorkOrder(**wo) for wo in data["work_orders"]]
        edges = [tuple(e) for e in data["dependency_edges"]]

        return EngineeringProjectPlan(
            project_id=data["project_id"],
            plan_version=data["plan_version"],
            objective=data["objective"],
            repository_id=data["repository_id"],
            baseline_commit=data["baseline_commit"],
            authorized_project_scope=data["authorized_project_scope"],
            work_orders=work_orders,
            dependency_edges=edges,
            plan_digest=data["plan_digest"],
            is_human_authorized=bool(data.get("is_human_authorized", False)),
            authorized_by=data.get("authorized_by"),
            created_at_utc=data.get("created_at_utc", ""),
        )

    def record_intermediate_deliverable(
        self,
        project_id: str,
        work_order_id: str,
        patch_text: str,
        patch_digest: str,
        validation_status: str,
    ) -> None:
        """Saves an independently accepted intermediate task deliverable."""
        deliverable_id = f"deliv-{project_id}-{work_order_id}"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO intermediate_deliverables (
                    deliverable_id, project_id, work_order_id, patch_text,
                    patch_digest, validation_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    deliverable_id,
                    project_id,
                    work_order_id,
                    patch_text,
                    patch_digest,
                    validation_status,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()

    def get_intermediate_deliverables(self, project_id: str) -> Dict[str, Dict[str, Any]]:
        """Returns all intermediate deliverables for a project."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT work_order_id, patch_text, patch_digest, validation_status
                FROM intermediate_deliverables WHERE project_id = ?
                """,
                (project_id,),
            ).fetchall()

        return {
            r[0]: {
                "work_order_id": r[0],
                "patch_text": r[1],
                "patch_digest": r[2],
                "validation_status": r[3],
            }
            for r in rows
        }

    def save_checkpoint(self, checkpoint: CheckpointRecord) -> None:
        """Saves a durable execution checkpoint."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO checkpoints (
                    checkpoint_id, project_id, plan_version, completed_tasks,
                    in_flight_tasks, deliverable_digests, state_summary, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    checkpoint.checkpoint_id,
                    checkpoint.project_id,
                    checkpoint.plan_version,
                    json.dumps(checkpoint.completed_task_ids),
                    json.dumps(checkpoint.in_flight_task_ids),
                    json.dumps(checkpoint.intermediate_deliverable_digests),
                    checkpoint.state_summary,
                    checkpoint.created_at_utc,
                ),
            )
            conn.commit()

    def get_latest_checkpoint(self, project_id: str) -> Optional[CheckpointRecord]:
        """Retrieves the latest checkpoint for session recovery."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT checkpoint_id, project_id, plan_version, completed_tasks,
                       in_flight_tasks, deliverable_digests, state_summary, created_at
                FROM checkpoints WHERE project_id = ? ORDER BY created_at DESC LIMIT 1
                """,
                (project_id,),
            ).fetchone()

        if not row:
            return None

        return CheckpointRecord(
            checkpoint_id=row[0],
            project_id=row[1],
            plan_version=row[2],
            completed_task_ids=json.loads(row[3]),
            in_flight_task_ids=json.loads(row[4]),
            intermediate_deliverable_digests=json.loads(row[5]),
            state_summary=row[6],
            created_at_utc=row[7],
        )

    def validate_project_isolation(
        self,
        requested_project_id: str,
        target_project_id: str,
    ) -> None:
        """Enforces cross-project context isolation."""
        if requested_project_id != target_project_id:
            raise CrossProjectLeakageError(
                f"Cross-project access blocked: context from '{requested_project_id}' cannot be bound to '{target_project_id}'"
            )
