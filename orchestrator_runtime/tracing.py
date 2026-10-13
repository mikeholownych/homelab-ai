"""W3C Trace Context level 1 distributed tracing integration.

Implements the W3C Recommendation for Trace Context propagation:
- Parses incoming `traceparent` and `tracestate` headers.
- Generates compliant 128-bit trace IDs and 64-bit span IDs when not present.
- Creates hierarchical child spans for downstream worker and provider dispatch.
- Binds trace IDs and span IDs to audit evidence and upstream request headers.
"""
from __future__ import annotations

import json
import os
import queue
import re
import threading
import time
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Mapping

_TRACEPARENT_PATTERN = re.compile(r"^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")


@dataclass
class Span:
    """An individual distributed tracing span compliant with OpenTelemetry schema."""
    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    start_time_ns: int = field(default_factory=time.time_ns)
    end_time_ns: int = 0
    attributes: dict[str, Any] = field(default_factory=dict)
    status_code: int = 1  # 1 = OK, 2 = ERROR, 0 = UNSET
    status_message: str = ""

    def end(self, end_time_ns: int | None = None, status_code: int | None = None, status_message: str = "") -> None:
        self.end_time_ns = end_time_ns or time.time_ns()
        if status_code is not None:
            self.status_code = status_code
        if status_message:
            self.status_message = status_message

    def to_otlp_json(self) -> dict[str, Any]:
        """Convert to standard OpenTelemetry protobuf-equivalent JSON span schema."""
        otlp_attrs = []
        for k, v in self.attributes.items():
            if isinstance(v, bool):
                val_dict = {"boolValue": v}
            elif isinstance(v, int):
                val_dict = {"intValue": str(v)}
            elif isinstance(v, float):
                val_dict = {"doubleValue": v}
            else:
                val_dict = {"stringValue": str(v)}
            otlp_attrs.append({"key": k, "value": val_dict})

        res: dict[str, Any] = {
            "traceId": self.trace_id,
            "spanId": self.span_id,
            "name": self.name,
            "kind": 1,  # SPAN_KIND_INTERNAL
            "startTimeUnixNano": str(self.start_time_ns),
            "endTimeUnixNano": str(self.end_time_ns or time.time_ns()),
            "attributes": otlp_attrs,
            "status": {"code": self.status_code},
        }
        if self.parent_span_id:
            res["parentSpanId"] = self.parent_span_id
        if self.status_message:
            res["status"]["message"] = self.status_message
        return res


@dataclass(frozen=True)
class TraceContext:
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    sampled: bool = True
    tracestate: str = ""

    def __post_init__(self) -> None:
        if len(self.trace_id) != 32 or self.trace_id == "0" * 32:
            raise ValueError(f"invalid trace_id: {self.trace_id!r}")
        if len(self.span_id) != 16 or self.span_id == "0" * 16:
            raise ValueError(f"invalid span_id: {self.span_id!r}")

    @classmethod
    def new_root(cls, *, sampled: bool = True) -> "TraceContext":
        """Generate a fresh root trace context."""
        trace_id = os.urandom(16).hex()
        span_id = os.urandom(8).hex()
        return cls(trace_id=trace_id, span_id=span_id, sampled=sampled)

    @classmethod
    def from_headers(cls, headers: Mapping[str, str], *, sampled_default: bool = True) -> "TraceContext":
        """Parse W3C traceparent and tracestate from HTTP headers (case-insensitive keys)."""
        traceparent: str | None = None
        tracestate: str = ""
        for k, v in headers.items():
            k_lower = k.lower()
            if k_lower == "traceparent":
                traceparent = v.strip()
            elif k_lower == "tracestate":
                tracestate = v.strip()

        if not traceparent:
            return cls.new_root(sampled=sampled_default)

        match = _TRACEPARENT_PATTERN.match(traceparent)
        if not match:
            return cls.new_root(sampled=sampled_default)

        version, trace_id, parent_id, flags_hex = match.groups()
        # W3C forbids all-zero IDs
        if trace_id == "0" * 32 or parent_id == "0" * 16:
            return cls.new_root(sampled=sampled_default)

        flags = int(flags_hex, 16)
        sampled = bool(flags & 0x01)

        # Gateway creates a new server span for this hop
        server_span_id = os.urandom(8).hex()
        return cls(
            trace_id=trace_id,
            span_id=server_span_id,
            parent_span_id=parent_id,
            sampled=sampled,
            tracestate=tracestate,
        )

    def child_span(self) -> "TraceContext":
        """Create a child span context for an outgoing request (e.g. to a worker)."""
        child_span_id = os.urandom(8).hex()
        return TraceContext(
            trace_id=self.trace_id,
            span_id=child_span_id,
            parent_span_id=self.span_id,
            sampled=self.sampled,
            tracestate=self.tracestate,
        )

    def to_headers(self) -> dict[str, str]:
        """Serialize into W3C traceparent and tracestate headers."""
        flags = "01" if self.sampled else "00"
        headers = {"traceparent": f"00-{self.trace_id}-{self.span_id}-{flags}"}
        if self.tracestate:
            headers["tracestate"] = self.tracestate
        return headers


