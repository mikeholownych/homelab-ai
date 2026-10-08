# T5820 Orchestrator Gateway Observability Contract

**Date**: 2026-09-29  
**Status**: Implemented and offline qualified; awaiting operational maintenance window for live deployment.  
**Service Target**: `aihost-orchestrator-gateway.service` (Dell Precision T5820, loopback `127.0.0.1:8010`).

---

## 1. Overview & Architecture

The T5820 orchestrator gateway provides authenticated OpenAI-compatible inference, capability-aware worker scheduling, dependency-gated graph execution, and hash-chained evidence recording for dual independent TP=1 vLLM workers (`b0-live-tp1-worker1` and `b0-live-tp1-worker2`).

To support continuous production monitoring by VictoriaMetrics / Prometheus without impacting active inference workloads or introducing external runtime dependencies:
1. `GET /health`: JSON operational health and readiness endpoint distinguishing process liveness, scheduler readiness, and downstream worker health.
2. `GET /metrics`: Prometheus text exposition format 0.0.4 metric exporter exposing bounded-cardinality counters, gauges, and latency histograms.

Both endpoints are **non-blocking**, **scrape-safe**, and execute in $O(1)$ memory without invoking downstream model inference or triggering scheduler side effects.

---

## 2. Health Endpoint Contract: `GET /health`

### 2.1 Interface & Query Parameters

- **Path**: `GET /health`
- **Content-Type**: `application/json`
- **Query Parameters**:
  - `strict`: Optional boolean (`true` or `1`). When `strict=true`, degraded states (e.g. 1 of 2 workers down) return HTTP `503 Service Unavailable` instead of `200 OK`.

### 2.2 Health State Model

| Health State | HTTP Status (Default) | HTTP Status (`strict=true`) | `ready` | `can_route` | Description |
|:---|:---:|:---:|:---:|:---:|:---|
| **`healthy`** | `200 OK` | `200 OK` | `true` | `true` | Gateway alive, scheduler operational, all workers expected to serve are healthy and fresh. |
| **`degraded`** | `200 OK` | `503 Service Unavailable` | `true` | `true` | Gateway alive and able to route inference to at least one healthy worker, but one or more workers expected to serve are unhealthy or stale. |
| **`unavailable`** | `503 Service Unavailable` | `503 Service Unavailable` | `false` | `false` | Zero workers are healthy/available, or scheduler is unable to route requests. |
| **`stale`** | Evaluated as `unavailable` or `degraded` | Evaluated as `unavailable` or `degraded` | Dynamic | Dynamic | Worker observation age exceeds configured TTL (`max_freshness_seconds`, default 30.0s). |

A worker configured with `status: "stopped"` remains in the worker registry and `/health` response, with
`status: "stopped"`, `healthy: false`, `expected_state: "stopped"`, and `blocked_reason: "operator_stopped"`.
It is not probed, does not contribute to degradation or dependency staleness, and is excluded from scheduler
`total_workers`. `configured_workers` and `stopped_workers` retain the inventory counts. vllm-top does not
discover stopped workers as inference instances; its gateway detail panel labels them `stopped` neutrally.

