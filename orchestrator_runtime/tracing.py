"""W3C Trace Context level 1 distributed tracing integration.

Implements the W3C Recommendation for Trace Context propagation:
- Parses incoming `traceparent` and `tracestate` headers.
- Generates compliant 128-bit trace IDs and 64-bit span IDs when not present.
- Creates hierarchical child spans for downstream worker and provider dispatch.
- Binds trace IDs and span IDs to audit evidence and upstream request headers.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Mapping

_TRACEPARENT_PATTERN = re.compile(r"^([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")


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
