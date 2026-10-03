"""Concurrency-safe, zero-dependency Prometheus metrics registry and instruments.

Implements Prometheus text exposition format 0.0.4 with strictly bounded
cardinality labels, monotonic counters, thread-safe gauges, and latency histograms.
"""

from __future__ import annotations

import threading
import time
from typing import Any


def _escape_label_value(val: str) -> str:
    """Escape label values according to Prometheus text exposition format 0.0.4."""
    return str(val).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format_labels(
    label_names: tuple[str, ...],
    label_values: tuple[str, ...],
    extra: dict[str, str] | None = None,
) -> str:
    parts: list[str] = []
    for name, val in zip(label_names, label_values):
        parts.append(f'{name}="{_escape_label_value(val)}"')
    if extra:
        for name, val in extra.items():
            parts.append(f'{name}="{_escape_label_value(val)}"')
    if not parts:
        return ""
    return "{" + ",".join(parts) + "}"


def _format_value(value: float) -> str:
    """Exact sample value: integers without a decimal point, other floats at full round-trip precision.

    (A fixed 6-significant-digit format makes large second-valued counters advance in coarse steps, which
    corrupts rate() and histogram sums once they grow.)"""
    value = float(value)
    if value != value:
        return "NaN"
    if value in (float("inf"), float("-inf")):
        return "+Inf" if value > 0 else "-Inf"
    if value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return repr(value)


class Counter:
    """Thread-safe monotonic counter."""

    def __init__(self, name: str, help_text: str, label_names: tuple[str, ...] = ()) -> None:
        self.name = name
        self.help_text = help_text
        self.label_names = label_names
        self._values: dict[tuple[str, ...], float] = {}
        self._lock = threading.Lock()

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        if amount < 0:
            raise ValueError("Counters can only be incremented by non-negative amounts")
        key = tuple(str(labels.get(k, "")) for k in self.label_names)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def get(self, **labels: str) -> float:
        key = tuple(str(labels.get(k, "")) for k in self.label_names)
        with self._lock:
            return self._values.get(key, 0.0)

    def collect(self) -> list[str]:
        with self._lock:
            items = sorted(self._values.items(), key=lambda kv: kv[0])
        if not items:
            # If no samples, emit zero for bare metric if unlabelled
            if not self.label_names:
                return [
                    f"# HELP {self.name} {self.help_text}",
                    f"# TYPE {self.name} counter",
                    f"{self.name} 0",
                ]
            return []
        lines = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} counter",
        ]
        for key, val in items:
            label_str = _format_labels(self.label_names, key)
            lines.append(f"{self.name}{label_str} {_format_value(val)}")
        return lines


class Gauge:
    """Thread-safe gauge representing arbitrary instantaenous numerical state."""

    def __init__(self, name: str, help_text: str, label_names: tuple[str, ...] = ()) -> None:
        self.name = name
        self.help_text = help_text
        self.label_names = label_names
        self._values: dict[tuple[str, ...], float] = {}
        self._lock = threading.Lock()

    def set(self, value: float, **labels: str) -> None:
        key = tuple(str(labels.get(k, "")) for k in self.label_names)
        with self._lock:
            self._values[key] = float(value)

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = tuple(str(labels.get(k, "")) for k in self.label_names)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def dec(self, amount: float = 1.0, **labels: str) -> None:
        key = tuple(str(labels.get(k, "")) for k in self.label_names)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) - amount

    def remove(self, **labels: str) -> None:
        """Drop a series so a stale reading is absent from the scrape instead of frozen at its last value."""
        key = tuple(str(labels.get(k, "")) for k in self.label_names)
        with self._lock:
            self._values.pop(key, None)

    def get(self, **labels: str) -> float:
        key = tuple(str(labels.get(k, "")) for k in self.label_names)
        with self._lock:
            return self._values.get(key, 0.0)

    def collect(self) -> list[str]:
        with self._lock:
            items = sorted(self._values.items(), key=lambda kv: kv[0])
        if not items:
            if not self.label_names:
                return [
                    f"# HELP {self.name} {self.help_text}",
                    f"# TYPE {self.name} gauge",
                    f"{self.name} 0",
                ]
            return []
        lines = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} gauge",
        ]
        for key, val in items:
            label_str = _format_labels(self.label_names, key)
            lines.append(f"{self.name}{label_str} {_format_value(val)}")
        return lines