### 2.3 JSON Schema Contract

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "OrchestratorHealthResponse",
  "type": "object",
  "required": ["status", "ready", "can_route", "timestamp", "gateway", "scheduler", "workers", "dependency_freshness"],
  "properties": {
    "status": {
      "type": "string",
      "enum": ["healthy", "degraded", "unavailable"]
    },
    "ready": {
      "type": "boolean",
      "description": "True if gateway can accept requests right now"
    },
    "can_route": {
      "type": "boolean",
      "description": "True if at least one model worker is available to serve inference"
    },
    "timestamp": {
      "type": "string",
      "format": "date-time"
    },
    "gateway": {
      "type": "object",
      "required": ["status", "uptime_seconds", "pid"],
      "properties": {
        "status": { "type": "string", "enum": ["alive"] },
        "uptime_seconds": { "type": "number", "minimum": 0 },
        "pid": { "type": "integer" }
      }
    },
    "scheduler": {
      "type": "object",
      "required": ["ready", "status", "queued_work", "active_work", "available_workers", "total_workers"],
      "properties": {
        "ready": { "type": "boolean" },
        "status": { "type": "string", "enum": ["ready", "blocked"] },
        "queued_work": { "type": "integer", "minimum": 0 },
        "active_work": { "type": "integer", "minimum": 0 },
        "available_workers": { "type": "integer", "minimum": 0 },
        "total_workers": { "type": "integer", "minimum": 0, "description": "Workers expected to serve, including unhealthy workers; excludes stopped workers." },
        "configured_workers": { "type": "integer", "minimum": 0 },
        "stopped_workers": { "type": "integer", "minimum": 0 }
      }
    },
    "workers": {
      "type": "object",
      "additionalProperties": {
        "type": "object",
        "required": ["status", "healthy", "public_model_id", "model_id", "last_observed_seconds_ago", "last_check_timestamp", "consecutive_failures"],
        "properties": {
          "status": { "type": "string", "enum": ["healthy", "unhealthy", "stale", "unknown", "stopped"] },
          "healthy": { "type": "boolean" },
          "public_model_id": { "type": "string" },
          "model_id": { "type": "string" },
          "last_observed_seconds_ago": { "type": ["number", "null"] },
          "last_check_timestamp": { "type": ["string", "null"], "format": "date-time" },
          "consecutive_failures": { "type": "integer", "minimum": 0 }
        }
      }
    },
    "dependency_freshness": {
      "type": "object",
      "required": ["freshness_seconds", "max_ttl_seconds", "is_stale"],
      "properties": {
        "freshness_seconds": { "type": "number", "minimum": 0 },
        "max_ttl_seconds": { "type": "number", "minimum": 0 },
        "is_stale": { "type": "boolean" }
      }
    }
  }
}
```

### 2.4 Example Payloads

#### Healthy State (`200 OK`)
```json
{
  "status": "healthy",
  "ready": true,
  "can_route": true,
  "timestamp": "2026-09-29T08:30:00.000000+00:00",
  "gateway": {
    "status": "alive",
    "uptime_seconds": 1845.210,
    "pid": 3542340
  },
  "scheduler": {
    "ready": true,
    "status": "ready",
    "queued_work": 0,
    "active_work": 1,
    "available_workers": 2,
    "total_workers": 2
  },
  "workers": {
    "b0-live-tp1-worker1": {
      "status": "healthy",
      "healthy": true,
      "public_model_id": "engineering/b0",
      "model_id": "Qwen/Qwen2.5-Coder-32B-Instruct",
      "last_observed_seconds_ago": 1.450,
      "last_check_timestamp": "2026-09-29T08:29:58.550000+00:00",
      "consecutive_failures": 0
    },
    "b0-live-tp1-worker2": {
      "status": "healthy",
      "healthy": true,
      "public_model_id": "engineering/b0",
      "model_id": "Qwen/Qwen2.5-Coder-32B-Instruct",
      "last_observed_seconds_ago": 2.110,
      "last_check_timestamp": "2026-09-29T08:29:57.890000+00:00",
      "consecutive_failures": 0
    }
  },
  "dependency_freshness": {
    "freshness_seconds": 2.110,
    "max_ttl_seconds": 30.0,
    "is_stale": false
  }
}
```

#### Degraded State (`200 OK` or `503 Service Unavailable` with `?strict=true`)
```json
{
  "status": "degraded",
  "ready": true,
  "can_route": true,
  "timestamp": "2026-09-29T08:31:00.000000+00:00",
  "gateway": {
    "status": "alive",
    "uptime_seconds": 1905.210,
    "pid": 3542340
  },
  "scheduler": {
    "ready": true,
    "status": "ready",
    "queued_work": 0,
    "active_work": 0,
    "available_workers": 1,
    "total_workers": 2
  },
  "workers": {
    "b0-live-tp1-worker1": {
      "status": "healthy",
      "healthy": true,
      "public_model_id": "engineering/b0",
      "model_id": "Qwen/Qwen2.5-Coder-32B-Instruct",
      "last_observed_seconds_ago": 3.120,
      "last_check_timestamp": "2026-09-29T08:30:56.880000+00:00",
      "consecutive_failures": 0
    },
    "b0-live-tp1-worker2": {
      "status": "unhealthy",
      "healthy": false,
      "public_model_id": "engineering/b0",
      "model_id": "Qwen/Qwen2.5-Coder-32B-Instruct",
      "last_observed_seconds_ago": 0.500,
      "last_check_timestamp": "2026-09-29T08:30:59.500000+00:00",
      "consecutive_failures": 3
    }
  },
  "dependency_freshness": {
    "freshness_seconds": 3.120,
    "max_ttl_seconds": 30.0,
    "is_stale": false
  }
}
```

---

## 3. Prometheus Metrics Inventory: `GET /metrics`

- **Path**: `GET /metrics`
- **Content-Type**: `text/plain; version=0.0.4; charset=utf-8`

### 3.1 Complete Metric Family Table

| Metric Name | Type | Unit | Description | Labels | Label Values |
|:---|:---:|:---:|:---|:---|:---|
| `aihost_gateway_uptime_seconds` | Gauge | seconds | Current process uptime. | None | N/A |
| `aihost_gateway_start_time_seconds` | Gauge | seconds | Process start time (Unix epoch). | None | N/A |
| `aihost_http_requests_total` | Counter | requests | Total HTTP requests handled. | `route`, `method`, `status_class` | `route`: `v1_chat_completions`, `v1_models`, `health`, `metrics`, `unsupported`<br>`method`: `GET`, `POST`<br>`status_class`: `2xx`, `4xx`, `5xx` |
| `aihost_http_request_duration_seconds` | Histogram | seconds | Latency of HTTP requests. Buckets: 5ms, 10ms, 25ms, 50ms, 100ms, 250ms, 500ms, 1s, 2.5s, 5s, 10s, 30s, 60s. | `route`, `method` | Same as above. |
| `aihost_http_requests_in_flight` | Gauge | requests | Active requests currently being served. | `route` | Same as above. |
| `aihost_http_auth_failures_total` | Counter | rejections | Total authentication rejections. | `route` | Same as above. |
| `aihost_inference_requests_total` | Counter | requests | Inference requests received at runtime. | `status` | `received`, `rejected` |
| `aihost_inference_dispatches_total` | Counter | dispatches | Requests dispatched to a model worker. | `worker_id`, `model` | `worker_id`: `b0-live-tp1-worker1`, `b0-live-tp1-worker2`<br>`model`: `engineering/b0` |
| `aihost_inference_completions_total` | Counter | completions | Terminal completion count by outcome. | `worker_id`, `outcome` | `outcome`: `completed`, `failed`, `cancelled`, `timed_out` |
| `aihost_inference_duration_seconds` | Histogram | seconds | End-to-end model inference duration. Buckets: 100ms, 250ms, 500ms, 1s, 2.5s, 5s, 10s, 30s, 60s, 120s. | `worker_id`, `model` | Same as above. |
| `aihost_inference_ttft_seconds` | Histogram | seconds | Time to First Token for streaming requests. Buckets: 10ms, 50ms, 100ms, 250ms, 500ms, 1s, 2.5s, 5s, 10s. | `worker_id` | Same as above. |
| `aihost_inference_prompt_tokens_total` | Counter | tokens | Estimated prompt tokens processed. | `worker_id`, `model` | Same as above. |
| `aihost_inference_completion_tokens_total` | Counter | tokens | Estimated completion tokens generated. | `worker_id`, `model` | Same as above. |
| `aihost_inference_streaming_requests_total` | Counter | requests | Streaming inference requests by outcome. | `worker_id`, `outcome` | `outcome`: `success`, `failure` |
| `aihost_scheduler_queued_work` | Gauge | tasks | Current queued tasks in scheduler. | None | N/A |
| `aihost_scheduler_active_work` | Gauge | tasks | Current actively executing tasks. | None | N/A |
| `aihost_scheduler_queue_wait_seconds` | Histogram | seconds | Queue wait latency before execution. Buckets: 1ms, 5ms, 10ms, 50ms, 100ms, 500ms, 1s, 5s, 15s, 30s, 60s. | None | N/A |
| `aihost_scheduler_dispatch_decisions_total` | Counter | decisions | Scheduler routing decisions. | `worker_id`, `decision` | `decision`: `dispatched`, `rejected_concurrency`, `rejected_capability`, `rejected_unhealthy` |
| `aihost_scheduler_worker_available` | Gauge | status | Worker availability (1 = available, 0 = busy/down). | `worker_id` | Configured worker IDs. |
| `aihost_scheduler_dependency_blocked_work` | Gauge | tasks | Tasks blocked by dependency gates. | None | N/A |
| `aihost_scheduler_admission_backpressure_total` | Counter | rejections | Backpressure admission rejections. | `reason` | `body_limit`, `capacity_exceeded`, `unsupported_capability`, `request_shape` |
| `aihost_worker_health_status` | Gauge | status | Worker health (1 = healthy, 0 = unhealthy). | `worker_id` | Configured worker IDs. |
| `aihost_worker_last_check_timestamp_seconds` | Gauge | seconds | Timestamp of last worker observation. | `worker_id` | Configured worker IDs. |
| `aihost_worker_check_duration_seconds` | Gauge | seconds | Latency of last worker probe/call. | `worker_id` | Configured worker IDs. |
| `aihost_provider_errors_total` | Counter | errors | Downstream worker provider errors. | `worker_id`, `error_type` | `error_type`: `timeout`, `connection_error`, `http_5xx`, `invalid_response` |
| `aihost_worker_quarantine_status` | Gauge | status | Circuit breaker quarantine status (0 = normal, 1 = quarantined). | `worker_id` | Configured worker IDs. |
| `aihost_authority_validations_total` | Counter | validations | External validation outcomes. | `outcome` | `accepted`, `rejected` |
| `aihost_preflight_rejections_total` | Counter | rejections | Fail-closed preflight rejections. | `reason` | `state_hash_mismatch`, `missing_evidence`, `expired_capability` |
| `aihost_evidence_verification_failures_total` | Counter | failures | Evidence store write or hash check failures. | None | N/A |
| `aihost_authority_rejections_total` | Counter | rejections | Tool authority boundary rejections. | `reason` | `unauthorized_action`, `capability_denied`, `expired_authority` |

### 3.2 Cardinality Ceiling

Every label is strictly bounded to an enumerated domain. High-cardinality items (request UUIDs, client IPs, prompt text, user IDs, raw exception messages, tool parameter hashes) are strictly excluded from metric labels.

- Total maximum distinct time series for a 2-worker deployment: **under 180 total time series**, ensuring trivial memory and TSDB ingestion footprint.

---

## 4. VictoriaMetrics / Prometheus Scrape Configuration

To integrate with the host's existing VictoriaMetrics TSDB service (`aihost-observability-victoriametrics.service` on port 8428):

```yaml
# /etc/local-ai/observability/prometheus.yml or vmagent scrape config
scrape_configs:
  - job_name: 'aihost-orchestrator-gateway'
    scrape_interval: 10s
    scrape_timeout: 5s
    metrics_path: /metrics
    static_configs:
      - targets: ['127.0.0.1:8010']
        labels:
          environment: production
          host: ai-5820-01
          service: orchestrator-gateway
          role: inference-gateway
