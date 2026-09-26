"""Durable Transactional Workflow Engine with Monotonic Fencing and Recovery."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any
import uuid

from autonomous_engineering.core.crypto import canonical_json
from autonomous_engineering.core.types import (
    FailureClass,
    TaskStepState,
    WorkOrderState,
)
from autonomous_engineering.planning.models import ExecutionPlan
from autonomous_engineering.work_order.models import WorkOrder


class WorkflowEngineError(RuntimeError):
    def __init__(self, message: str, failure_class: FailureClass | None = None) -> None:
        super().__init__(message)
        self.failure_class = failure_class


class WorkflowEngine:
    """ACID transactional workflow engine managing work order lifecycles and worker leases.

    Invariants:
    - Atomicity: State changes and lease updates are committed in SQLite transactions.
    - Monotonic Fencing: Every lease increment enforces strict linear ordering; late tokens are rejected.
    - Recovery: Engine state is reloaded directly from SQLite on restart without loss of lineage.
    - Idempotent Completion: Submitting an identical artifact for an already completed task succeeds idempotently.
    """

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS work_orders (
                    work_order_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    predecessor_hash TEXT,
                    contract_hash TEXT NOT NULL,
                    state TEXT NOT NULL,
                    terminal_disposition TEXT,
                    fencing_token INTEGER NOT NULL DEFAULT 1,
                    data_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (work_order_id, version)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS task_assignments (
                    assignment_id TEXT PRIMARY KEY,
                    work_order_id TEXT NOT NULL,
                    work_order_version INTEGER NOT NULL,
                    step_id TEXT NOT NULL,
                    required_role TEXT NOT NULL,
                    status TEXT NOT NULL,
                    fencing_token INTEGER NOT NULL,
                    lease_worker TEXT,
                    lease_expires_at TEXT,
                    output_artifact_hash TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (work_order_id, work_order_version) 
                        REFERENCES work_orders (work_order_id, version)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id TEXT PRIMARY KEY,
                    work_order_id TEXT NOT NULL,
                    work_order_version INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def record_audit(
        self,
        work_order_id: str,
        work_order_version: int,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO audit_events (event_id, work_order_id, work_order_version, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    f"evt-{uuid.uuid4().hex[:12]}",
                    work_order_id,
                    work_order_version,
                    event_type,
                    canonical_json(payload),
                    now_iso,
                ),
            )
            conn.commit()

    def register_work_order(self, work_order: WorkOrder) -> None:
        """Register a work order into durable storage."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO work_orders (
                    work_order_id, version, predecessor_hash, contract_hash, 
                    state, terminal_disposition, fencing_token, data_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    work_order.work_order_id,
                    work_order.version,
                    work_order.predecessor_hash,
                    work_order.contract_hash,
                    str(work_order.state.current_stage),
                    work_order.state.terminal_disposition,
                    work_order.state.fencing_token,
                    canonical_json(work_order.to_dict()),
                    work_order.created_at,
                    now_iso,
                ),
            )
            conn.commit()
        self.record_audit(
            work_order.work_order_id,
            work_order.version,
            "WORK_ORDER_REGISTERED",
            {"state": str(work_order.state.current_stage), "contract_hash": work_order.contract_hash},
        )

    def initialize_plan(self, plan: ExecutionPlan) -> list[str]:
        """Materialize execution plan task assignments into durable state."""
        now_iso = datetime.now(timezone.utc).isoformat()
        assignment_ids = []
        with self._get_connection() as conn:
            # First task is READY, downstream tasks are PENDING
            for idx, step in enumerate(plan.steps):
                assignment_id = f"asgn-{uuid.uuid4().hex[:12]}"
                assignment_ids.append(assignment_id)
                initial_status = (
                    TaskStepState.READY if len(step.dependencies) == 0 else TaskStepState.PENDING
                )
                conn.execute(
                    """
                    INSERT INTO task_assignments (
                        assignment_id, work_order_id, work_order_version, step_id,
                        required_role, status, fencing_token, retry_count, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        assignment_id,
                        plan.work_order_id,
                        plan.work_order_version,
                        step.step_id,
                        step.required_role,
                        str(initial_status),
                        1,  # initial fencing token
                        0,
                        now_iso,
                        now_iso,
                    ),
                )
            conn.commit()
        return assignment_ids

    def acquire_lease(
        self,
        assignment_id: str,
        worker_id: str,
        lease_seconds: int = 60,
    ) -> int:
        """Atomically acquire a lease on a task assignment with an incremented fencing token."""
        now = datetime.now(timezone.utc)
        expires_at = datetime.fromtimestamp(now.timestamp() + lease_seconds, tz=timezone.utc).isoformat()
        now_iso = now.isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT fencing_token, status, work_order_id, work_order_version 
                FROM task_assignments 
                WHERE assignment_id = ?
                """,
                (assignment_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise WorkflowEngineError(f"Assignment {assignment_id} not found")

            if row["status"] in (str(TaskStepState.COMPLETED), str(TaskStepState.SUPERSEDED)):
                raise WorkflowEngineError(
                    f"Cannot lease task in terminal state {row['status']}",
                    FailureClass.SUPERSEDED if row["status"] == str(TaskStepState.SUPERSEDED) else None,
                )

            new_fencing_token = row["fencing_token"] + 1

            cursor.execute(
                """
                UPDATE task_assignments
                SET status = ?, lease_worker = ?, lease_expires_at = ?,
                    fencing_token = ?, updated_at = ?
                WHERE assignment_id = ? AND fencing_token = ?
                """,
                (
                    str(TaskStepState.DISPATCHED),
                    worker_id,
                    expires_at,
                    new_fencing_token,
                    now_iso,
                    assignment_id,
                    row["fencing_token"],
                ),
            )
            if cursor.rowcount == 0:
                raise WorkflowEngineError("Concurrent lease modification detected")

            conn.commit()

        return new_fencing_token

    def complete_assignment(
        self,
        assignment_id: str,
        fencing_token: int,
        output_artifact_hash: str,
    ) -> None:
        """Commit completion of an assignment with atomic fencing token verification."""
        now_iso = datetime.now(timezone.utc).isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT status, fencing_token, output_artifact_hash, work_order_id, work_order_version 
                FROM task_assignments 
                WHERE assignment_id = ?
                """,
                (assignment_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise WorkflowEngineError(f"Assignment {assignment_id} not found")

            current_status = row["status"]
            current_token = row["fencing_token"]
            existing_hash = row["output_artifact_hash"]

            if current_status == str(TaskStepState.SUPERSEDED):
                raise WorkflowEngineError(
                    f"Cannot commit result: assignment {assignment_id} was superseded",
                    FailureClass.SUPERSEDED,
                )

            # Strict fencing token check
            if current_token != fencing_token:
                raise WorkflowEngineError(
                    f"Stale fencing token: expected {current_token}, got {fencing_token}",
                    FailureClass.STALE_FENCING_TOKEN,
                )

            # Idempotency check: duplicate delivery with same token and hash
            if current_status == str(TaskStepState.COMPLETED):
                if existing_hash == output_artifact_hash:
                    return  # Idempotent success
                raise WorkflowEngineError(
                    f"Conflicting completion for assignment {assignment_id}: existing {existing_hash} != {output_artifact_hash}",
                    FailureClass.MALFORMED_OUTPUT,
                )

            # Atomic commit
            cursor.execute(
                """
                UPDATE task_assignments
                SET status = ?, output_artifact_hash = ?, updated_at = ?
                WHERE assignment_id = ? AND fencing_token = ? AND status = ?
                """,
                (
                    str(TaskStepState.COMPLETED),
                    output_artifact_hash,
                    now_iso,
                    assignment_id,
                    fencing_token,
                    str(TaskStepState.DISPATCHED),
                ),
            )
            if cursor.rowcount == 0:
                raise WorkflowEngineError(
                    "Failed to commit assignment completion (lease state changed concurrently)",
                    FailureClass.STALE_FENCING_TOKEN,
                )

            conn.commit()

        self.record_audit(
            row["work_order_id"],
            row["work_order_version"],
            "ASSIGNMENT_COMPLETED",
            {
                "assignment_id": assignment_id,
                "fencing_token": fencing_token,
                "output_artifact_hash": output_artifact_hash,
            },
        )

    def advance_ready_tasks(self, plan: ExecutionPlan) -> list[str]:
        """Check prerequisites in plan and advance PENDING tasks to READY."""
        now_iso = datetime.now(timezone.utc).isoformat()
        advanced = []
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT assignment_id, step_id, status 
                FROM task_assignments 
                WHERE work_order_id = ? AND work_order_version = ?
                """,
                (plan.work_order_id, plan.work_order_version),
            )
            assignments = {row["step_id"]: row for row in cursor.fetchall()}

            for step in plan.steps:
                asgn = assignments.get(step.step_id)
                if not asgn or asgn["status"] != str(TaskStepState.PENDING):
                    continue

                # Check if all dependencies are completed
                deps_met = True
                for dep_id in step.dependencies:
                    dep_asgn = assignments.get(dep_id)
                    if not dep_asgn or dep_asgn["status"] != str(TaskStepState.COMPLETED):
                        deps_met = False
                        break

                if deps_met:
                    cursor.execute(
                        """
                        UPDATE task_assignments 
                        SET status = ?, updated_at = ?
                        WHERE assignment_id = ?
                        """,
                        (str(TaskStepState.READY), now_iso, asgn["assignment_id"]),
                    )
                    advanced.append(asgn["assignment_id"])

            conn.commit()
        return advanced

    def supersede_work_order(self, work_order_id: str, version: int) -> None:
        """Mark active assignments and work order state as SUPERSEDED."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE work_orders
                SET state = ?, updated_at = ?
                WHERE work_order_id = ? AND version = ?
                """,
                (str(WorkOrderState.SUPERSEDED), now_iso, work_order_id, version),
            )
            conn.execute(
                """
                UPDATE task_assignments
                SET status = ?, updated_at = ?
                WHERE work_order_id = ? AND work_order_version = ?
                  AND status NOT IN (?, ?)
                """,
                (
                    str(TaskStepState.SUPERSEDED),
                    now_iso,
                    work_order_id,
                    version,
                    str(TaskStepState.COMPLETED),
                    str(TaskStepState.FAILED),
                ),
            )
            conn.commit()
        self.record_audit(
            work_order_id,
            version,
            "WORK_ORDER_SUPERSEDED",
            {"reason": "New version issued"},
        )

    def set_terminal_disposition(
        self,
        work_order_id: str,
        version: int,
        disposition: str,
        state: WorkOrderState,
    ) -> None:
        """Commit authoritative terminal disposition."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE work_orders
                SET terminal_disposition = ?, state = ?, updated_at = ?
                WHERE work_order_id = ? AND version = ?
                """,
                (disposition, str(state), now_iso, work_order_id, version),
            )
            conn.commit()
        self.record_audit(
            work_order_id,
            version,
            "TERMINAL_DISPOSITION_COMMITTED",
            {"disposition": disposition, "state": str(state)},
        )

    def get_work_order(self, work_order_id: str, version: int) -> dict[str, Any] | None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM work_orders WHERE work_order_id = ? AND version = ?
                """,
                (work_order_id, version),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return dict(row)

    def get_assignment(self, assignment_id: str) -> dict[str, Any] | None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM task_assignments WHERE assignment_id = ?
                """,
                (assignment_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return dict(row)

    def list_assignments(self, work_order_id: str, version: int) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM task_assignments 
                WHERE work_order_id = ? AND work_order_version = ?
                ORDER BY created_at ASC
                """,
                (work_order_id, version),
            )
            return [dict(row) for row in cursor.fetchall()]

    def list_audit_events(self, work_order_id: str, version: int) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM audit_events 
                WHERE work_order_id = ? AND work_order_version = ?
                ORDER BY created_at ASC
                """,
                (work_order_id, version),
            )
            return [dict(row) for row in cursor.fetchall()]
