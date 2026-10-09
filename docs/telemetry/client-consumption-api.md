# Client Telemetry Consumption API Specification

## 1. Overview and Scope

The Client Telemetry API provides secure, versioned, read-only visibility into operational measurements from the T5820 inference appliance (`ai-5820-01`). It is implemented directly inside the authenticated orchestrator gateway (`orchestrator_gateway` / `orchestrator_runtime`) to expose live execution metrics—including Time to First Token (TTFT), Inter-Token Latency (ITL), queue wait times, token counts, and worker cache performance—to authorized client applications (such as Nexus context managers or monitoring daemons).

### Core Principles
- **Engine-Agnostic Contract:** The API contract uses normalized, standardized metric definitions that apply consistently across worker backends (`llama.cpp`, `vLLM`, or custom engines).
- **Read-Only Non-Disruptive Access:** Telemetry queries cannot mutate appliance state, alter scheduling priorities, or degrade ongoing model inferences.
- **Strict Data Isolation:** Request-level telemetry is strictly isolated by authenticated client ID. Requests executed by one client cannot be discovered, enumerated, or viewed by another client.
- **Zero Content Leakage:** Telemetry records store strictly operational execution metadata (timings, counts, statuses). Raw prompts, completions, system messages, and credentials are never stored in the telemetry ring buffer.
- **Explicit Provenance:** All latency measurements explicitly declare their measurement origin and derivation method (e.g., directly observed streaming chunks vs. engine-reported post-inference timings).

---

## 2. API Contract & Versioning

- **API Contract Version:** `2026-10-09`
- **Transport:** HTTPS (TLS 1.3)
- **Base Endpoints:**
  - `GET /v1/telemetry/capabilities`
  - `GET /v1/telemetry/inference`

All responses include the `api_version` field to ensure consumers can verify backwards compatibility.

---

## 3. Authentication & Authorization

All requests to `/v1/telemetry/*` require an HTTP `Authorization` header containing a valid Bearer token configured in the orchestrator gateway client registry:

```http
Authorization: Bearer <CLIENT_TOKEN>
```

### Scope Hierarchy
Client tokens are assigned granular scopes in the appliance configuration:

| Scope | Telemetry Permissions |
|---|---|
| `workload` | Permitted to discover capabilities (`/v1/telemetry/capabilities`) and query their **own** request telemetry by exact `request_id`. Denied access to aggregate worker or appliance telemetry (HTTP 403). |
| `telemetry` | Full telemetry access: capabilities, aggregate appliance telemetry, worker cache and latency distributions, and query/filter own request history. |
| `monitoring` | Equivalent to `telemetry` for monitoring agents; access to appliance and worker aggregate telemetry. |
| `admin` | Full access across all scopes and administration operations. |

---

## 4. Endpoint Specifications

### 4.1 Capability Discovery: `GET /v1/telemetry/capabilities`

Allows independent clients to programmatically discover supported metrics, query dimensions, units, derivation methods, buffer limits, and explicitly declared unavailable features.

#### Query Parameters
None.

