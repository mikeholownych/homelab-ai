# llama.cpp metrics -> gateway -> vllm-top vocabulary (backlog 626)

The mapping already exists in code: `orchestrator_runtime/engine_stats.py` scrapes each worker's `/metrics` and the gateway
re-exports the values as `aihost_engine_*` (`health.py` `_ENGINE_METRICS`, `metrics.py`). vllm-top reads `vllm:*` names
(`vllm-top/src/metrics.rs`) and detects llama.cpp only by the `llamacpp:` prefix (`discover.rs`), so it shows no engine
numbers for a llama.cpp worker directly. The bridge is the gateway: vllm-top's `Gateway` source kind (`config.rs`, `orchestrator.rs`) reads
each worker's republished `engine_stats` from the gateway's `/health` (engine-agnostic, no worker credential), so llama.cpp workers do get an engine panel.

| vllm-top / vLLM name | llama.cpp source | Gateway export | Status |
|---|---|---|---|
| `num_requests_running` | `llamacpp:requests_processing` | `aihost_engine_requests_running` | mapped |
| `num_requests_waiting` | `llamacpp:requests_deferred` | `aihost_engine_requests_waiting` | mapped |
| `kv_cache_usage_perc` | `llamacpp:kv_cache_usage_ratio` | `aihost_engine_kv_cache_usage_ratio` | mapped (ratio, not percent) |
| `prompt_tokens_total` | `llamacpp:prompt_tokens_total` (excludes cached) | `aihost_engine_prompt_tokens_total` | mapped |
| `generation_tokens_total` | `llamacpp:tokens_predicted_total` | `aihost_engine_generation_tokens_total` | mapped |
| prefix cache queries/hits | `llamacpp:prompt_tokens_cached_total` | `aihost_engine_prompt_tokens_cached_total`, `aihost_engine_prefix_cache_hit_ratio` | mapped, derived ratio |
| prefill / decode time | `prompt_seconds_total`, `tokens_predicted_seconds_total` | `aihost_engine_prompt_seconds_total`, `aihost_engine_generation_seconds_total` | mapped (rates give tok/s) |
| `time_to_first_token_seconds` | none (counters only, no histograms) | none | derive client-side |
| `request_queue_time_seconds` | none | none | derive from deferred gauge + client timing |
| `inter_token_latency_seconds` | none | none | derive client-side from the stream |
| `e2e_request_latency_seconds` | none | `aihost_inference_duration_seconds` (gateway wall time, includes engine queueing) | gateway-side only |

## Deriving the missing latencies client-side
- **TTFT:** time from request send to the first content delta of a streamed response (`controlled_probe.py` records
  `ttft_seconds`; `run_benchmark.py` records raw token arrival times). Prefill-bound, so it includes any queue wait.
- **Queue time:** not exposed by llama.cpp. Observe `requests_deferred > 0` for the worker while a request is in flight, or subtract the
  worker's `prompt_seconds_total` delta for the request from its TTFT; with `-np 1` anything above that is queueing.
- **ITL / TPOT:** differences between successive streamed chunk arrival times; TPOT = (e2e - TTFT) / (completion_tokens - 1).
  Streaming chunks are not guaranteed one token each, so report the percentile of chunk gaps and the tokens-per-chunk count.
- Gateway `aihost_inference_duration_seconds` is not TTFT; it is full worker-call wall time.

Correction (2026-11-17): an earlier version of this file listed a "vllm-top has no engine panel for llama.cpp" gap. That was wrong: the
`Gateway` source above already provides it. The remaining limit is that llama.cpp exposes no latency histograms, so TTFT, queue time and ITL
stay client-derived (section above).
