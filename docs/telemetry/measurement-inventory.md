# T5820 Inference Appliance: Measurement Source Inventory

## 1. Architectural Data Path

Operational measurements originate across multiple appliance subsystems and traverse distinct collection and normalization stages before arriving at the client telemetry interface:

```
[ Inference Engine (llama-server) ]
   ├── /metrics (Prometheus format) ──────────┐
   ├── /slots (JSON slot state) ──────────────┼──> [ HealthManager._stats_loop ]
   └── HTTP response body timings / usage ──┐ │        (2.0s polling interval)
                                            │ │                  │
[ Gateway Scheduler & Concurrency Slots ]   │ │                  ▼
   ├── Ticket wait timer (monotonic) ───────┼─┼──> [ engine_stats.py ]
   └── Active / queued work counts ─────────┼─┤        (Normalized cache ratios & slot counts)
                                            │ │                  │
[ Gateway Streaming SSE Proxy ]             │ │                  ▼
   ├── First chunk delta timer (monotonic) ─┼─┴──> [ MetricsRegistry & Histograms ]
   └── Inter-token delta timers ────────────┘          (Prometheus /metrics & in-memory distributions)
                                                                 │
                                                                 ▼
                                                   [ TelemetryService / Buffer ]
                                                       (Bounded ring buffer & API)
                                                                 │
                                                                 ▼
                                                   [ GET /v1/telemetry/* ]
```

