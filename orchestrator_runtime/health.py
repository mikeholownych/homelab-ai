"""Deterministic, non-blocking health and readiness manager for the T5820 orchestrator.

Distinguishes gateway process liveness, scheduler readiness, and downstream worker health.
Guarantees fail-closed evaluation, bounded freshness, and zero inference side effects on scrape.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from orchestrator_runtime.metrics import MetricsRegistry
    from orchestrator_runtime.runtime import CapabilityRegistry, ProviderAdapter


@dataclass
class WorkerHealthState:
    """Observed health state for a single model worker."""

    worker_id: str
    healthy: bool
    status: str  # "healthy", "unhealthy", "stale", "unknown"
    last_observed_timestamp: float
    last_observed_iso: str
    check_duration_seconds: float = 0.0
    error_message: str | None = None
    consecutive_failures: int = 0


class HealthManager:
    """Manages worker health observations and evaluates gateway health and readiness."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        adapters: dict[str, ProviderAdapter] | None = None,
        metrics: MetricsRegistry | None = None,
        *,
        max_freshness_seconds: float = 30.0,
        start_time: float | None = None,
    ) -> None:
        self.registry = registry
        self.adapters = adapters or {}
        self.metrics = metrics
        self.max_freshness_seconds = max_freshness_seconds
        self.start_time = start_time or time.time()
        self._states: dict[str, WorkerHealthState] = {}
        self._lock = threading.RLock()

        # Initialize health states for all workers currently registered
        self._sync_registered_workers()

    def _sync_registered_workers(self) -> None:
        """Ensure all workers in the registry have an initial observation state."""
        now = time.time()
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            for worker_dict in self.registry.snapshot():
                wid = worker_dict["worker_id"]
                is_healthy = bool(worker_dict.get("healthy", True))
                if wid not in self._states:
                    self._states[wid] = WorkerHealthState(
                        worker_id=wid,
                        healthy=is_healthy,
                        status="healthy" if is_healthy else "unhealthy",
                        last_observed_timestamp=now,
                        last_observed_iso=now_iso,
                        check_duration_seconds=0.0,
                        consecutive_failures=0 if is_healthy else 1,
                    )
                    if self.metrics:
                        self.metrics.worker_health_status.set(1.0 if is_healthy else 0.0, worker_id=wid)
                        self.metrics.worker_last_check_timestamp_seconds.set(now, worker_id=wid)
                        self.metrics.scheduler_worker_available.set(1.0 if is_healthy else 0.0, worker_id=wid)

    def record_worker_observation(
        self,
        worker_id: str,
        healthy: bool,
        duration: float = 0.0,
        error: str | None = None,
    ) -> None:
        """Record the outcome of an inference execution or background probe."""
        now = time.time()
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            prev = self._states.get(worker_id)
            consecutive = (0 if healthy else (prev.consecutive_failures + 1 if prev else 1))
            status = "healthy" if healthy else "unhealthy"
            self._states[worker_id] = WorkerHealthState(
                worker_id=worker_id,
                healthy=healthy,
                status=status,
                last_observed_timestamp=now,
                last_observed_iso=now_iso,
                check_duration_seconds=duration,
                error_message=error,
                consecutive_failures=consecutive,
            )

        # Synchronize capability registry and metrics
        try:
            self.registry.update_health(worker_id, healthy)
        except Exception:
            pass

        if self.metrics:
            self.metrics.worker_health_status.set(1.0 if healthy else 0.0, worker_id=worker_id)
            self.metrics.worker_last_check_timestamp_seconds.set(now, worker_id=worker_id)
            self.metrics.worker_check_duration_seconds.set(duration, worker_id=worker_id)
            self.metrics.scheduler_worker_available.set(1.0 if healthy else 0.0, worker_id=worker_id)
            if not healthy and error:
                err_type = "timeout" if "timeout" in error.lower() else "connection_error"
                self.metrics.provider_errors_total.inc(worker_id=worker_id, error_type=err_type)

    def check(self, *, strict: bool = False) -> tuple[int, dict[str, Any]]:
        """Evaluate non-blocking operational health and return (http_status, json_dict).

        Does NOT make downstream network calls during evaluation.
        """
        now = time.time()
        now_iso = datetime.now(timezone.utc).isoformat()

        with self._lock:
            self._sync_registered_workers()
            registered_workers = {w["worker_id"]: w for w in self.registry.snapshot()}
            total_registered = len(registered_workers)

            worker_summaries: dict[str, dict[str, Any]] = {}
            healthy_count = 0
            unhealthy_count = 0
            stale_count = 0
            max_age = 0.0

            for wid, worker_record in registered_workers.items():
                state = self._states.get(wid)
                if state is None:
                    worker_summaries[wid] = {
                        "status": "unknown",
                        "healthy": False,
                        "public_model_id": worker_record.get("public_model_id", "unknown"),
                        "model_id": worker_record.get("model_id", "unknown"),
                        "last_observed_seconds_ago": None,
                        "last_check_timestamp": None,
                        "consecutive_failures": 0,
                    }
                    unhealthy_count += 1
                    continue

                age = max(0.0, now - state.last_observed_timestamp)
                if age > max_age:
                    max_age = age

                is_stale = age > self.max_freshness_seconds
                if is_stale:
                    status_str = "stale"
                    stale_count += 1
                    effective_healthy = False
                elif not state.healthy:
                    status_str = "unhealthy"
                    unhealthy_count += 1
                    effective_healthy = False
                else:
                    status_str = "healthy"
                    healthy_count += 1
                    effective_healthy = True

                worker_summaries[wid] = {
                    "status": status_str,
                    "healthy": effective_healthy,
                    "public_model_id": worker_record.get("public_model_id", "unknown"),
                    "model_id": worker_record.get("model_id", "unknown"),
                    "last_observed_seconds_ago": round(age, 3),
                    "last_check_timestamp": state.last_observed_iso,
                    "consecutive_failures": state.consecutive_failures,
                }

        # Deterministic status resolution
        if total_registered == 0:
            overall_status = "unavailable"
            ready = False
            can_route = False
            http_status = HTTPStatus.SERVICE_UNAVAILABLE
        elif healthy_count == total_registered:
            overall_status = "healthy"
            ready = True
            can_route = True
            http_status = HTTPStatus.OK
        elif healthy_count > 0:
            # At least one worker available: degraded but functional
            overall_status = "degraded"
            ready = True
            can_route = True
            http_status = HTTPStatus.SERVICE_UNAVAILABLE if strict else HTTPStatus.OK
        else:
            # Zero healthy workers
            overall_status = "unavailable"
            ready = False
            can_route = False
            http_status = HTTPStatus.SERVICE_UNAVAILABLE

        queued_work = 0
        active_work = 0
        if self.metrics:
            queued_work = int(self.metrics.scheduler_queued_work.get())
            active_work = int(self.metrics.scheduler_active_work.get())

        payload = {
            "status": overall_status,
            "ready": ready,
            "can_route": can_route,
            "timestamp": now_iso,
            "gateway": {
                "status": "alive",
                "uptime_seconds": round(now - self.start_time, 3),
                "pid": os.getpid(),
            },
            "scheduler": {
                "ready": can_route,
                "status": "ready" if can_route else "blocked",
                "queued_work": queued_work,
                "active_work": active_work,
                "available_workers": healthy_count,
                "total_workers": total_registered,
            },
            "workers": worker_summaries,
            "dependency_freshness": {
                "freshness_seconds": round(max_age, 3),
                "max_ttl_seconds": self.max_freshness_seconds,
                "is_stale": stale_count > 0,
            },
        }

        return int(http_status), payload
