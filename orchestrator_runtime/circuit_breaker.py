"""Enterprise-grade Circuit Breaker pattern for workers and pools.

Provides automatic failure detection, fast failover without latency penalty,
cooldown probing, and recovery across Closed, Open, and Half-Open states.
"""
from __future__ import annotations

import enum
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable


class CircuitState(str, enum.Enum):
    CLOSED = "closed"        # Normal operation: requests allowed
    OPEN = "open"            # Tripped: requests blocked, fast-fail to fallback
    HALF_OPEN = "half_open"  # Trial period: probing healthy recovery


@dataclass
class FailureEvent:
    timestamp: float
    is_failure: bool


class CircuitBreaker:
    """Thread-safe circuit breaker with sliding window and consecutive failure tracking."""

    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int = 5,
        recovery_timeout: float = 15.0,
        half_open_probes_required: int = 2,
        error_window_seconds: float = 10.0,
        error_rate_threshold: float = 0.5,
        min_requests_for_error_rate: int = 4,
        on_state_change: Callable[[str, CircuitState, CircuitState, str], None] | None = None,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_probes_required = half_open_probes_required
        self.error_window_seconds = error_window_seconds
        self.error_rate_threshold = error_rate_threshold
        self.min_requests_for_error_rate = min_requests_for_error_rate
        self.on_state_change = on_state_change

        self._lock = threading.RLock()
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._successful_probes = 0
        self._last_state_change = time.monotonic()
        self._tripped_at: float | None = None
        self._recent_events: deque[FailureEvent] = deque()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._check_auto_half_open()
            return self._state

    def _check_auto_half_open(self) -> None:
        """Transitions from OPEN to HALF_OPEN if the recovery timeout has expired."""
        if self._state == CircuitState.OPEN and self._tripped_at is not None:
            now = time.monotonic()
            if now - self._tripped_at >= self.recovery_timeout:
                self._transition_to(
                    CircuitState.HALF_OPEN,
                    f"recovery timeout of {self.recovery_timeout:.1f}s expired; entering trial phase",
                )

    def _transition_to(self, new_state: CircuitState, reason: str) -> None:
        old_state = self._state
        if old_state == new_state:
            return
        self._state = new_state
        self._last_state_change = time.monotonic()
        if new_state == CircuitState.OPEN:
            self._tripped_at = time.monotonic()
            self._successful_probes = 0
        elif new_state == CircuitState.CLOSED:
            self._tripped_at = None
            self._consecutive_failures = 0
            self._successful_probes = 0
        elif new_state == CircuitState.HALF_OPEN:
            self._successful_probes = 0

        if self.on_state_change:
            try:
                self.on_state_change(self.name, old_state, new_state, reason)
            except Exception:  # noqa: BLE001
                pass

    def allow_request(self) -> bool:
        """Determines if a request should be dispatched to this target."""
        with self._lock:
            self._check_auto_half_open()
            if self._state == CircuitState.CLOSED:
                return True
            if self._state == CircuitState.HALF_OPEN:
                return True
            return False

    def record_success(self) -> None:
        """Records a successful upstream call."""
        now = time.monotonic()
        with self._lock:
            self._recent_events.append(FailureEvent(now, is_failure=False))
            self._purge_old_events(now)

            if self._state == CircuitState.HALF_OPEN:
                self._successful_probes += 1
                if self._successful_probes >= self.half_open_probes_required:
                    self._transition_to(
                        CircuitState.CLOSED,
                        f"recovered after {self._successful_probes} consecutive successful probes",
                    )
            elif self._state == CircuitState.CLOSED:
                self._consecutive_failures = 0

    def record_failure(self, error: Any = None, is_fatal: bool = True) -> None:
        """Records a failed upstream call (connection error, 5xx, or timeout)."""
        now = time.monotonic()
        error_desc = str(error) if error else "unknown upstream failure"
        with self._lock:
            self._recent_events.append(FailureEvent(now, is_failure=True))
            self._purge_old_events(now)
            self._consecutive_failures += 1

            if self._state == CircuitState.HALF_OPEN:
                # Any failure during half-open trial immediately trips back to OPEN
                self._transition_to(
                    CircuitState.OPEN,
                    f"failed during half-open trial ({error_desc}); extending cooldown",
                )
                return

            if self._state == CircuitState.CLOSED:
                # Check consecutive failure threshold
                if self._consecutive_failures >= self.failure_threshold:
                    self._transition_to(
                        CircuitState.OPEN,
                        f"reached {self._consecutive_failures} consecutive failures ({error_desc})",
                    )
                    return

                # Check windowed error rate threshold
                total = len(self._recent_events)
                if total >= self.min_requests_for_error_rate:
                    fails = sum(1 for e in self._recent_events if e.is_failure)
                    error_rate = fails / total
                    if error_rate >= self.error_rate_threshold:
                        self._transition_to(
                            CircuitState.OPEN,
                            f"error rate {error_rate:.1%} in {self.error_window_seconds}s exceeded threshold {self.error_rate_threshold:.1%}",
                        )

    def _purge_old_events(self, now: float) -> None:
        cutoff = now - self.error_window_seconds
        while self._recent_events and self._recent_events[0].timestamp < cutoff:
            self._recent_events.popleft()

    def reset(self) -> None:
        with self._lock:
            self._recent_events.clear()
            self._transition_to(CircuitState.CLOSED, "manual reset")

    def describe(self) -> dict[str, Any]:
        with self._lock:
            self._check_auto_half_open()
            return {
                "name": self.name,
                "state": self._state.value,
                "consecutive_failures": self._consecutive_failures,
                "successful_probes": self._successful_probes,
                "last_changed_seconds_ago": round(time.monotonic() - self._last_state_change, 2),
                "tripped": self._state == CircuitState.OPEN,
            }