#### Response Schema (HTTP 200 OK)
```json
{
  "object": "telemetry_capabilities",
  "api_version": "2026-10-09",
  "version": "2026-10-09",
  "timestamp": "2026-10-09T15:20:00.000000+00:00",
  "client": {
    "client_id": "nexus",
    "scopes": ["telemetry", "workload"],
    "can_view_aggregate_telemetry": true
  },
  "scopes": ["appliance", "worker", "request", "all"],
  "scopes_supported": ["appliance", "worker", "request", "all"],
  "dimensions": ["worker_id", "model", "pool", "request_id"],
  "retrieval_limits": {
    "max_limit": 100,
    "default_limit": 10,
    "max_buffer_size": 10000
  },
  "request_correlation": {
    "available": true,
    "mechanism": "X-Request-ID header / request_id query parameter",
    "isolation": "strict_client_isolation"
  },
  "supported_metrics": [
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
          "description": "Directly observed duration from request start to the first token delta chunk over SSE."
        },
        {
          "name": "engine_reported_timings",
          "provenance": "engine_reported",
          "description": "Prefill prompt_ms reported by the inference engine in non-streaming response timings."
        }
      ],
      "request_correlation": true,
      "freshness": "event_driven"
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
          "description": "Consecutive token delta inter-arrival intervals measured during SSE streaming."
        },
        {
          "name": "engine_reported_timings",
          "provenance": "engine_reported",
          "description": "Predicted per-token ms calculated from response timings (predicted_ms / predicted_n)."
        }
      ],
      "request_correlation": true,
      "freshness": "event_driven"
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
          "description": "Monotonic duration between admission ticket enqueue and slot grant."
        }
      ],
      "request_correlation": true,
      "freshness": "event_driven"
    },
    {
      "metric": "prompt_tokens",
      "description": "Evaluated prompt tokens for a request or cumulative totals.",
      "unit": "tokens",
      "scopes": ["request", "worker"],
      "type": "counter_or_integer"
    },
    {
      "metric": "completion_tokens",
      "description": "Generated completion tokens for a request or cumulative totals.",
      "unit": "tokens",
      "scopes": ["request", "worker"],
      "type": "counter_or_integer"
    },
    {
      "metric": "kv_cache_usage_ratio",
      "description": "Fraction of engine KV cache memory currently occupied (0.0 to 1.0).",
      "unit": "ratio",
      "scopes": ["worker"],
      "type": "gauge"
    },
    {
      "metric": "prefix_cache_hit_ratio",
      "description": "Cache hit efficiency ratio for prompt prefix reuse (0.0 to 1.0).",
      "unit": "ratio",
      "scopes": ["worker"],
      "type": "gauge"
    }
  ],
  "unavailable_capabilities": [
    {
      "capability": "gpu_hardware_sensors_via_api",
      "status": "unsupported",
      "reason": "Host hardware sensor telemetry (VRAM bytes, GPU temperature, wattage) is queried on-host by vllm-top and is not exposed over the gateway proxy API."
    },
    {
      "capability": "arbitrary_promql_expressions",
      "status": "unsupported",
      "reason": "Arbitrary metrics expressions are rejected; queries are strictly bounded to named parameters."
    },
    {
      "capability": "cross_client_request_history",
      "status": "unsupported",
      "reason": "Requests from other clients are isolated by design and cannot be queried."
    },
    {
      "capability": "raw_prompt_payload_storage",
      "status": "unsupported",
      "reason": "Raw prompts, completions, and headers are excluded from telemetry store for data privacy."
    }
  ],
  "active_workers": [
    {
      "worker_id": "b0-live-llama-worker1",
      "pool": "lead",
      "role": "production",
      "model_id": "Qwen3.6-35B-A3B-UD-Q4_K_M",
      "public_model_id": "engineering/lead",
      "engine": "llama.cpp",
      "context_limit": 65536,
      "max_concurrency": 1
    },
    {
      "worker_id": "b0-live-llama-deep-worker2",
      "pool": "deep",
      "role": "production",
      "model_id": "Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M",
      "public_model_id": "engineering/deep",
      "engine": "llama.cpp",
      "context_limit": 65536,
      "max_concurrency": 1
    }
  ]
}
```

---

### 4.2 Telemetry Query: `GET /v1/telemetry/inference`

Retrieves bounded telemetry observations across appliance, worker, and request scopes.

