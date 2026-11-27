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
from .nvme_moe import (
    ExpertCache,
    GpuDeviceInfo,
    HardwareSnapshot,
    HostMemoryArbiter,
    MoEModelIndex,
    NVMeMoEStreamEngine,
    PlacementPlan,
    SecurityBindError,
    index_gguf_model,
    plan_model_placement,
    probe_nvme_random_read,
    validate_loopback_bind,
)
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
    "ExpertCache",
    "Gauge",
    "GpuDeviceInfo",
    "GraphScheduler",
    "HardwareSnapshot",
    "HealthManager",
    "Histogram",
    "HostMemoryArbiter",
    "InMemoryAdapter",
    "MetricsRegistry",
    "MoEModelIndex",
    "NVMeMoEStreamEngine",
    "OpenAIProviderAdapter",
    "OrchestratorRuntime",
    "PlacementPlan",
    "ProviderError",
    "RequestTelemetryBuffer",
    "RequestTelemetryRecord",
    "SecurityBindError",
    "TaskGraph",
    "TelemetryService",
    "WorkerHealthState",
    "WorkerRecord",
    "index_gguf_model",
    "plan_model_placement",
    "probe_nvme_random_read",
    "validate_loopback_bind",
]