class MirroredCounter(Gauge):
    """A cumulative counter owned by another system (an inference engine), re-exported verbatim.

    The value is set, never incremented here. When the engine restarts its counter drops; that is a normal
    counter reset to Prometheus, which handles it in rate(). Absent (removed) when the reading is stale.
    """

    def collect(self) -> list[str]:
        lines = super().collect()
        return [line.replace(" gauge", " counter", 1) if line.startswith("# TYPE") else line for line in lines]


class Histogram:
    """Thread-safe cumulative histogram for latency and size distributions."""

    DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)

    def __init__(
        self,
        name: str,
        help_text: str,
        label_names: tuple[str, ...] = (),
        buckets: tuple[float, ...] | None = None,
    ) -> None:
        self.name = name
        self.help_text = help_text
        self.label_names = label_names
        self.buckets = tuple(sorted(buckets or self.DEFAULT_BUCKETS))
        # Map: key -> (bucket_counts: list[int], total_count: int, total_sum: float)
        self._data: dict[tuple[str, ...], tuple[list[int], int, float]] = {}
        self._lock = threading.Lock()

    def observe(self, value: float, **labels: str) -> None:
        val = float(value)
        key = tuple(str(labels.get(k, "")) for k in self.label_names)
        with self._lock:
            if key not in self._data:
                self._data[key] = ([0] * len(self.buckets), 0, 0.0)
            counts, count, sum_val = self._data[key]
            for i, upper in enumerate(self.buckets):
                if val <= upper:
                    counts[i] += 1
            self._data[key] = (counts, count + 1, sum_val + val)

    def get_summary(self, **labels: str) -> tuple[int, float]:
        """Return (count, sum) for the given label values."""
        key = tuple(str(labels.get(k, "")) for k in self.label_names)
        with self._lock:
            if key not in self._data:
                return (0, 0.0)
            _, count, sum_val = self._data[key]
            return (count, sum_val)

    def collect(self) -> list[str]:
        with self._lock:
            items = sorted(self._data.items(), key=lambda kv: kv[0])
        if not items:
            if not self.label_names:
                lines = [
                    f"# HELP {self.name} {self.help_text}",
                    f"# TYPE {self.name} histogram",
                ]
                for b in self.buckets:
                    lines.append(f'{self.name}_bucket{{le="{b}"}} 0')
                lines.append(f'{self.name}_bucket{{le="+Inf"}} 0')
                lines.append(f"{self.name}_sum 0")
                lines.append(f"{self.name}_count 0")
                return lines
            return []
        lines = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} histogram",
        ]
        for key, (b_counts, count, sum_val) in items:
            cum_count = 0
            for b_idx, bound in enumerate(self.buckets):
                cum_count = b_counts[b_idx]
                b_labels = _format_labels(self.label_names, key, extra={"le": str(bound)})
                lines.append(f"{self.name}_bucket{b_labels} {cum_count}")
            inf_labels = _format_labels(self.label_names, key, extra={"le": "+Inf"})
            lines.append(f"{self.name}_bucket{inf_labels} {count}")
            base_labels = _format_labels(self.label_names, key)
            lines.append(f"{self.name}_sum{base_labels} {_format_value(sum_val)}")
            lines.append(f"{self.name}_count{base_labels} {count}")
        return lines


