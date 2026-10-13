"""Fail-closed runtime primitives for cooperative engineering inference."""

from .admission import AdmissionCancelled, AdmissionController, AdmissionRejected, PoolUnavailable
from .capabilities import Capability
from .capacity import CapacityState, CapacityTracker
from .circuit_breaker import CircuitBreaker, CircuitBreakerRegistry, CircuitState
from .clients import Client, ClientRegistry, QuotaExceeded
from .engines import EngineObservation, LlamaCppAdapter, VllmAdapter
from .evidence import EvidenceStore
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
from .smart_router import ComplexityReport, CostModel, LatencyTracker, PromptComplexityAnalyzer
from .telemetry import RequestTelemetryBuffer, RequestTelemetryRecord, TelemetryService

__all__ = [
    "AdmissionCancelled",
    "AdmissionController",
    "AdmissionRejected",
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
    "LatencyTracker",
    "LlamaCppAdapter",
    "PoolUnavailable",
    "PromptComplexityAnalyzer",
    "QuotaExceeded",
    "RequestCancelled",
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