```

If monitoring authentication is enabled via `ORCHESTRATOR_REQUIRE_MONITORING_AUTH=true`:
```yaml
    bearer_token_file: /etc/local-ai/orchestrator/monitoring-token
```

---

## 5. PromQL Query Library

### 5.1 Gateway Availability
```promql
# Gateway process up and serving
up{job="aihost-orchestrator-gateway"} == 1
```

### 5.2 Worker Health Status
```promql
# Health status of each worker (1 = healthy, 0 = unhealthy)
aihost_worker_health_status{job="aihost-orchestrator-gateway"}

# Alert if any worker is unhealthy for > 1 minute
aihost_worker_health_status == 0
```

### 5.3 Request Latency (HTTP Gateway)
```promql
# 95th percentile HTTP request duration by route
histogram_quantile(0.95, sum(rate(aihost_http_request_duration_seconds_bucket[5m])) by (le, route))

# Median (p50) inference endpoint latency
histogram_quantile(0.50, sum(rate(aihost_http_request_duration_seconds_bucket{route="v1_chat_completions"}[5m])) by (le))
```

### 5.4 Model Inference Latency & TTFT
```promql
# 95th percentile inference execution duration by worker
histogram_quantile(0.95, sum(rate(aihost_inference_duration_seconds_bucket[5m])) by (le, worker_id))

