"""Persistent Engineering Service Daemon for Autonomous Execution."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.authority.admission import AdmissionEvaluator
from autonomous_engineering.core.types import (
    ArtifactType,
    TaskStepState,
    ValidationStatus,
    WorkOrderState,
)
from autonomous_engineering.workflow.engine import WorkflowEngine, WorkflowEngineError
from autonomous_engineering.workflow.heterogeneous_engine import (
    DeliverableBundle,
    HeterogeneousEngineeringPipeline,
)

logger = logging.getLogger(__name__)


@dataclass
class ServiceOperatingMetrics:
    total_work_orders_processed: int = 0
    accepted_work_orders: int = 0
    rejected_work_orders: int = 0
    repaired_work_orders: int = 0
    stale_tokens_rejected: int = 0
    leases_recovered: int = 0
    total_execution_time_seconds: float = 0.0
    restart_recovery_count: int = 0


class PersistentEngineeringService:
    """Persistent engineering service daemon that safely and durably executes admitted work orders.
    
    Guarantees:
    - Runs independently of client CLI connections.
    - Atomically manages task leases with monotonic fencing tokens.
    - Recovers in-flight work orders across service process restarts.
    - Prevents zombie or stale workers from committing results.
    """

    def __init__(
        self,
        engine: WorkflowEngine,
        artifact_store: ArtifactStore,
        pipeline: HeterogeneousEngineeringPipeline,
        poll_interval_seconds: float = 0.1,
    ) -> None:
        self.engine = engine
        self.artifact_store = artifact_store
        self.pipeline = pipeline
        self.poll_interval = poll_interval_seconds
        self.metrics = ServiceOperatingMetrics()
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Starts the persistent background execution service loop."""
        self._running = True
        self._recover_stale_leases_on_startup()
        self._worker_thread = threading.Thread(target=self._service_loop, daemon=True)
        self._worker_thread.start()
        logger.info("PersistentEngineeringService started.")

    def stop(self) -> None:
        """Gracefully stops the persistent background execution loop."""
        self._running = False
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5.0)
        logger.info("PersistentEngineeringService stopped.")

    def process_pending_work_orders(self) -> int:
        """Processes all admitted and ready work orders in the queue."""
        processed = 0
        admitted = self._find_admitted_work_orders()
        for wo in admitted:
            wo_id = wo["work_order_id"]
            ver = wo["version"]
            t0 = time.perf_counter()
            try:
                state = self.pipeline.execute_lifecycle(wo_id, ver)
                dt = time.perf_counter() - t0
                self.metrics.total_execution_time_seconds += dt
                self.metrics.total_work_orders_processed += 1
                if state == WorkOrderState.ACCEPTED:
                    self.metrics.accepted_work_orders += 1
                else:
                    self.metrics.rejected_work_orders += 1
                processed += 1
            except Exception as e:
                logger.error(f"Error executing work order {wo_id} v{ver}: {e}")
                self.metrics.rejected_work_orders += 1
        return processed

    def _service_loop(self) -> None:
        while self._running:
            try:
                self.process_pending_work_orders()
            except Exception as err:
                logger.error(f"Unexpected error in service loop: {err}")
            time.sleep(self.poll_interval)

    def _recover_stale_leases_on_startup(self) -> int:
        """Scans for abandoned or expired leases from prior crashes and reclaims them."""
        recovered = 0
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.engine._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT assignment_id, fencing_token 
                FROM task_assignments 
                WHERE status = ? AND (lease_expires_at IS NULL OR lease_expires_at < ?)
                """,
                (str(TaskStepState.DISPATCHED), now_iso),
            )
            rows = cursor.fetchall()
            for r in rows:
                cursor.execute(
                    """
                    UPDATE task_assignments 
                    SET status = ?, lease_worker = NULL, lease_expires_at = NULL,
                        fencing_token = fencing_token + 1, updated_at = ?
                    WHERE assignment_id = ?
                    """,
                    (str(TaskStepState.READY), now_iso, r["assignment_id"]),
                )
                recovered += 1
            conn.commit()

        if recovered > 0:
            self.metrics.leases_recovered += recovered
            self.metrics.restart_recovery_count += 1
            logger.info(f"Crash recovery: reclaimed {recovered} abandoned task assignments.")
        return recovered

    def _find_admitted_work_orders(self) -> List[Dict[str, Any]]:
        with self.engine._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT work_order_id, version, state 
                FROM work_orders 
                WHERE state = ?
                ORDER BY created_at ASC
                """,
                (str(WorkOrderState.ADMITTED),),
            )
            return [dict(r) for r in cursor.fetchall()]