### Subsystem Roles
1. **Engine Polling (Worker Scope):** `HealthManager._stats_loop` polls each worker's `/metrics` and `/slots` endpoints every 2.0s. Normalization functions in [`engine_stats.py`](file:///home/mike/Projects/aihost/orchestrator_runtime/engine_stats.py) compute KV-cache usage ratio, prefix-cache hit ratio, and active slot counts.
2. **Request-Level Timing (Request Scope):**
   - **Queue Wait:** Measured by gateway admission scheduler ([`admission.py`](file:///home/mike/Projects/aihost/orchestrator_runtime/admission.py)) as the monotonic delta between ticket creation and slot acquisition.
   - **Streaming TTFT & ITL:** Measured by the SSE streaming loop in [`server.py`](file:///home/mike/Projects/aihost/orchestrator_gateway/server.py). The gateway records the exact duration until the first SSE chunk arrives, and monotonic intervals between subsequent chunk deltas.
   - **Non-Streaming TTFT & ITL:** Extracted from the worker's JSON response `timings` field (`prompt_ms` for TTFT, `predicted_ms / predicted_n` for ITL) in [`runtime.py`](file:///home/mike/Projects/aihost/orchestrator_runtime/runtime.py).
3. **GPU Hardware Sensors (Out-of-Band):** Intel Arc Pro B65 hardware metrics (VRAM allocation, GPU core frequency, temperature, wattage) are polled on-host by `vllm-top` directly via `/usr/bin/xpu-smi`. They do not transit the gateway proxy path and are explicitly classified as unsupported over the gateway client API.

---

## 2. Measurement Source Inventory

| Metric Identity | Origin | Source Location | Unit | Scope | Type | Availability | Accuracy | Freshness | Exposure Suitability |
|---|---|---|---|---|---|---|---|---|---|
| `ttft_seconds` (streaming) | Gateway | `server.py:_completion` | Seconds | Request, Worker | Histogram / Scalar | Available | Measured | Event-driven (request completion) | Safe (client isolated) |
| `ttft_seconds` (non-streaming) | Worker Engine | `runtime.py:complete` (from engine `prompt_ms`) | Seconds | Request, Worker | Histogram / Scalar | Available | Engine-reported | Event-driven (request completion) | Safe (client isolated) |
| `inter_token_latency_seconds` (streaming) | Gateway | `server.py:_completion` | Seconds | Request, Worker | Histogram / Scalar | Available | Measured | Event-driven (request completion) | Safe (client isolated) |
| `inter_token_latency_seconds` (non-streaming) | Worker Engine | `runtime.py:complete` (from `predicted_ms / predicted_n`) | Seconds | Request, Worker | Histogram / Scalar | Available | Engine-reported | Event-driven (request completion) | Safe (client isolated) |
| `queue_wait_seconds` | Gateway | `admission.py:acquire`, `runtime.py:complete` | Seconds | Request, Worker | Histogram / Scalar | Available | Measured | Event-driven | Safe |
| `duration_seconds` | Gateway | `runtime.py:complete` | Seconds | Request, Worker | Histogram / Scalar | Available | Measured | Event-driven | Safe |
| `prompt_tokens` | Worker Engine | `runtime.py:complete` (from engine `usage.prompt_tokens`) | Tokens | Request, Worker | Counter / Integer | Available | Engine-reported | Event-driven | Safe |
| `completion_tokens` | Worker Engine | `runtime.py:complete` (from engine `usage.completion_tokens`) | Tokens | Request, Worker | Counter / Integer | Available | Engine-reported | Event-driven | Safe |
| `cached_prompt_tokens` | Worker Engine | `runtime.py:complete` (from `prompt_tokens_details.cached_tokens` or `cache_n`) | Tokens | Request | Integer | Available | Engine-reported | Event-driven | Safe |
| `finish_reason` | Worker Engine | `runtime.py:complete` (from engine `finish_reason`) | String | Request | Categorical | Available | Engine-reported | Event-driven | Safe |
| `termination` | Gateway | `runtime.py:complete`, `reasoning.py` | String | Request | Categorical | Available | Evaluated | Event-driven | Safe |
| `kv_cache_usage_ratio` | Worker Engine | `engine_stats.py:normalize_metrics` | Ratio (0.0-1.0) | Worker | Gauge | Available | Engine-reported | 2.0s poll interval | Restricted (telemetry scope) |
| `prefix_cache_hit_ratio` | Worker Engine | `engine_stats.py:normalize_metrics` | Ratio (0.0-1.0) | Worker | Gauge | Available | Engine-reported | 2.0s poll interval | Restricted (telemetry scope) |
| `prompt_tokens_cached_total` | Worker Engine | `engine_stats.py:normalize_metrics` | Tokens | Worker | Counter | Available | Engine-reported | 2.0s poll interval | Restricted (telemetry scope) |
| `requests_running` | Worker Engine | `engine_stats.py:normalize_slots` | Count | Worker | Gauge | Available | Engine-reported | 2.0s poll interval | Restricted (telemetry scope) |
| `requests_waiting` | Worker Engine | `engine_stats.py:normalize_slots` | Count | Worker | Gauge | Available | Engine-reported | 2.0s poll interval | Restricted (telemetry scope) |
| `scheduler_queue_depth` | Gateway | `admission.py:queued`, `metrics.py` | Count | Appliance, Pool | Gauge | Available | Measured | Instantaneous | Restricted (telemetry scope) |
| `active_work` | Gateway | `admission.py:inflight`, `metrics.py` | Count | Appliance | Gauge | Available | Measured | Instantaneous | Restricted (telemetry scope) |
| `worker_health_status` | Gateway | `health.py:HealthManager` | Boolean | Worker | Gauge | Available | Measured (HTTP probe) | 10.0s probe interval | Restricted (telemetry scope) |
| `gpu_vram_allocation_bytes` | GPU Driver / Sysfs | Host `xpu-smi` | Bytes | Worker / Device | Gauge | Out-of-band | Measured | Queried by vllm-top | Unsupported via API |
| `gpu_utilization_ratio` | GPU Driver / Sysfs | Host `xpu-smi` | Ratio | Device | Gauge | Out-of-band | Measured | Queried by vllm-top | Unsupported via API |
| `gpu_temperature_celsius` | GPU Driver / Sysfs | Host `xpu-smi` | Celsius | Device | Gauge | Out-of-band | Measured | Queried by vllm-top | Unsupported via API |
| `gpu_power_watts` | GPU Driver / Sysfs | Host `xpu-smi` | Watts | Device | Gauge | Out-of-band | Measured | Queried by vllm-top | Unsupported via API |
| `raw_prompt_text` | Client / Gateway | Request body | Text | Request | Payload | Excluded | Measured | Transient | Unsupported (privacy) |
| `completion_text` | Worker / Gateway | Response body | Text | Request | Payload | Excluded | Measured | Transient | Unsupported (privacy) |

---

## 3. Analysis of Observational Capabilities

### 3.1 Streaming vs. Non-Streaming Measurement Differences
- **Streaming Requests (`stream: true`):**
  - TTFT is measured as wall-clock elapsed time from request dispatch until the arrival of the first SSE chunk (`ttft_provenance: "streaming_first_chunk"`). This captures the real end-user perception of latency, including prefill computation, worker HTTP serialization, and network delivery.
  - ITL is calculated across all generated tokens as the average interval between consecutive chunks (`itl_provenance: "streaming_delta_intervals"`).
- **Non-Streaming Requests (`stream: false`):**
  - The client receives the response only after the entire generation finishes. TTFT cannot be observed via chunk arrival; instead, the gateway extracts the engine's internal prefill duration (`prompt_ms`) from response timings (`ttft_provenance: "engine_reported_timings"`).
  - ITL is computed from the engine's predicted generation duration divided by token count (`predicted_ms / predicted_n`).

### 3.2 Gateway vs. Host Hardware Metrics
vllm-top 1.0.3 displays host GPU sensors (VRAM allocated/free, GPU utilization, temperatures, wattage). These measurements are read directly from Intel oneAPI Level Zero and `xpu-smi` by the console running locally on the appliance host.
Exposing host GPU hardware sensors over the gateway API is explicitly declared **unsupported** in `/v1/telemetry/capabilities` for three reasons:
1. **Separation of Concerns:** The gateway is an application-level model proxy, not a hardware monitoring agent. Hardware metrics belong in node-level Prometheus exporters (`intel_gpu_exporter` / `node_exporter`).
2. **Multi-Tenant GPU Sharing:** Dual Arc Pro B65 cards are shared by dedicated worker processes. Correlating raw board-level wattage or VRAM memory pages to an individual ephemeral HTTP request is physically imprecise and architecturally misleading.
3. **Overhead and Reliability:** Invoking external driver CLI tools (`xpu-smi`) from synchronous gateway request paths risks introducing unbounded latencies.

### 3.3 Engine Ingestion & Normalization
The gateway normalizes metrics from disparate engine formats into standard Prometheus gauges and distribution histograms:
- `engine_kv_cache_usage_ratio`: Extracted from llama.cpp's `llama_kv_cache_usage_ratio` or slot occupancy.
- `engine_prefix_cache_hit_ratio`: Calculated from `prompt_tokens_cached / (prompt_tokens_cached + prompt_tokens_evaluated)`.
- `scheduler_queue_wait_seconds`: Collected across gateway admission queues with histogram buckets `[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]`.
- `inference_ttft_seconds`: Observed across both streaming and engine-reported observations with histogram buckets `[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0]`.
- `inference_inter_token_latency_seconds`: Observed with histogram buckets `[0.01, 0.02, 0.03, 0.04, 0.05, 0.075, 0.1, 0.15, 0.2, 0.5]`.
