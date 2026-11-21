# Phase 2c deep bake-off — prompt and batch note

What each engine x model pair is asked to do (identical for every pair; produced
by `harness/run_deep_bakeoff.sh`).

| Step | Tool | Request shape |
| --- | --- | --- |
| Warmup (discarded) | `engine_sweep_client.py longctx` | 512 / 2048 / 8192-token synthetic prompts, 16 tokens out (JIT/compile at measured shapes) |
| Cold TTFT | `engine_sweep_client.py longctx` | 2048 and 8192 target tokens, random nonce prefix per request (no prefix-cache hit), 16 tokens out |
| Batch decode | `engine_sweep_client.py batch` | c = 1, 2, 4 concurrent streams, ~1.2k-token prompt each (nonce prefix), 128 tokens out, `2 x c` requests per level; metric = aggregate completion tok/s |
| Warm TTFT | `deep_probe.py warm` | One fixed ~2k-token prefix, sent twice with a different short tail; the 2nd request's TTFT is recorded (`cached_tokens` and speedup kept) |
| Quality | `deep_probe.py quality` | 4 OpenAI `tools` contract probes, `temperature 0`, `max_tokens 2048`: `echo_exact`, `typed_args` (string + integer + enum), `select_tool` (pick 1 of 3), `optional_int` (optional integer arg). Pass = right tool name **and** argument keys/types/values; anything else (no tool call, wrong tool, bad JSON, HTTP error) = fail |
| Ops | `run_deep_bakeoff.sh` | 7-item checklist from the run's own evidence (see below) |

TTFT counts the first `content` **or** `reasoning_content` delta, so thinking models
are not penalised for streaming reasoning first.

## Ops checklist (7 items, each pass/fail)

`ready_within_300s`, `tool_calls_supported`, `stream_usage_reported`,
`prefix_cache_effective` (cached tokens reported or warm speedup >= 1.5x),
`stable_no_oom_or_crash` (container still up, no OOM / segfault in its log),
`gtt_headroom_ge_8GiB` (peak GTT used leaves >= 8 GiB of the 61.35 GiB pool),
`digest_pinned_no_hsa_override`.

## Engine configuration (per pair)

- llama.cpp HIP: `-ngl 99 -fa on --jinja -np 4 -c 65536` (4 slots x 16384).
- vLLM ROCm: `--attention-backend TRITON_ATTN --enable-prefix-caching
  --max-model-len 16384 --enable-auto-tool-choice`; `--gpu-memory-utilization`
  0.7 (Coder-30B FP8) / 0.8 (Qwen3.6-35B FP8).
- No `HSA_OVERRIDE_GFX_VERSION`. One engine on the APU at a time (ports 8101 / 8102).
- SGLang is **not** run: smoke result UNAVAILABLE (see smoke evidence); no scores
  are fabricated for it.

## Comparison caveat

llama.cpp runs a GGUF quant (Q8_0 / UD-Q6_K) and vLLM an FP8 safetensors
checkpoint of the same model, so a pair score compares *engine + artifact*. The
scorecard normalizes TTFT and tok/s per model (ratio to the best engine on that
model); quality and ops are absolute fractions.