class CircuitBreakerRegistry:
    """Manages both worker-level and pool-level circuit breakers."""

    def __init__(
        self,
        *,
        worker_failure_threshold: int = 5,
        pool_failure_threshold: int = 7,
        recovery_timeout: float = 15.0,
        evidence: Any = None,
        metrics: Any = None,
    ) -> None:
        self.worker_failure_threshold = worker_failure_threshold
        self.pool_failure_threshold = pool_failure_threshold
        self.recovery_timeout = recovery_timeout
        self.evidence = evidence
        self.metrics = metrics

        self._lock = threading.RLock()
        self._worker_breakers: dict[str, CircuitBreaker] = {}
        self._pool_breakers: dict[str, CircuitBreaker] = {}

    def _on_state_change(self, name: str, old_state: CircuitState, new_state: CircuitState, reason: str) -> None:
        # Evidence logging
        if self.evidence is not None:
            try:
                target_type, target_id = name.split(":", 1)
                self.evidence.append(
                    "circuit_breaker_transition",
                    target_type=target_type,
                    target_id=target_id,
                    from_state=old_state.value,
                    to_state=new_state.value,
                    reason=reason,
                )
            except Exception:  # noqa: BLE001
                pass

        # Prometheus metrics update
        if self.metrics is not None and hasattr(self.metrics, "circuit_breaker_state"):
            try:
                target_type, target_id = name.split(":", 1)
                state_val = 1.0 if new_state == CircuitState.OPEN else (0.5 if new_state == CircuitState.HALF_OPEN else 0.0)
                self.metrics.circuit_breaker_state.set(state_val, target_type=target_type, target_id=target_id)
            except Exception:  # noqa: BLE001
                pass

    def worker_breaker(self, worker_id: str) -> CircuitBreaker:
        with self._lock:
            if worker_id not in self._worker_breakers:
                self._worker_breakers[worker_id] = CircuitBreaker(
                    f"worker:{worker_id}",
                    failure_threshold=self.worker_failure_threshold,
                    recovery_timeout=self.recovery_timeout,
                    on_state_change=self._on_state_change,
                )
                if self.metrics is not None and hasattr(self.metrics, "circuit_breaker_state"):
                    try:
                        self.metrics.circuit_breaker_state.set(0.0, target_type="worker", target_id=worker_id)
                    except Exception:  # noqa: BLE001
                        pass
            return self._worker_breakers[worker_id]

    def pool_breaker(self, pool_name: str) -> CircuitBreaker:
        with self._lock:
            if pool_name not in self._pool_breakers:
                self._pool_breakers[pool_name] = CircuitBreaker(
                    f"pool:{pool_name}",
                    failure_threshold=self.pool_failure_threshold,
                    recovery_timeout=self.recovery_timeout,
                    on_state_change=self._on_state_change,
                )
                if self.metrics is not None and hasattr(self.metrics, "circuit_breaker_state"):
                    try:
                        self.metrics.circuit_breaker_state.set(0.0, target_type="pool", target_id=pool_name)
                    except Exception:  # noqa: BLE001
                        pass
            return self._pool_breakers[pool_name]

    def is_worker_available(self, worker_id: str) -> bool:
        return self.worker_breaker(worker_id).allow_request()

    def is_pool_available(self, pool_name: str) -> bool:
        return self.pool_breaker(pool_name).allow_request()

    def record_success(self, worker_id: str, pool_name: str | None = None) -> None:
        self.worker_breaker(worker_id).record_success()
        if pool_name:
            self.pool_breaker(pool_name).record_success()

    def record_failure(self, worker_id: str, pool_name: str | None = None, error: Any = None) -> None:
        self.worker_breaker(worker_id).record_failure(error)
        if pool_name:
            self.pool_breaker(pool_name).record_failure(error)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "workers": {wid: b.describe() for wid, b in self._worker_breakers.items()},
                "pools": {pid: b.describe() for pid, b in self._pool_breakers.items()},
            }
