"""Fail-closed runtime primitives for cooperative engineering inference."""

from .admission import AdmissionCancelled, AdmissionController, AdmissionRejected, PoolUnavailable
from .cache import CacheEntry, ResponseCache
from .capabilities import Capability
from .capacity import CapacityState, CapacityTracker
from .circuit_breaker import CircuitBreaker, CircuitBreakerRegistry, CircuitState
from .clients import Client, ClientRegistry, QuotaExceeded
from .engines import EngineObservation, LlamaCppAdapter, VllmAdapter
from .evidence import EvidenceStore, SyslogEvidenceStreamer
from .guardrails import GuardrailResult, GuardrailScanner, GuardrailViolation
from .health import HealthManager, WorkerHealthState
from .metrics import Counter, Gauge, Histogram, MetricsRegistry
from .routing import RouteConfigError, RouteDecision, Router, RouteRule
from .runtime import (
    CapabilityRegistry,
    GraphScheduler,
    InMemoryAdapter,
    OpenAIProviderAdapter,
    OrchestratorRuntime,
    ProviderError,
    RequestCancelled,
    TaskGraph,
    WorkerRecord,
)
from .smart_router import ComplexityReport, CostModel, EscalationPolicy, LatencyTracker, PromptComplexityAnalyzer
from .telemetry import RequestTelemetryBuffer, RequestTelemetryRecord, TelemetryService
from .tracing import OTLPTraceExporter, Span, TraceContext

__all__ = [
    "OTLPTraceExporter",
    "Span",
    "AdmissionCancelled",
    "AdmissionController",
    "AdmissionRejected",
    "CacheEntry",
    "Capability",
    "CapacityState",
    "CapacityTracker",
    "CircuitBreaker",
    "CircuitBreakerRegistry",
    "CircuitState",
    "Client",
    "ClientRegistry",
    "ComplexityReport",
    "CostModel",
    "EngineObservation",
    "EscalationPolicy",
    "GuardrailResult",
    "GuardrailScanner",
    "GuardrailViolation",
    "LatencyTracker",
    "LlamaCppAdapter",
    "PoolUnavailable",
    "PromptComplexityAnalyzer",
    "QuotaExceeded",
    "RequestCancelled",
    "ResponseCache",
    "SyslogEvidenceStreamer",
    "TraceContext",
    "VllmAdapter",
    "RouteConfigError",
    "RouteDecision",
    "RouteRule",
    "Router",
    "CapabilityRegistry",
    "Counter",
    "EvidenceStore",
    "Gauge",
    "GraphScheduler",
    "HealthManager",
    "Histogram",
    "InMemoryAdapter",
    "MetricsRegistry",
    "OpenAIProviderAdapter",
    "OrchestratorRuntime",
    "ProviderError",
    "RequestTelemetryBuffer",
    "RequestTelemetryRecord",
    "TaskGraph",
    "TelemetryService",
    "WorkerHealthState",
    "WorkerRecord",
]
