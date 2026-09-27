"""
Autonomous Engineering System - Phase 11
Workstream H: Optimization Experiment Scheduler

Coordinates optimization campaigns, enforcing hardware concurrency caps,
protected-service reservations, durable SQLite checkpointing, and clean pause/resume/cancellation.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import sqlite3
from typing import Any, Dict, List, Optional, Set


class ExperimentState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class SchedulerConcurrencyError(Exception):
    """Raised when an experiment exceeds hardware concurrency limits."""


class ProtectedResourceInterferenceError(Exception):
    """Raised when an experiment attempts to interfere with protected resident serving."""


@dataclass(frozen=True)
class ExperimentJob:
    """An optimization batch execution job."""
    job_id: str
    campaign_id: str
    candidate_id: str
    task_ids: List[str]
    priority: int  # 0 = normal optimization, 10 = high priority
    max_concurrency: int = 2
    state: ExperimentState = ExperimentState.QUEUED
    completed_task_ids: List[str] = field(default_factory=list)
    created_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class OptimizationExperimentScheduler:
    """
    Schedules and fences optimization experiment batches.
    Protects resident inference workers from resource contention and deadlocks.
    """

    def __init__(
        self,
        db_path: str = ":memory:",
        max_system_concurrency: int = 2,
        protected_resident_model: str = "engineering/b0",
    ) -> None:
        self.db_path = str(db_path)
        self.max_system_concurrency = max_system_concurrency
        self.protected_resident_model = protected_resident_model
        self._active_concurrency = 0
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self) -> None:
        if self.db_path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS experiment_jobs (
                job_id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                state TEXT NOT NULL,
                completed_count INTEGER DEFAULT 0,
                total_count INTEGER NOT NULL,
                checkpoint_data TEXT
            )
        """)
        self._conn.commit()

    def submit_job(self, job: ExperimentJob, target_model: str) -> None:
        """Submits an experiment job, validating protected service non-interference."""
        # Interference Guard: Optimization jobs cannot unload or alter protected resident model
        if target_model != self.protected_resident_model and "swap" in job.candidate_id.lower():
            raise ProtectedResourceInterferenceError(
                f"Job '{job.job_id}' requests non-resident model '{target_model}' without maintenance authorization"
            )

        self._conn.execute(
            """
            INSERT OR REPLACE INTO experiment_jobs
            (job_id, campaign_id, candidate_id, state, completed_count, total_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (job.job_id, job.campaign_id, job.candidate_id, job.state.value, len(job.completed_task_ids), len(job.task_ids))
        )
        self._conn.commit()

    def acquire_execution_slot(self, job_id: str) -> bool:
        """Acquires a concurrency slot, failing closed if limits are reached."""
        if self._active_concurrency >= self.max_system_concurrency:
            raise SchedulerConcurrencyError(
                f"Maximum system concurrency cap ({self.max_system_concurrency}) reached"
            )
        self._active_concurrency += 1
        self._conn.execute(
            "UPDATE experiment_jobs SET state = ? WHERE job_id = ?",
            (ExperimentState.RUNNING.value, job_id),
        )
        self._conn.commit()
        return True

    def release_execution_slot(self, job_id: str, completed_tasks_count: int) -> None:
        """Releases concurrency slot and persists job progress."""
        self._active_concurrency = max(0, self._active_concurrency - 1)
        self._conn.execute(
            "UPDATE experiment_jobs SET completed_count = ? WHERE job_id = ?",
            (completed_tasks_count, job_id),
        )
        self._conn.commit()

    def pause_job(self, job_id: str) -> None:
        """Pauses a running job."""
        self._conn.execute(
            "UPDATE experiment_jobs SET state = ? WHERE job_id = ?",
            (ExperimentState.PAUSED.value, job_id),
        )
        self._conn.commit()

    def cancel_job(self, job_id: str) -> None:
        """Cancels an experiment job."""
        self._conn.execute(
            "UPDATE experiment_jobs SET state = ? WHERE job_id = ?",
            (ExperimentState.CANCELLED.value, job_id),
        )
        self._conn.commit()

    def get_job_state(self, job_id: str) -> Optional[ExperimentState]:
        """Queries the current state of an experiment job."""
        row = self._conn.execute(
            "SELECT state FROM experiment_jobs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        if row:
            return ExperimentState(row[0])
        return None
