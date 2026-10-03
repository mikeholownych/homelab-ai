"""Deterministic, non-blocking health and readiness manager for the T5820 orchestrator.

Distinguishes gateway process liveness, scheduler readiness, and downstream worker health.
Guarantees fail-closed evaluation, bounded freshness, and zero inference side effects on scrape.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

from . import engine_stats

# Engine stats older than this are not published (they would look current but be stale).
ENGINE_STATS_MAX_AGE_SECONDS = 15.0

# neutral engine-stat name -> registry attribute that exports it (all labelled worker_id, pool, engine)
_ENGINE_METRICS = {
    "requests_running": "engine_requests_running",
    "requests_waiting": "engine_requests_waiting",
    "kv_cache_usage": "engine_kv_cache_usage_ratio",
    "prefix_cache_hit_ratio": "engine_prefix_cache_hit_ratio",
    "generation_tokens_in_flight": "engine_generation_tokens_in_flight",
    "prompt_tokens_in_flight": "engine_prompt_tokens_in_flight",
    "prompt_tokens_total": "engine_prompt_tokens_total",
    "prompt_tokens_cached_total": "engine_prompt_tokens_cached_total",
    "generation_tokens_total": "engine_generation_tokens_total",
    "prompt_seconds_total": "engine_prompt_seconds_total",
    "generation_seconds_total": "engine_generation_seconds_total",
}

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
        probe_interval_seconds: float = 10.0,
        start_time: float | None = None,
        auto_start: bool = False,
        scheduling_mode: str | None = None,
    ) -> None:
        self.registry = registry
        self.adapters = adapters or {}
        self.metrics = metrics
        self.max_freshness_seconds = max_freshness_seconds
        self.probe_interval_seconds = probe_interval_seconds
        self.start_time = start_time or time.time()
        self.scheduling_mode = scheduling_mode or os.environ.get("ORCHESTRATOR_SCHEDULING_MODE", "CONFIGURATION_B_PLUS")
        self._states: dict[str, WorkerHealthState] = {}
        self._engine_stats: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self._stats_thread: threading.Thread | None = None
        self.stats_interval_seconds = max(0.5, float(os.environ.get("ORCHESTRATOR_ENGINE_STATS_INTERVAL_SECONDS", "1.0")))

        # Initialize health states for all workers currently registered
        self._sync_registered_workers()

        if auto_start:
            self.start()

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
                err_type = "timeout" if ("timeout" in error.lower() or "timed out" in error.lower()) else "connection_error"
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

                published_stats = self._engine_stats.get(wid)
                if published_stats is not None and now - published_stats["observed_at"] > ENGINE_STATS_MAX_AGE_SECONDS:
                    published_stats = None
                worker_summaries[wid] = {
                    "status": status_str,
                    "healthy": effective_healthy,
                    "pool": worker_record.get("pool", "lead"),
                    "engine": worker_record.get("engine", "unknown"),
                    "engine_stats": published_stats,
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
                "scheduling_mode": self.scheduling_mode,
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

    def probe_worker(self, worker_id: str) -> bool:
        """Probe a single worker via lightweight non-inference /v1/models call or adapter check."""
        worker_record = None
        for w in self.registry.snapshot():
            if w["worker_id"] == worker_id:
                worker_record = w
                break
        if worker_record is None:
            return False

        endpoint = worker_record.get("endpoint")
        auth_token = worker_record.get("auth_token")

        if endpoint and (endpoint.startswith("http://") or endpoint.startswith("https://")):
            url = endpoint.rstrip("/") + "/v1/models"
            headers = {}
            if auth_token:
                headers["Authorization"] = f"Bearer {auth_token}"
            req = urllib.request.Request(url, headers=headers, method="GET")
            t0 = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=2.0) as resp:
                    elapsed = time.monotonic() - t0
                    if 200 <= resp.status < 300:
                        self.record_worker_observation(worker_id, healthy=True, duration=elapsed)
                        self._collect_engine_stats(worker_record, endpoint, headers)
                        return True
                    else:
                        self.record_worker_observation(worker_id, healthy=False, duration=elapsed, error=f"http_{resp.status}")
                        return False
            except Exception as exc:
                elapsed = time.monotonic() - t0
                self.record_worker_observation(worker_id, healthy=False, duration=elapsed, error=str(exc))
                return False
        else:
            is_healthy = bool(worker_record.get("healthy", True))
            self.record_worker_observation(worker_id, healthy=is_healthy, duration=0.0)
            return is_healthy

    def _collect_engine_stats(self, worker_record: dict[str, Any], endpoint: str, headers: dict[str, str]) -> None:
        """Best-effort read of the engine's own metrics, re-published in a neutral shape.

        Never affects health: a failure here only leaves the previous stats in place until they age
        out of the published view (see ENGINE_STATS_MAX_AGE_SECONDS).
        """
        engine = worker_record.get("engine", "unknown")
        if engine in ("unknown", "", None):
            return
        try:
            req = urllib.request.Request(endpoint.rstrip("/") + "/metrics", headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                body = resp.read(4_000_000).decode("utf-8", errors="replace")
            slots = None
            if engine == "llama.cpp":
                # Live per-request progress (KV occupancy, in-flight tokens); optional and never fatal.
                try:
                    slots_req = urllib.request.Request(endpoint.rstrip("/") + "/slots", headers=headers, method="GET")
                    with urllib.request.urlopen(slots_req, timeout=2.0) as slots_resp:
                        slots = json.loads(slots_resp.read(4_000_000).decode("utf-8", errors="replace"))
                except Exception:
                    slots = None
            stats = engine_stats.extract(engine, body, slots)
        except Exception:
            return
        if stats is not None:
            stats["observed_at"] = time.time()
            with self._lock:
                engine_stats.with_live_counters(stats, self._engine_stats.get(worker_record["worker_id"]))
                self._engine_stats[worker_record["worker_id"]] = stats
            self._export_engine_metrics(worker_record, stats)

    def _engine_labels(self, worker_record: dict[str, Any]) -> dict[str, str]:
        return {"worker_id": worker_record["worker_id"], "pool": str(worker_record.get("pool", "lead")),
                "engine": str(worker_record.get("engine", "unknown"))}

    def _export_engine_metrics(self, worker_record: dict[str, Any], stats: dict[str, Any]) -> None:
        """Republish engine state as Prometheus series; a value the engine does not report is removed, not zeroed."""
        if not self.metrics:
            return
        labels = self._engine_labels(worker_record)
        for key, attribute in _ENGINE_METRICS.items():
            metric = getattr(self.metrics, attribute)
            value = stats.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                metric.set(float(value), **labels)
            else:
                metric.remove(**labels)

    def _retire_engine_metrics(self, worker_record: dict[str, Any]) -> None:
        if not self.metrics:
            return
        labels = self._engine_labels(worker_record)
        for attribute in _ENGINE_METRICS.values():
            getattr(self.metrics, attribute).remove(**labels)

    def collect_all_engine_stats(self) -> None:
        """Refresh engine statistics for every worker (independent of health probing)."""
        for w in self.registry.snapshot():
            endpoint, token = w.get("endpoint"), w.get("auth_token")
            if not endpoint or not str(endpoint).startswith(("http://", "https://")):
                continue
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            if self.metrics:
                self.metrics.worker_info.set(
                    1.0, worker_id=w["worker_id"], pool=str(w.get("pool", "lead")), engine=str(w.get("engine", "unknown")),
                    model=str(w.get("model_id", "unknown")), gpu=",".join(str(g) for g in w.get("gpu_assignment") or []) or "unknown")
            self._collect_engine_stats(w, endpoint, headers)
            # A reading that has aged out must disappear from the scrape instead of freezing at its last value.
            with self._lock:
                published = self._engine_stats.get(w["worker_id"])
                stale = published is not None and time.time() - published["observed_at"] > ENGINE_STATS_MAX_AGE_SECONDS
            if stale:
                self._retire_engine_metrics(w)

    def _stats_loop(self) -> None:
        """Frequent, lightweight engine-stats refresh so monitors can derive smooth token rates."""
        while not self._stop_event.is_set():
            try:
                self.collect_all_engine_stats()
            except Exception:
                pass
            if self._stop_event.wait(self.stats_interval_seconds):
                break

    def probe_all(self) -> None:
        """Probe all currently registered workers."""
        for w in self.registry.snapshot():
            self.probe_worker(w["worker_id"])

    def _poll_loop(self) -> None:
        """Periodic background polling loop that refreshes worker health."""
        # Initial probe
        try:
            self.probe_all()
        except Exception:
            pass

        while not self._stop_event.is_set():
            if self._stop_event.wait(self.probe_interval_seconds):
                break
            try:
                self.probe_all()
            except Exception:
                pass

    def start(self) -> None:
        """Start background polling thread."""
        with self._lock:
            if self._poll_thread is not None and self._poll_thread.is_alive():
                return
            self._stop_event.clear()
            self._poll_thread = threading.Thread(
                target=self._poll_loop, daemon=True, name="HealthManagerPoller"
            )
            self._poll_thread.start()
            self._stats_thread = threading.Thread(target=self._stats_loop, daemon=True, name="EngineStatsPoller")
            self._stats_thread.start()

    def stop(self) -> None:
        """Stop background polling thread."""
        self._stop_event.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=2.0)
        if self._stats_thread is not None:
            self._stats_thread.join(timeout=2.0)