class OTLPTraceExporter:
    """Asynchronous background OpenTelemetry OTLP/HTTP JSON trace exporter.

    Buffers spans in-memory and batch exports them to an OTLP collector endpoint (Grafana Tempo,
    OpenTelemetry Collector, Jaeger) via standard HTTP POST /v1/traces.
    """

    def __init__(
        self,
        endpoint: str | None = None,
        *,
        service_name: str = "aihost-orchestrator",
        service_version: str = "2.0",
        batch_size: int = 64,
        batch_timeout_seconds: float = 1.0,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        raw_endpoint = endpoint or os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        if raw_endpoint and not raw_endpoint.endswith("/v1/traces"):
            raw_endpoint = f"{raw_endpoint.rstrip('/')}/v1/traces"
        self.endpoint = raw_endpoint
        self.service_name = service_name
        self.service_version = service_version
        self.batch_size = max(1, batch_size)
        self.batch_timeout_seconds = max(0.05, batch_timeout_seconds)
        self.headers = dict(headers or {})
        self._queue: queue.Queue[Span] = queue.Queue(maxsize=10000)
        self._exported_spans: list[Span] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        if self.endpoint:
            self._start()

    def _start(self) -> None:
        self._thread = threading.Thread(target=self._worker, daemon=True, name="otlp-trace-exporter")
        self._thread.start()

    def record_span(self, span: Span) -> None:
        """Enqueue span for background export."""
        with self._lock:
            self._exported_spans.append(span)
        if self.endpoint and not self._stop_event.is_set():
            try:
                self._queue.put_nowait(span)
            except queue.Full:
                pass

    def start_span(
        self,
        name: str,
        context: TraceContext | None = None,
        *,
        attributes: dict[str, Any] | None = None,
    ) -> tuple[Span, TraceContext]:
        """Create and start a new Span, returning both the Span and its child TraceContext."""
        start_ns = time.time_ns()
        if context is None:
            child_ctx = TraceContext.new_root()
        else:
            child_ctx = context.child_span()
        span = Span(
            name=name,
            trace_id=child_ctx.trace_id,
            span_id=child_ctx.span_id,
            parent_span_id=child_ctx.parent_span_id,
            start_time_ns=start_ns,
            attributes=dict(attributes or {}),
        )
        return span, child_ctx

    def end_span(
        self,
        span: Span,
        *,
        attributes: dict[str, Any] | None = None,
        status_code: int = 1,
        status_message: str = "",
    ) -> None:
        """End and record a span."""
        if attributes:
            span.attributes.update(attributes)
        span.end(status_code=status_code, status_message=status_message)
        self.record_span(span)

    @contextmanager
    def span(self, name: str, context: TraceContext | None = None, attributes: dict[str, Any] | None = None):
        """Context manager for tracing an operation."""
        span_obj, child_ctx = self.start_span(name, context, attributes=attributes)
        try:
            yield span_obj, child_ctx
        except Exception as ex:
            self.end_span(span_obj, status_code=2, status_message=str(ex))
            raise
        else:
            self.end_span(span_obj, status_code=1)

    def _build_payload(self, spans: list[Span]) -> dict[str, Any]:
        return {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": self.service_name}},
                            {"key": "service.version", "value": {"stringValue": self.service_version}},
                        ]
                    },
                    "scopeSpans": [
                        {
                            "scope": {
                                "name": "aihost.orchestrator",
                                "version": self.service_version,
                            },
                            "spans": [s.to_otlp_json() for s in spans],
                        }
                    ],
                }
            ]
        }

    def _export_batch(self, batch: list[Span]) -> None:
        if not self.endpoint or not batch:
            return
        payload = self._build_payload(batch)
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            **self.headers,
        }
        req = urllib.request.Request(self.endpoint, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                pass
        except Exception:
            # Network or collector failure is non-fatal; fail closed with resilience
            pass

    def _worker(self) -> None:
        batch: list[Span] = []
        last_flush = time.monotonic()
        while not self._stop_event.is_set():
            try:
                span = self._queue.get(timeout=0.1)
                batch.append(span)
            except queue.Empty:
                pass

            now = time.monotonic()
            if len(batch) >= self.batch_size or (batch and now - last_flush >= self.batch_timeout_seconds):
                self._export_batch(batch)
                batch = []
                last_flush = now

        # Drain remaining on exit
        while not self._queue.empty():
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if batch:
            self._export_batch(batch)

    def flush(self) -> None:
        """Drain queue and export immediately."""
        batch: list[Span] = []
        while not self._queue.empty():
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break
        if batch:
            self._export_batch(batch)

    def shutdown(self) -> None:
        """Stop exporter thread cleanly."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    @property
    def exported_spans(self) -> list[Span]:
        with self._lock:
            return list(self._exported_spans)
