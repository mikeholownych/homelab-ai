# Phase 2c deep bake-off — run notes (`20261121T073429Z`)

Host `ai-ms-s1-max-01`, ROCm 7.2.0 host driver, gfx1151 native (no `HSA_OVERRIDE_GFX_VERSION`),
rootless podman, one engine on the APU at a time. Images (digest-pinned, same as smoke):
- llama.cpp HIP: `ghcr.io/ggml-org/llama.cpp@sha256:9c44da4d33fa3e1250ec910d3af7b7acd1154baef3fe0efda53d91ae4a9f4184`
- vLLM ROCm: `docker.io/kyuz0/vllm-therock-gfx1151@sha256:f8a7433d662b37b200ca19996d4013288071341ad514e66de69ea4871cfa3966` (TRITON_ATTN)

## Pairs run (4)

| Pair | Artifact | Status |
| --- | --- | --- |
| llamacpp x coder30b (Qwen3-Coder-30B-A3B) | GGUF Q8_0 | measured |
| vllm x coder30b | HF FP8 | measured |
| llamacpp x q36_35b (Qwen3.6-35B-A3B) | GGUF UD-Q6_K (sha256 verified) | measured |
| vllm x q36_35b | HF FP8 (per-file LFS sha256 verified, rev `c653bba4`) | measured (attempt 2) |

`downloads_q36_35b.txt` (one dir up) holds the sha256-verified download log.

## Deferred (not run) and why

- **SGLang (all models):** smoke result UNAVAILABLE (4 documented start failures on ROCm 7.2 /
  gfx1151); no deep run, no scores.
- **Qwen3.6-27B, Qwen3-Coder-Next, GLM-4.7-Flash:** deferred for time. Each vLLM pair costs ~15 min
  (start + untuned-kernel decode) plus 21-45 GiB of extra downloads per artifact; the two
  completed models already give a 2-engine comparison on two model families. No
  failures were observed for these models - they were simply not attempted, so no claim is made.
  Coder-Next (45 GiB GGUF + 45 GiB third-party AWQ) and GLM-4.7-Flash (third-party AWQ) are
  the most fragile and remain open follow-ups.

## Anomaly: attempt 1 of vllm x q36_35b (kept for evidence)

`attempt1-vllm-q36_35b-reasoning-parser-null-ttft/` ran with `--reasoning-parser qwen3`. vLLM then
streams thinking under a `reasoning` delta key which `engine_sweep_client.py` (shared, unmodified)
does not read, so every TTFT was `null` and the warm-prefix row was empty. Throughput, tool
quality (4/4) and load behaviour were valid. Attempt 2 dropped the reasoning parser (thinking
then arrives in `content`, so TTFT is measured). Attempt 1 is excluded from the scorecard
(its directory has no `<engine>/<model>` nesting). Its ops row also shows `ready_within_300s`
false (314 s; first load of that FP8 checkpoint, likely cold page cache) and
`prefix_cache_effective` false (no TTFT to compare).

## Caveats that affect interpretation

- **vLLM is slow on this stack for a configuration reason, not a crash:** its logs warn
  `Using default MoE config` / `Using default W8A8 Block FP8 kernel config. Performance might
  be sub-optimal` (no tuned config for `AMD_Radeon_8060S`); Triton JIT spikes also appear during
  inference. Decode was 7-14 tok/s aggregate vs 37-74 for llama.cpp; prefill ~400 tok/s vs
  1200-1500. A tuned config could change this - the scorecard measures what ships today.
- Scorecard normalization is **per model, ratio-to-best**, so with two engines the best gets 1.0
  by construction; read the raw columns (geomean TTFT, mean tok/s) as well as the score.
- Engines serve different artifacts (GGUF vs FP8), so the score compares engine+artifact pairs.
- `ready_within_300s` depends on page cache (llama.cpp loads were 6-9 s with the GGUF already
  cached from earlier runs; `vllm x q36_35b` loaded 235 s). `gtt_used_peak_gib` is system-wide
  GTT usage from `rocm-smi`, not per-process.
- The Qwen3.6-35B FP8 download (~35 GiB) ran partly concurrently with the Coder-30B pairs;
  it can have affected model load times but not measured TTFT/throughput (GPU/HBM-bound).
- Quality = 4 tool-call contract probes (see `prompts/deep_batch_note.md`); all four pairs pass
  4/4, so quality does not discriminate here. Harder probes would be needed to separate pairs.
- vLLM `prefix_cache_effective` rests on the warm speedup (2.1x-5.9x); vLLM did not report
  `cached_tokens`.