# 95th percentile Time to First Token (TTFT) for streaming requests
histogram_quantile(0.95, sum(rate(aihost_inference_ttft_seconds_bucket[5m])) by (le, worker_id))
```

### 5.5 Accepted Throughput & Dispatches
```promql
# Completed inference requests per minute by worker
sum(rate(aihost_inference_completions_total{outcome="completed"}[1m])) by (worker_id) * 60

# Total token generation rate (tokens per second)
sum(rate(aihost_inference_completion_tokens_total[1m])) by (worker_id)
```

### 5.6 Queue Wait Duration & Concurrency
```promql
# 95th percentile queue wait time
histogram_quantile(0.95, sum(rate(aihost_scheduler_queue_wait_seconds_bucket[5m])) by (le))

# Current active concurrent inference requests
aihost_scheduler_active_work{job="aihost-orchestrator-gateway"}
```

### 5.7 Errors, Timeouts & Rejections
```promql
# Provider error rate by worker and error type
sum(rate(aihost_provider_errors_total[5m])) by (worker_id, error_type)

# Authentication rejection rate
sum(rate(aihost_http_auth_failures_total[5m])) by (route)

# Authority boundary rejection rate
sum(rate(aihost_authority_rejections_total[5m])) by (reason)
```

---

## 6. Security & Credential Boundary Review

1. **Inference API Authentication**: `/v1/models` and `/v1/chat/completions` strictly require valid `client_token` credentials via `Authorization: Bearer <token>`.
2. **Monitoring Protection**: `/health` and `/metrics` are designed to bind to localhost loopback (`127.0.0.1:8010`). If exposed across network boundaries, `ORCHESTRATOR_REQUIRE_MONITORING_AUTH=true` enforces a dedicated `ORCHESTRATOR_MONITORING_TOKEN`. A monitoring token **cannot** access `/v1/*` routes.
3. **Data Sanitization**: No user prompt content, tokens, completion text, system paths, or credential hashes are exposed in `/health` or `/metrics`.

---

## 7. Operational Deployment & Rollback Procedure

> [!IMPORTANT]
> Live deployment to the T5820 host is **not authorized** during active performance campaigns (e.g. Phase 14 requalification). The procedure below must be executed only during an authorized maintenance window.

### 7.1 Deployment Procedure (Authorized Window Only)
1. Verify active campaign is drained:
   ```bash
   ssh 10.0.8.5 "systemctl status aihost-orchestrator-gateway.service"
   ```
2. Build new release directory:
   ```bash
   RELEASE_DIR="/var/lib/aihost/releases/t5820-gateway-$(git rev-parse --short HEAD)"
   sudo mkdir -p "$RELEASE_DIR"
   sudo cp -r orchestrator_gateway orchestrator_runtime orchestrator_contract "$RELEASE_DIR/"
   sudo chown -R aihost-runtime:render "$RELEASE_DIR"
   ```
3. Update systemd drop-in `/etc/systemd/system/aihost-orchestrator-gateway.service.d/15-release.conf`:
   ```ini
   [Service]
   WorkingDirectory=/var/lib/aihost/releases/t5820-gateway-<rev>
   Environment=PYTHONPATH=/var/lib/aihost/releases/t5820-gateway-<rev>
   ```
4. Reload systemd and restart service:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart aihost-orchestrator-gateway.service
   ```
5. Verify operational readiness:
   ```bash
   curl -s -i http://127.0.0.1:8010/health
   curl -s -i http://127.0.0.1:8010/metrics | head -n 30
   ```

### 7.2 Rollback Procedure
If degraded behavior is observed:
1. Revert `/etc/systemd/system/aihost-orchestrator-gateway.service.d/15-release.conf` to point back to the previous release (`/var/lib/aihost/releases/t5820-gateway-e523f9a`).
2. Reload and restart:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart aihost-orchestrator-gateway.service
   ```
3. Verify baseline restoration:
   ```bash
   curl -s http://127.0.0.1:8010/v1/models -H "Authorization: Bearer $(cat /etc/local-ai/orchestrator/client-token)"
   ```
