"""Fail-closed runtime primitives for cooperative engineering inference."""

from .admission import AdmissionCancelled, AdmissionController, AdmissionRejected, PoolUnavailable
from .capabilities import Capability
from .capacity import CapacityState, CapacityTracker
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

__all__ = [
    "AdmissionCancelled",
    "AdmissionController",
    "AdmissionRejected",
    "Capability",
    "CapacityState",
    "CapacityTracker",
    "Client",
    "ClientRegistry",
    "EngineObservation",
    "LlamaCppAdapter",
    "PoolUnavailable",
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
    "TaskGraph",
    "WorkerHealthState",
    "WorkerRecord",
]