#### Query Parameters
| Parameter | Type | Required | Description | Constraints |
|---|---|---|---|---|
| `scope` | string | Optional | Scope level: `appliance`, `worker`, `request`, or `all`. | Defaults to `all` for telemetry clients, or `request` when `request_id` is supplied. |
| `request_id` | string | Optional | Correlation UUID of a specific request. | Client must own the request. If provided, effective scope is `request`. |
| `worker_id` | string | Optional | Target worker identifier (e.g., `b0-live-llama-worker1`). | Must match a registered worker. |
| `model` | string | Optional | Filter requests by public model alias or engine model id. | |
| `metric` | string | Optional | Filter output to a specific metric name (e.g. `ttft_seconds`). | Must match a cataloged metric name. |
| `limit` | integer | Optional | Maximum number of request records returned. | Integer between 1 and 100. Default: 10. |

---

## 5. Scope Definitions and Response Structures

### 5.1 Request Scope (`scope=request`)

Provides high-resolution telemetry for individual inference requests, correlated by `request_id`.

#### Querying by Request ID
`GET /v1/telemetry/inference?request_id=c1234567-89ab-cdef-0123-456789abcdef`

```json
{
  "object": "telemetry_inference",
  "api_version": "2026-10-09",
  "version": "2026-10-09",
  "timestamp": "2026-10-09T15:20:05.123456+00:00",
  "client_id": "nexus",
  "scope": "request",
  "requests": [
    {
      "request_id": "c1234567-89ab-cdef-0123-456789abcdef",
      "client_id": "nexus",
      "worker_id": "b0-live-llama-worker1",
      "pool": "lead",
      "model": "engineering/lead",
      "model_id": "Qwen3.6-35B-A3B-UD-Q4_K_M",
      "artifact_digest": "sha256:d489...665e",
      "stream": true,
      "priority": "interactive",
      "status": "completed",
      "termination": "complete",
      "finish_reason": "stop",
      "prompt_tokens": 1542,
      "completion_tokens": 284,
      "cached_prompt_tokens": 896,
      "queue_duration_seconds": 0.001245,
      "ttft_seconds": 0.384210,
      "ttft_provenance": "streaming_first_chunk",
      "inter_token_latency_seconds": 0.041852,
      "itl_provenance": "streaming_delta_intervals",
      "duration_seconds": 12.285412,
      "timestamp": "2026-10-09T15:20:00.123456+00:00"
    }
  ]
}
```

#### Timings and Provenance Field Definitions
- `stream`: Boolean indicating whether SSE streaming was used.
- `queue_duration_seconds`: Time spent queued in the gateway admission scheduler waiting for concurrency slot grant.
- `ttft_seconds`: Time to First Token in seconds.
- `ttft_provenance`: Origin of the TTFT observation:
  - `"streaming_first_chunk"`: Measured directly by gateway timer on arrival of the first SSE chunk.
  - `"engine_reported_timings"`: Prefill `prompt_ms` reported in engine response body (non-streaming).
- `inter_token_latency_seconds`: Average generation time per output token.
- `itl_provenance`: Origin of the ITL observation:
  - `"streaming_delta_intervals"`: Monotonic delta between consecutive SSE token arrivals.
  - `"engine_reported_timings"`: Derived from engine `predicted_ms / predicted_n`.

---

### 5.2 Worker Scope (`scope=worker`)

Provides worker-level engine stats, cache occupancies, active concurrency, and latency distributions.

`GET /v1/telemetry/inference?scope=worker&worker_id=b0-live-llama-worker1`

