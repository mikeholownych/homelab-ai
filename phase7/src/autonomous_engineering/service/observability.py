"""Observability and Telemetry Collector for Autonomous Engineering Service."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Any, Optional


class ServiceHealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    STALLED = "STALLED"
    CRITICAL = "CRITICAL"


@dataclass
class TaskExecutionRecord:
    work_order_id: str
    version: int
    task_class: str
    started_at: float
    completed_at: Optional[float] = None
    state: str = "PENDING"
    terminal_disposition: Optional[str] = None
    repair_cycles: int = 0
    worker_id: Optional[str] = None
    error_message: Optional[str] = None


@dataclass
class ServiceTelemetrySnapshot:
    timestamp: str
    health_status: ServiceHealthStatus
    queue_depth: int
    active_tasks: int
    completed_tasks: int
    accepted_tasks: int
    rejected_tasks: int
    repaired_tasks: int
    stale_rejections: int
    leases_recovered: int
    mean_task_latency_seconds: float
    active_worker_count: int
    is_draining: bool
    diagnostics: List[str] = field(default_factory=list)


class ServiceObservability:
    """Collects, aggregates, and exposes live operational telemetry for unattended service."""

    def __init__(self, max_records: int = 1000) -> None:
        self.max_records = max_records
        self.records: Dict[str, TaskExecutionRecord] = {}
        self.stale_token_rejections: int = 0
        self.leases_recovered: int = 0
        self.active_workers: Dict[str, float] = {}
        self.is_draining: bool = False
        self._admission_stopped: bool = False

    def record_task_start(
        self, work_order_id: str, version: int, task_class: str, worker_id: Optional[str] = None
    ) -> None:
        key = f"{work_order_id}-v{version}"
        self.records[key] = TaskExecutionRecord(
            work_order_id=work_order_id,
            version=version,
            task_class=task_class,
            started_at=time.time(),
            worker_id=worker_id,
            state="EXECUTING",
        )
        if worker_id:
            self.active_workers[worker_id] = time.time()

    def record_task_completion(
        self,
        work_order_id: str,
        version: int,
        state: str,
        disposition: str,
        repair_cycles: int = 0,
        error_message: Optional[str] = None,
    ) -> None:
        key = f"{work_order_id}-v{version}"
        if key in self.records:
            rec = self.records[key]
            rec.completed_at = time.time()
            rec.state = state
            rec.terminal_disposition = disposition
            rec.repair_cycles = repair_cycles
            rec.error_message = error_message
            if rec.worker_id and rec.worker_id in self.active_workers:
                del self.active_workers[rec.worker_id]

    def record_stale_rejection(self) -> None:
        self.stale_token_rejections += 1

    def record_lease_recovery(self, count: int = 1) -> None:
        self.leases_recovered += count

    def set_draining(self, draining: bool) -> None:
        self.is_draining = draining

    def set_admission_stopped(self, stopped: bool) -> None:
        self._admission_stopped = stopped

    @property
    def is_admission_stopped(self) -> bool:
        return self._admission_stopped

    def get_snapshot(self, current_queue_depth: int = 0) -> ServiceTelemetrySnapshot:
        now_ts = datetime.now(timezone.utc).isoformat()
        active = [r for r in self.records.values() if r.completed_at is None]
        completed = [r for r in self.records.values() if r.completed_at is not None]
        accepted = [r for r in completed if r.state == "ACCEPTED"]
        rejected = [r for r in completed if r.state in ("REJECTED", "REVOKED", "FAILED")]
        repaired = [r for r in completed if r.repair_cycles > 0]

        latencies = [
            r.completed_at - r.started_at for r in completed if r.completed_at is not None
        ]
        mean_latency = sum(latencies) / len(latencies) if latencies else 0.0

        diagnostics = []
        health = ServiceHealthStatus.HEALTHY

        # Detect stalls
        now = time.time()
        stalled_tasks = [r for r in active if (now - r.started_at) > 120.0]
        if stalled_tasks:
            health = ServiceHealthStatus.DEGRADED
            diagnostics.append(f"{len(stalled_tasks)} tasks active for >120s")

        if self.is_draining:
            diagnostics.append("Service is in DRAINING mode")
        if self._admission_stopped:
            diagnostics.append("Task admission is STOPPED by operator")

        return ServiceTelemetrySnapshot(
            timestamp=now_ts,
            health_status=health,
            queue_depth=current_queue_depth,
            active_tasks=len(active),
            completed_tasks=len(completed),
            accepted_tasks=len(accepted),
            rejected_tasks=len(rejected),
            repaired_tasks=len(repaired),
            stale_rejections=self.stale_token_rejections,
            leases_recovered=self.leases_recovered,
            mean_task_latency_seconds=mean_latency,
            active_worker_count=len(self.active_workers),
            is_draining=self.is_draining,
            diagnostics=diagnostics,
        )
