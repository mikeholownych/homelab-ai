"""Versioned client-facing telemetry interface and in-memory request correlation buffer.

Provides authenticated, read-only telemetry across appliance, worker, and request scopes.
Maintains strict client data isolation, bounded in-memory request history, explicit
measurement provenance, and engine-agnostic metric definitions.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from .clients import Client

API_VERSION = "2026-10-09"

SCOPES = ("appliance", "worker", "request", "all")

# Metadata catalogue defining every supported metric, unit, derivation method, and provenance
METRICS_CATALOGUE: list[dict[str, Any]] = [
    {
        "metric": "ttft_seconds",
        "description": "Time to first token in seconds.",
        "unit": "seconds",
        "scopes": ["request", "worker"],
        "type": "histogram_or_scalar",
        "methods": [
            {
                "name": "streaming_first_chunk",
                "provenance": "measured",
                "description": "Directly observed duration from request start to the first token delta chunk over SSE.",
            },
            {
                "name": "engine_reported_timings",
                "provenance": "engine_reported",
                "description": "Prefill prompt_ms reported by the inference engine in non-streaming response timings.",
            },
        ],
        "request_correlation": True,
        "freshness": "event_driven",
    },
    {
        "metric": "inter_token_latency_seconds",
        "description": "Inter-token latency (time per output token) in seconds.",
        "unit": "seconds",
        "scopes": ["request", "worker"],
        "type": "histogram_or_scalar",
        "methods": [
            {
                "name": "streaming_delta_intervals",
                "provenance": "measured",
                "description": "Consecutive token delta inter-arrival intervals measured during SSE streaming.",
            },
            {
                "name": "engine_reported_timings",
                "provenance": "engine_reported",
                "description": "Predicted per-token ms calculated from response timings (predicted_ms / predicted_n).",
            },
        ],
        "request_correlation": True,
        "freshness": "event_driven",
    },
    {
        "metric": "queue_wait_seconds",
        "description": "Duration spent waiting in the gateway scheduler queue prior to slot acquisition.",
        "unit": "seconds",
        "scopes": ["request", "worker"],
        "type": "histogram_or_scalar",
        "methods": [
            {
                "name": "gateway_scheduler_wait",
                "provenance": "measured",
                "description": "Monotonic duration between admission ticket enqueue and slot grant.",
            }
        ],
        "request_correlation": True,
        "freshness": "event_driven",
    },
    {
        "metric": "duration_seconds",
        "description": "Total dispatch wall time from scheduling to response completion.",
        "unit": "seconds",
        "scopes": ["request", "worker"],
        "type": "histogram_or_scalar",
        "methods": [
            {
                "name": "gateway_dispatch_duration",
                "provenance": "measured",
                "description": "Monotonic elapsed time measured by the gateway runtime.",
            }
        ],
        "request_correlation": True,
        "freshness": "event_driven",
    },
    {
        "metric": "prompt_tokens",
        "description": "Evaluated prompt tokens for a request or cumulative totals.",
        "unit": "tokens",
        "scopes": ["request", "worker"],
        "type": "counter_or_integer",
        "methods": [
            {
                "name": "provider_usage",
                "provenance": "engine_reported",
                "description": "Exact prompt token count reported in engine response usage.",
            },
            {
                "name": "gateway_estimate",
                "provenance": "estimated",
                "description": "Conservative preflight estimate fallback if provider omitted usage.",
            },
        ],
        "request_correlation": True,
        "freshness": "event_driven",
    },
    {
        "metric": "completion_tokens",
        "description": "Generated tokens across completion choices.",
        "unit": "tokens",
        "scopes": ["request", "worker"],
        "type": "counter_or_integer",
        "methods": [
            {
                "name": "provider_usage",
                "provenance": "engine_reported",
                "description": "Exact generated token count reported in engine response usage.",
            }
        ],
        "request_correlation": True,
        "freshness": "event_driven",
    },
    {
        "metric": "cached_prompt_tokens",
        "description": "Prompt tokens reused from engine KV/prefix cache.",
        "unit": "tokens",
        "scopes": ["request", "worker"],
        "type": "counter_or_integer",
        "methods": [
            {
                "name": "provider_cache_details",
                "provenance": "engine_reported",
                "description": "Cached tokens from prompt_tokens_details or engine prompt_tokens_cached_total.",
            }
        ],
        "request_correlation": True,
        "freshness": "event_driven / 2.0s",
    },
    {
        "metric": "kv_cache_usage_ratio",
        "description": "Fraction (0..1) of engine KV capacity held by active or retained sequences.",
        "unit": "ratio",
        "scopes": ["worker"],
        "type": "gauge",
        "methods": [
            {
                "name": "engine_slots_summary",
                "provenance": "engine_reported",
                "description": "llama.cpp /slots prompt and decoded tokens divided by allocated context capacity.",
            }
        ],
        "request_correlation": False,
        "freshness": "2.0s poll interval",
    },
    {
        "metric": "prefix_cache_hit_ratio",
        "description": "Lifetime fraction (0..1) of prompt tokens served from prefix cache rather than recomputed.",
        "unit": "ratio",
        "scopes": ["worker"],
        "type": "gauge",
        "methods": [
            {
                "name": "engine_cache_ratio",
                "provenance": "engine_reported",
                "description": "Cached prompt tokens divided by sum of cached and processed tokens.",
            }
        ],
        "request_correlation": False,
        "freshness": "2.0s poll interval",
    },
    {
        "metric": "requests_running",
        "description": "Inference requests currently executing inside the worker engine.",
        "unit": "count",
        "scopes": ["worker"],
        "type": "gauge",
        "methods": [
            {
                "name": "engine_slots",
                "provenance": "engine_reported",
                "description": "Number of active processing slots reported by the engine.",
            }
        ],
        "request_correlation": False,
        "freshness": "2.0s poll interval",
    },
    {
        "metric": "requests_waiting",
        "description": "Inference requests queued inside the worker engine awaiting an execution slot.",
        "unit": "count",
        "scopes": ["worker"],
        "type": "gauge",
        "methods": [
            {
                "name": "engine_deferred",
                "provenance": "engine_reported",
                "description": "Requests deferred inside the engine.",
            }
        ],
        "request_correlation": False,
        "freshness": "2.0s poll interval",
    },
    {
        "metric": "scheduler_queue_depth",
        "description": "Requests waiting in the gateway admission queue, broken down by pool.",
        "unit": "count",
        "scopes": ["appliance"],
        "type": "gauge",
        "methods": [
            {
                "name": "gateway_scheduler",
                "provenance": "measured",
                "description": "Tickets currently waiting for worker concurrency slot.",
            }
        ],
        "request_correlation": False,
        "freshness": "instantaneous",
    },
    {
        "metric": "worker_health_status",
        "description": "Worker probe health state (1 = healthy, 0 = unhealthy).",
        "unit": "boolean",
        "scopes": ["worker"],
        "type": "gauge",
        "methods": [
            {
                "name": "gateway_health_manager",
                "provenance": "measured",
                "description": "Active HTTP probe result to the worker endpoint.",
            }
        ],
        "request_correlation": False,
        "freshness": "10.0s probe interval",
    },
]

# Explicit declaration of capabilities that are unavailable or unsupported over the gateway API
UNAVAILABLE_CAPABILITIES: list[dict[str, str]] = [
    {
        "capability": "gpu_hardware_sensors_via_api",
        "status": "unsupported",
        "reason": "Host hardware sensor telemetry (VRAM bytes, GPU temperature, wattage) is queried on-host by vllm-top and is not exposed over the gateway proxy API.",
    },
    {
        "capability": "arbitrary_promql_expressions",
        "status": "unsupported",
        "reason": "Arbitrary metrics expressions are rejected; queries are strictly bounded to named parameters.",
    },
    {
        "capability": "cross_client_request_history",
        "status": "unsupported",
        "reason": "Requests from other clients are isolated by design and cannot be queried.",
    },
    {
        "capability": "raw_prompt_payload_storage",
        "status": "unsupported",
        "reason": "Raw prompts, completions, and headers are excluded from telemetry store for data privacy.",
    },
]


@dataclass
class RequestTelemetryRecord:
    request_id: str
    client_id: str
    worker_id: str
    pool: str
    model: str
    model_id: str
    artifact_digest: str
    stream: bool
    priority: str
    status: str  # completed, rejected, failed, cancelled, timed_out
    termination: str | None
    finish_reason: str | None
    prompt_tokens: int
    completion_tokens: int
    cached_prompt_tokens: int | None
    queue_duration_seconds: float | None
    ttft_seconds: float | None
    ttft_provenance: str | None  # "streaming_first_chunk" | "engine_reported_timings" | None
    inter_token_latency_seconds: float | None
    itl_provenance: str | None  # "streaming_delta_intervals" | "engine_reported_timings" | None
    duration_seconds: float
    timestamp: str  # ISO-8601 UTC
    error_message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if not self.error_message:
            data.pop("error_message", None)
        if not self.details:
            data.pop("details", None)
        return data


class RequestTelemetryBuffer:
    """Thread-safe bounded in-memory buffer of recent request-level telemetry records.

    Enforces strict max capacity (FIFO eviction) and client isolation.
    """

    def __init__(self, max_size: int = 10_000) -> None:
        self.max_size = max(1, max_size)
        self._records: OrderedDict[str, RequestTelemetryRecord] = OrderedDict()
        self._lock = threading.Lock()

    def record(self, entry: RequestTelemetryRecord) -> None:
        with self._lock:
            self._records[entry.request_id] = entry
            while len(self._records) > self.max_size:
                self._records.popitem(last=False)

    def get_by_id(self, request_id: str, client_id: str | None = None) -> RequestTelemetryRecord | None:
        with self._lock:
            entry = self._records.get(request_id)
            if entry is None:
                return None
            if client_id is not None and entry.client_id != client_id:
                # Disallow cross-client discovery: do not reveal that another client's request exists
                return None
            return entry

    def query(
        self,
        client_id: str | None = None,
        *,
        worker_id: str | None = None,
        model: str | None = None,
        limit: int = 10,
    ) -> list[RequestTelemetryRecord]:
        with self._lock:
            limit = max(1, min(limit, 100))
            results: list[RequestTelemetryRecord] = []
            for entry in reversed(self._records.values()):
                if client_id is not None and entry.client_id != client_id:
                    continue
                if worker_id is not None and entry.worker_id != worker_id:
                    continue
                if model is not None and entry.model != model and entry.model_id != model:
                    continue
                results.append(entry)
                if len(results) >= limit:
                    break
            return results

    def count(self, client_id: str | None = None) -> int:
        with self._lock:
            if client_id is None:
                return len(self._records)
            return sum(1 for e in self._records.values() if e.client_id == client_id)

    def clear(self) -> None:
        with self._lock:
            self._records.clear()


class TelemetryService:
    """Aggregates appliance, worker, and request telemetry for client consumption."""

    def __init__(self, runtime: Any, buffer: RequestTelemetryBuffer) -> None:
        self.runtime = runtime
        self.buffer = buffer

    def capabilities(self, client: Client) -> dict[str, Any]:
        """Generate capability discovery payload according to the API contract."""
        registered_workers = []
        for w in self.runtime.registry.snapshot():
            registered_workers.append({
                "worker_id": w["worker_id"],
                "pool": w.get("pool", "lead"),
                "role": w.get("role", "production"),
                "model_id": w["model_id"],
                "public_model_id": w["public_model_id"],
                "engine": w.get("engine", "unknown"),
                "context_limit": w["context_limit"],
                "max_concurrency": w["max_concurrency"],
            })

        can_view_aggregates = bool(client.scopes & {"telemetry", "monitoring", "admin"})

        return {
            "object": "telemetry_capabilities",
            "api_version": API_VERSION,
            "version": API_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "client": {
                "client_id": client.client_id,
                "scopes": sorted(client.scopes),
                "can_view_aggregate_telemetry": can_view_aggregates,
            },
            "scopes": list(SCOPES),
            "scopes_supported": list(SCOPES),
            "dimensions": ["worker_id", "model", "pool", "request_id"],
            "query_parameters": {
                "scope": "Query scope (appliance, worker, request, all).",
                "request_id": "Exact request correlation ID for request-level telemetry.",
                "worker_id": "Filter observations by worker identity.",
                "model": "Filter observations by model identifier.",
                "metric": "Filter response to a specific metric name.",
                "limit": "Max requests returned (1..100, default 10).",
            },
            "retrieval_limits": {
                "max_limit": 100,
                "default_limit": 10,
                "max_buffer_size": self.buffer.max_size,
            },
            "request_correlation": {
                "available": True,
                "mechanism": "X-Request-ID header / request_id query parameter",
                "isolation": "strict_client_isolation",
            },
            "supported_metrics": METRICS_CATALOGUE,
            "metrics": METRICS_CATALOGUE,
            "unavailable_capabilities": UNAVAILABLE_CAPABILITIES,
            "active_workers": registered_workers,
        }

    def inference_telemetry(
        self,
        client: Client,
        *,
        scope: str | None = None,
        request_id: str | None = None,
        worker_id: str | None = None,
        model: str | None = None,
        metric: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Retrieve bounded inference observations with scope and permission enforcement."""
        can_view_aggregates = bool(client.scopes & {"telemetry", "monitoring", "admin"})

        if scope is not None and scope not in SCOPES:
            raise ValueError(f"invalid scope {scope!r}; must be one of {list(SCOPES)}")

        if metric is not None:
            known_metrics = {m["metric"] for m in METRICS_CATALOGUE}
            if metric not in known_metrics:
                raise ValueError(f"unsupported metric {metric!r}; supported: {sorted(known_metrics)}")

        limit = max(1, min(limit, 100))

        # Determine effective scope
        effective_scope = scope
        if effective_scope is None:
            if request_id is not None:
                effective_scope = "request"
            elif worker_id is not None:
                effective_scope = "worker"
            else:
                effective_scope = "all" if can_view_aggregates else "request"

        # Permission check: aggregate scopes and request history require telemetry, monitoring, or admin
        if not can_view_aggregates:
            if effective_scope in ("appliance", "worker", "all"):
                raise PermissionError("telemetry, monitoring or admin scope required for aggregate worker/appliance telemetry")
            if effective_scope == "request" and request_id is None:
                raise PermissionError("telemetry scope required to query request history without request_id")

        data: dict[str, Any] = {}

        # -------------------------------------------------------------
        # 1. Request scope
        # -------------------------------------------------------------
        if effective_scope in ("request", "all") or request_id is not None:
            if request_id is not None:
                record = self.buffer.get_by_id(request_id, client_id=client.client_id)
                if record is None:
                    raise KeyError(f"request_id {request_id!r} not found")
                data["requests"] = [self._filter_record_metrics(record.to_dict(), metric)]
            else:
                records = self.buffer.query(client.client_id, worker_id=worker_id, model=model, limit=limit)
                data["requests"] = [self._filter_record_metrics(r.to_dict(), metric) for r in records]

        # -------------------------------------------------------------
        # 2. Worker scope
        # -------------------------------------------------------------
        if can_view_aggregates and effective_scope in ("worker", "all"):
            workers_out = []
            snapshot = self.runtime.registry.snapshot()
            if worker_id:
                snapshot = [w for w in snapshot if w["worker_id"] == worker_id]
                if not snapshot:
                    raise KeyError(f"worker_id {worker_id!r} not found")

            for w in snapshot:
                wid = w["worker_id"]
                w_telemetry = self._build_worker_telemetry(w, metric)
                if w_telemetry:
                    workers_out.append(w_telemetry)
            data["workers"] = workers_out

        # -------------------------------------------------------------
        # 3. Appliance scope
        # -------------------------------------------------------------
        if can_view_aggregates and effective_scope in ("appliance", "all"):
            data["appliance"] = self._build_appliance_telemetry(metric)

        return {
            "object": "telemetry_inference",
            "api_version": API_VERSION,
            "version": API_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "client_id": client.client_id,
            "scope": effective_scope,
            "requests": data.get("requests", []),
            "workers": data.get("workers", []),
            "appliance": data.get("appliance"),
            "data": data,
        }

    def _filter_record_metrics(self, record_dict: dict[str, Any], metric: str | None) -> dict[str, Any]:
        if not metric:
            return record_dict
        # Retain essential identity fields plus the requested metric
        base = {
            "request_id": record_dict["request_id"],
            "client_id": record_dict["client_id"],
            "worker_id": record_dict["worker_id"],
            "model": record_dict["model"],
            "timestamp": record_dict["timestamp"],
        }
        if metric in record_dict:
            base[metric] = record_dict[metric]
            # Attach provenance if applicable
            prov_key = f"{metric}_provenance"
            if prov_key in record_dict:
                base[prov_key] = record_dict[prov_key]
            elif metric in ("ttft", "ttft_seconds") and "ttft_provenance" in record_dict:
                base["ttft_provenance"] = record_dict["ttft_provenance"]
            elif metric in ("inter_token_latency_seconds", "itl") and "itl_provenance" in record_dict:
                base["itl_provenance"] = record_dict["itl_provenance"]
        return base

    def _build_worker_telemetry(self, worker_meta: dict[str, Any], metric_filter: str | None) -> dict[str, Any]:
        wid = worker_meta["worker_id"]
        pool = worker_meta.get("pool", "lead")
        public_model = worker_meta.get("public_model_id", "engineering/lead")

        # Basic identity
        out: dict[str, Any] = {
            "worker_id": wid,
            "pool": pool,
            "role": worker_meta.get("role", "production"),
            "model_id": worker_meta["model_id"],
            "public_model_id": public_model,
            "artifact_digest": worker_meta.get("artifact_digest", ""),
            "engine": worker_meta.get("engine", "unknown"),
            "gpu_assignment": list(worker_meta.get("gpu_assignment", ())),
            "status": worker_meta.get("status", "unknown"),
            "healthy": bool(worker_meta.get("healthy", False)),
            "available": bool(self.runtime.metrics.scheduler_worker_available.get(worker_id=wid) == 1.0),
            "context_limit": worker_meta.get("context_limit"),
            "max_concurrency": worker_meta.get("max_concurrency"),
            "inflight_requests": int(self.runtime.metrics.worker_inflight.get(worker_id=wid)),
        }

        # Cache metrics
        engine_stats = None
        if hasattr(self.runtime, "health") and hasattr(self.runtime.health, "_engine_stats"):
            engine_stats = self.runtime.health._engine_stats.get(wid)

        kv_cache = self.runtime.metrics.engine_kv_cache_usage_ratio.get(worker_id=wid, pool=pool, engine=worker_meta.get("engine", "unknown"))
        prefix_cache = self.runtime.metrics.engine_prefix_cache_hit_ratio.get(worker_id=wid, pool=pool, engine=worker_meta.get("engine", "unknown"))
        cached_tokens = self.runtime.metrics.engine_prompt_tokens_cached_total.get(worker_id=wid, pool=pool, engine=worker_meta.get("engine", "unknown"))

        cache_dict = {
            "kv_cache_usage_ratio": round(kv_cache, 4) if kv_cache else None,
            "prefix_cache_hit_ratio": round(prefix_cache, 4) if prefix_cache else None,
            "prompt_tokens_cached_total": int(cached_tokens) if cached_tokens else None,
        }

        # Counters
        counters_dict = {
            "requests_running": int(self.runtime.metrics.engine_requests_running.get(worker_id=wid, pool=pool, engine=worker_meta.get("engine", "unknown"))),
            "requests_waiting": int(self.runtime.metrics.engine_requests_waiting.get(worker_id=wid, pool=pool, engine=worker_meta.get("engine", "unknown"))),
            "prompt_tokens_total": int(self.runtime.metrics.engine_prompt_tokens_total.get(worker_id=wid, pool=pool, engine=worker_meta.get("engine", "unknown"))),
            "generation_tokens_total": int(self.runtime.metrics.engine_generation_tokens_total.get(worker_id=wid, pool=pool, engine=worker_meta.get("engine", "unknown"))),
        }

        # Latencies
        ttft_dist = self.runtime.metrics.inference_ttft_seconds.get_distribution(worker_id=wid)
        itl_dist = self.runtime.metrics.inference_inter_token_latency_seconds.get_distribution(worker_id=wid)
        queue_dist = self.runtime.metrics.scheduler_queue_wait_seconds.get_distribution(worker_id=wid)
        dur_dist = self.runtime.metrics.inference_duration_seconds.get_distribution(worker_id=wid, model=public_model, pool=pool)

        latencies_dict = {
            "ttft_seconds": ttft_dist,
            "inter_token_latency_seconds": itl_dist,
            "queue_wait_seconds": queue_dist,
            "duration_seconds": dur_dist,
        }

        # Freshness
        observed_at = None
        age_seconds = None
        stale = False
        if engine_stats and "observed_at" in engine_stats:
            observed_at = datetime.fromtimestamp(engine_stats["observed_at"], timezone.utc).isoformat()
            age_seconds = round(time.time() - engine_stats["observed_at"], 2)
            stale = age_seconds > 30.0

        freshness_dict = {
            "observed_at": observed_at,
            "age_seconds": age_seconds,
            "stale": stale,
        }

        if metric_filter:
            if metric_filter in cache_dict:
                return {**out, metric_filter: cache_dict[metric_filter], "freshness": freshness_dict}
            if metric_filter in counters_dict:
                return {**out, metric_filter: counters_dict[metric_filter], "freshness": freshness_dict}
            if metric_filter in latencies_dict:
                return {**out, metric_filter: latencies_dict[metric_filter], "freshness": freshness_dict}
            return out

        out["cache"] = cache_dict
        out["engine_counters"] = counters_dict
        out["latencies"] = latencies_dict
        out["latency_distributions"] = latencies_dict
        out["freshness"] = freshness_dict
        return out

    def _build_appliance_telemetry(self, metric_filter: str | None) -> dict[str, Any]:
        now = time.time()
        start = getattr(self.runtime.metrics, "start_time", now)
        uptime = round(now - start, 2)

        active = int(self.runtime.metrics.scheduler_active_work.get())
        queued = int(self.runtime.metrics.scheduler_queued_work.get())
        blocked = int(self.runtime.metrics.scheduler_dependency_blocked_work.get())

        workers = self.runtime.registry.snapshot()
        total_workers = len(workers)
        healthy_workers = sum(1 for w in workers if w.get("healthy"))
        available_workers = sum(1 for w in workers if self.runtime.metrics.scheduler_worker_available.get(worker_id=w["worker_id"]) == 1.0)

        # Queue depth by pool
        pools = {w.get("pool", "lead") for w in workers}
        queue_by_pool = {p: int(self.runtime.metrics.scheduler_queue_depth.get(pool=p)) for p in pools}

        # Request completions
        received = int(self.runtime.metrics.inference_requests_total.get(status="received"))
        rejected = int(self.runtime.metrics.inference_requests_total.get(status="rejected"))

        appliance_data = {
            "gateway": {
                "status": "healthy" if not self.runtime.shutting_down.is_set() else "draining",
                "uptime_seconds": uptime,
                "start_time_seconds": start,
                "version": API_VERSION,
            },
            "workers_summary": {
                "total": total_workers,
                "healthy": healthy_workers,
                "available": available_workers,
            },
            "admission": {
                "queued_work": queued,
                "active_work": active,
                "dependency_blocked_work": blocked,
                "queue_depth_by_pool": queue_by_pool,
            },
            "totals": {
                "requests_received": received,
                "requests_rejected": rejected,
            },
        }

        if metric_filter:
            if metric_filter == "scheduler_queue_depth":
                return {"admission": {"queue_depth_by_pool": queue_by_pool}}
            return appliance_data

        return appliance_data