```json
{
  "object": "telemetry_inference",
  "api_version": "2026-10-09",
  "version": "2026-10-09",
  "timestamp": "2026-10-09T15:20:10.000000+00:00",
  "client_id": "nexus",
  "scope": "worker",
  "workers": [
    {
      "worker_id": "b0-live-llama-worker1",
      "pool": "lead",
      "role": "production",
      "model_id": "Qwen3.6-35B-A3B-UD-Q4_K_M",
      "public_model_id": "engineering/lead",
      "artifact_digest": "sha256:d489...665e",
      "engine": "llama.cpp",
      "gpu_assignment": [0],
      "status": "ready",
      "healthy": true,
      "available": true,
      "context_limit": 65536,
      "max_concurrency": 1,
      "inflight_requests": 0,
      "cache": {
        "kv_cache_usage_ratio": 0.1712,
        "prefix_cache_hit_ratio": 0.5000,
        "prompt_tokens_cached_total": 45210
      },
      "engine_counters": {
        "requests_running": 0,
        "requests_waiting": 0,
        "prompt_tokens_total": 128450,
        "generation_tokens_total": 34120
      },
      "latency_distributions": {
        "ttft_seconds": {
          "count": 142,
          "sum": 52.84,
          "avg": 0.3721,
          "buckets": {
            "0.05": 12,
            "0.1": 45,
            "0.25": 98,
            "0.5": 135,
            "1.0": 142
          }
        },
        "inter_token_latency_seconds": {
          "count": 142,
          "sum": 5.96,
          "avg": 0.0419,
          "buckets": {
            "0.02": 5,
            "0.05": 138,
            "0.1": 142
          }
        },
        "queue_wait_seconds": {
          "count": 142,
          "sum": 0.18,
          "avg": 0.0012,
          "buckets": {
            "0.001": 110,
            "0.005": 140,
            "0.01": 142
          }
        }
      },
      "freshness": {
        "observed_at": "2026-10-09T15:20:08.500000+00:00",
        "age_seconds": 1.5,
        "stale": false
      }
    }
  ]
}
```

---

### 5.3 Appliance Scope (`scope=appliance`)

Provides global gateway admission health, queue depths, and worker fleet availability.

`GET /v1/telemetry/inference?scope=appliance`

```json
{
  "object": "telemetry_inference",
  "api_version": "2026-10-09",
  "version": "2026-10-09",
  "timestamp": "2026-10-09T15:20:15.000000+00:00",
  "client_id": "nexus",
  "scope": "appliance",
  "appliance": {
    "gateway": {
      "status": "healthy",
      "uptime_seconds": 84210.5,
      "start_time_seconds": 1791500000.0,
      "version": "2026-10-09"
    },
    "workers_summary": {
      "total": 2,
      "healthy": 2,
      "available": 2
    },
    "admission": {
      "queued_work": 0,
      "active_work": 1,
      "dependency_blocked_work": 0,
      "queue_depth_by_pool": {
        "lead": 0,
        "deep": 0
      }
    },
    "totals": {
      "requests_received": 1420,
      "requests_rejected": 2
    }
  }
}
```

---

## 6. Error Semantics & HTTP Status Codes

The interface enforces strict HTTP error codes with descriptive JSON payloads:

| Status Code | Reason | Example Payload |
|---|---|---|
| `400 Bad Request` | Invalid query parameter (e.g. limit < 1 or > 100, unsupported metric name, invalid scope). | `{"error": {"message": "limit must be between 1 and 100", "type": "invalid_request_error"}}` |
| `401 Unauthorized` | Missing or invalid Bearer token. | `{"error": {"message": "valid bearer token required", "type": "unauthorized"}}` |
| `403 Forbidden` | Authenticated client lacks permission for the requested scope (e.g. `workload`-only client requesting `scope=worker` or `scope=appliance`). | `{"error": {"message": "telemetry, monitoring or admin scope required for aggregate worker/appliance telemetry", "type": "forbidden"}}` |
| `404 Not Found` | Requested worker ID not found, or requested `request_id` either does not exist or belongs to another client. | `{"error": {"message": "request_id '...' not found", "type": "not_found"}}` |
| `503 Service Unavailable` | Gateway is shutting down or telemetry buffer is uninitialized. | `{"error": {"message": "telemetry service unavailable", "type": "service_unavailable"}}` |

> [!NOTE]
> Cross-client request isolation explicitly returns **HTTP 404** (rather than 403) when querying another client's `request_id`. This prevents unauthorized clients from probing or confirming the existence of other clients' transactions.