class MetricsRegistry:
    """Authoritative registry containing all production metrics for the T5820 orchestrator."""

    def __init__(self, start_time: float | None = None) -> None:
        self.start_time = start_time or time.time()
        self._lock = threading.RLock()
        self._metrics: list[Counter | Gauge | Histogram] = []

        # ---------------------------------------------------------------------
        # 1. Gateway and HTTP
        # ---------------------------------------------------------------------
        self.gateway_uptime_seconds = self._register_gauge(
            "aihost_gateway_uptime_seconds",
            "Current uptime of the orchestrator gateway process in seconds.",
        )
        self.gateway_start_time_seconds = self._register_gauge(
            "aihost_gateway_start_time_seconds",
            "Process start time in seconds since the Unix epoch.",
        )
        self.gateway_start_time_seconds.set(self.start_time)

        self.http_requests_total = self._register_counter(
            "aihost_http_requests_total",
            "Total number of HTTP requests processed by the gateway.",
            ("route", "method", "status_class"),
        )
        self.http_request_duration_seconds = self._register_histogram(
            "aihost_http_request_duration_seconds",
            "HTTP request duration in seconds.",
            ("route", "method"),
            (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
        )
        self.http_requests_in_flight = self._register_gauge(
            "aihost_http_requests_in_flight",
            "Current number of in-flight HTTP requests being handled by the gateway.",
            ("route",),
        )
        self.http_auth_failures_total = self._register_counter(
            "aihost_http_auth_failures_total",
            "Total number of authentication failures rejected by the gateway.",
            ("route",),
        )

        # ---------------------------------------------------------------------
        # 2. Inference routing
        # ---------------------------------------------------------------------
        self.inference_requests_total = self._register_counter(
            "aihost_inference_requests_total",
            "Total number of inference requests submitted to the runtime.",
            ("status",),
        )
        self.inference_dispatches_total = self._register_counter(
            "aihost_inference_dispatches_total",
            "Total number of inference requests dispatched to a worker.",
            ("worker_id", "model"),
        )
        self.inference_completions_total = self._register_counter(
            "aihost_inference_completions_total",
            "Inference requests that reached a worker, by outcome (completed, failed, timed_out, rejected). "
            "`rejected` means the request itself was invalid for the worker (caller fault, e.g. context overflow or "
            "malformed history) and says nothing about worker health; `failure_class` is `none` for completed.",
            ("worker_id", "outcome", "failure_class"),
        )
        self.inference_duration_seconds = self._register_histogram(
            "aihost_inference_duration_seconds",
            "Wall time the gateway spent on the worker call, in seconds. Includes any queueing inside the engine "
            "(see aihost_engine_requests_waiting); it is not time-to-first-token.",
            ("worker_id", "model", "pool"),
            (0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0),
        )
        self.inference_ttft_seconds = self._register_histogram(
            "aihost_inference_ttft_seconds",
            "Time to first token in seconds. Only observed for streaming upstream calls; the gateway currently "
            "calls workers without streaming, so this family has no samples.",
            ("worker_id",),
            (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
        )
        self.inference_prompt_tokens_total = self._register_counter(
            "aihost_inference_prompt_tokens_total",
            "Prompt tokens across completed inference requests. source=provider is the engine's own count "
            "(exact); source=estimated is the gateway's fallback when the engine reported no usage.",
            ("worker_id", "model", "source"),
        )
        self.inference_completion_tokens_total = self._register_counter(
            "aihost_inference_completion_tokens_total",
            "Completion tokens across completed inference requests, including tool-call arguments. "
            "source=provider is the engine's own count (exact); source=estimated is a fallback.",
            ("worker_id", "model", "source"),
        )
        self.worker_inflight = self._register_gauge(
            "aihost_worker_inflight",
            "Requests the gateway currently has outstanding on a worker. Above max_concurrency, the excess "
            "waits inside the engine.",
            ("worker_id",),
        )
        self.worker_max_concurrency = self._register_gauge(
            "aihost_worker_max_concurrency",
            "Concurrent requests a worker is configured to serve.",
            ("worker_id",),
        )
        # Engine-reported state, republished by the gateway (it holds the worker credentials). A series is
        # absent when the engine does not report it or the reading is stale - never a made-up zero.
        engine_labels = ("worker_id", "pool", "engine")
        self.engine_requests_running = self._register_gauge(
            "aihost_engine_requests_running", "Requests the engine is processing right now.", engine_labels)
        self.engine_requests_waiting = self._register_gauge(
            "aihost_engine_requests_waiting", "Requests deferred inside the engine, waiting for a free slot.", engine_labels)
        self.engine_kv_cache_usage_ratio = self._register_gauge(
            "aihost_engine_kv_cache_usage_ratio",
            "Fraction (0..1) of the engine's context/KV capacity held by active or retained sequences.", engine_labels)
        self.engine_prefix_cache_hit_ratio = self._register_gauge(
            "aihost_engine_prefix_cache_hit_ratio",
            "Lifetime fraction (0..1) of prompt tokens served from cache rather than recomputed.", engine_labels)
        self.engine_generation_tokens_in_flight = self._register_gauge(
            "aihost_engine_generation_tokens_in_flight", "Tokens decoded so far by requests still running.", engine_labels)
        self.engine_prompt_tokens_in_flight = self._register_gauge(
            "aihost_engine_prompt_tokens_in_flight", "Prompt tokens evaluated so far by requests still running.", engine_labels)
        self.engine_prompt_tokens_total = self._register_mirrored_counter(
            "aihost_engine_prompt_tokens_total", "Prompt tokens the engine evaluated (excludes cached), as the engine counts them.", engine_labels)
        self.engine_prompt_tokens_cached_total = self._register_mirrored_counter(
            "aihost_engine_prompt_tokens_cached_total", "Prompt tokens the engine reused from cache.", engine_labels)
        self.engine_generation_tokens_total = self._register_mirrored_counter(
            "aihost_engine_generation_tokens_total", "Tokens the engine generated, as the engine counts them.", engine_labels)
        self.engine_prompt_seconds_total = self._register_mirrored_counter(
            "aihost_engine_prompt_seconds_total", "Seconds the engine spent evaluating prompts.", engine_labels)
        self.engine_generation_seconds_total = self._register_mirrored_counter(
            "aihost_engine_generation_seconds_total", "Seconds the engine spent generating tokens.", engine_labels)
        self.inference_streaming_requests_total = self._register_counter(
            "aihost_inference_streaming_requests_total",
            "Total number of streaming inference requests by outcome.",
            ("worker_id", "outcome"),
        )

        # ---------------------------------------------------------------------
        # 3. Scheduler
        # ---------------------------------------------------------------------
        self.scheduler_queued_work = self._register_gauge(
            "aihost_scheduler_queued_work",
            "Current number of tasks waiting in scheduler queue.",
        )
        self.scheduler_active_work = self._register_gauge(
            "aihost_scheduler_active_work",
            "Current number of tasks actively executing in scheduler.",
        )
        self.scheduler_queue_wait_seconds = self._register_histogram(
            "aihost_scheduler_queue_wait_seconds",
            "Time work waited in the gateway scheduler's own queue, in seconds. Engine-side queueing is not "
            "included; see aihost_engine_requests_waiting and aihost_worker_inflight.",
            (),
            (0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 15.0, 30.0, 60.0),
        )
        self.scheduler_dispatch_decisions_total = self._register_counter(
            "aihost_scheduler_dispatch_decisions_total",
            "Total number of dispatch decisions made by the scheduler.",
            ("worker_id", "decision"),
        )
        self.route_decisions_total = self._register_counter(
            "aihost_route_decisions_total",
            "Routing decisions by matched rule and the pool that served the request.",
            ("rule", "pool"),
        )
        self.scheduler_worker_available = self._register_gauge(
            "aihost_scheduler_worker_available",
            "Current worker availability status (1 = available, 0 = unavailable).",
            ("worker_id",),
        )
        self.scheduler_dependency_blocked_work = self._register_gauge(
            "aihost_scheduler_dependency_blocked_work",
            "Current number of task nodes blocked by unmet dependencies.",
        )
        self.scheduler_admission_backpressure_total = self._register_counter(
            "aihost_scheduler_admission_backpressure_total",
            "Total number of admission rejections and backpressure events.",
            ("reason",),
        )

        # ---------------------------------------------------------------------
        # 4. Worker and provider health
        # ---------------------------------------------------------------------
        self.worker_health_status = self._register_gauge(
            "aihost_worker_health_status",
            "Last observed worker health status (1 = healthy, 0 = unhealthy).",
            ("worker_id",),
        )
        self.worker_last_check_timestamp_seconds = self._register_gauge(
            "aihost_worker_last_check_timestamp_seconds",
            "Unix timestamp of the last health check or observed activity for a worker.",
            ("worker_id",),
        )
        self.worker_check_duration_seconds = self._register_gauge(
            "aihost_worker_check_duration_seconds",
            "Duration in seconds of the last health check probe.",
            ("worker_id",),
        )
        self.provider_errors_total = self._register_counter(
            "aihost_provider_errors_total",
            "Total number of downstream provider errors and timeouts.",
            ("worker_id", "error_type"),
        )
        self.worker_quarantine_status = self._register_gauge(
            "aihost_worker_quarantine_status",
            "Worker circuit-breaker or quarantine status (0 = normal, 1 = quarantined).",
            ("worker_id",),
        )

        # ---------------------------------------------------------------------
        # 5. Authority and validation
        # ---------------------------------------------------------------------
        self.authority_validations_total = self._register_counter(
            "aihost_authority_validations_total",
            "Total number of external validation evaluations by outcome.",
            ("outcome",),
        )
        self.preflight_rejections_total = self._register_counter(
            "aihost_preflight_rejections_total",
            "Total number of fail-closed preflight rejections.",
            ("reason",),
        )
        self.evidence_verification_failures_total = self._register_counter(
            "aihost_evidence_verification_failures_total",
            "Total number of evidence store or receipt verification failures.",
        )
        self.authority_rejections_total = self._register_counter(
            "aihost_authority_rejections_total",
            "Total number of tool or action execution authority rejections.",
            ("reason",),
        )

    def _register_counter(self, name: str, help_text: str, label_names: tuple[str, ...] = ()) -> Counter:
        counter = Counter(name, help_text, label_names)
        self._metrics.append(counter)
        return counter

    def _register_gauge(self, name: str, help_text: str, label_names: tuple[str, ...] = ()) -> Gauge:
        gauge = Gauge(name, help_text, label_names)
        self._metrics.append(gauge)
        return gauge

    def _register_mirrored_counter(self, name: str, help_text: str, label_names: tuple[str, ...] = ()) -> MirroredCounter:
        counter = MirroredCounter(name, help_text, label_names)
        self._metrics.append(counter)
        return counter

    def _register_histogram(
        self,
        name: str,
        help_text: str,
        label_names: tuple[str, ...] = (),
        buckets: tuple[float, ...] | None = None,
    ) -> Histogram:
        hist = Histogram(name, help_text, label_names, buckets)
        self._metrics.append(hist)
        return hist

    def update_uptime(self) -> None:
        """Update gateway uptime gauge to current timestamp."""
        self.gateway_uptime_seconds.set(time.time() - self.start_time)

    def render_prometheus_text(self) -> str:
        """Render all registered metric families into Prometheus 0.0.4 text format."""
        self.update_uptime()
        lines: list[str] = []
        with self._lock:
            for metric in self._metrics:
                lines.extend(metric.collect())
        lines.append("")  # trailing newline required by Prometheus exposition format
        return "\n".join(lines)
