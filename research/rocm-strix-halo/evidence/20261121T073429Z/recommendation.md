# Strix Halo engine×model recommendation (`ai-ms-s1-max-01`)

Status: **recommendation only. Lab wire is next; production promotion is deferred.**
Operator acceptance is required before any wire work starts (Task 7).

Host: `ai-ms-s1-max-01` (lab), ROCm 7.2.0 host driver, gfx1151 native (no
`HSA_OVERRIDE_GFX_VERSION`), rootless podman, one engine on the APU at a time.

Evidence:
- Deep run: `deep/scorecard.md`, `deep/NOTES.md`, per-pair `deep/<engine>/<model>/{metrics.jsonl,ops.json,run_cmd.txt}`
- Smoke: `../20261121T065325Z/smoke/SUMMARY.md`, `../20261121T065325Z/smoke/sglang/UNAVAILABLE.md`

## Primary winner

```yaml
engine: llama.cpp HIP (ghcr.io/ggml-org/llama.cpp, tag server-rocm, build b12464)
model: Qwen3-Coder-30B-A3B-Instruct
quant: GGUF Q8_0   # unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF @ b17cb02dd882d5b6ab62fc777ad2995f19668350
                   # sha256 4ff1cff607804037bf6d2168249c570baa4e1621292b159c0e06591e0d7c3066
image_digest_or_sha: ghcr.io/ggml-org/llama.cpp@sha256:9c44da4d33fa3e1250ec910d3af7b7acd1154baef3fe0efda53d91ae4a9f4184
listen_port: 8101   # port used in the bake-off (127.0.0.1); the lab wire may rebind it
```

Measured launch args (from `deep/llamacpp/coder30b/run_cmd.txt`):
`-m …Qwen3-Coder-30B-A3B-Instruct-Q8_0.gguf -ngl 99 -fa on --jinja --host 127.0.0.1 --port 8101 -c 65536 -np 4`.
Device flags: `--device=/dev/kfd --device=/dev/dri --group-add keep-groups --net=host`.

### Why Coder-30B Q8_0 over Qwen3.6-35B UD-Q6_K

The scorecard cannot separate the two (both 1.000, because normalization is per model and
all quality probes pass 4/4). The choice rests on raw llama.cpp metrics, for an interactive
coding agent that resends a growing, mostly identical prefix every turn:

| Raw metric (llama.cpp HIP) | Coder-30B Q8_0 | Qwen3.6-35B UD-Q6_K |
| --- | --- | --- |
| Warm-prefix TTFT (~1.86k prompt tokens) | **0.069 s** (1853 cached, 20.6x) | 0.420 s (1346 cached, 3.1x) |
| Cold TTFT 2k / 8k prompt | 1.47 s / 6.57 s | **1.34 s / 5.31 s** |
| Decode, aggregate tok/s c=1 / c=2 / c=4 | 37.2 / 48.3 / 56.9 | 37.7 / **55.5** / **73.8** |
| Peak GTT (of 61.35 GiB) | 36.3 GiB | **28.7 GiB** |
| Ready time | 6 s | 9 s |

Reasoning:
- Agent turns are mostly warm. Coder-30B reuses nearly the whole prefix (99.5%) and answers
  in 69 ms. Qwen3.6 reuses only 72% of the same prompt and takes about 6x longer. I did not
  find the cause in the logs. The likely explanation is its hybrid linear-attention state
  limiting prefix reuse, but that is an inference.
- Single-stream decode is a tie (37.2 vs 37.7 tok/s), so the Qwen3.6 advantages (about
  20% faster cold prefill, +30% at c=4, 7.6 GiB less GTT) matter mainly for several
  concurrent sessions or very long cold prompts, which is not the primary target.
- Q8_0 is a higher-fidelity quant than UD-Q6_K, and Coder-30B is a non-thinking instruct
  model built for coding and tool calling. Both hold 25+ GiB GTT headroom, well above the 8 GiB gate.

Caveats: warm TTFT is a single sample per pair. Quality probes (4 tool-call contracts)
do not discriminate. Qwen3.6 thinking-mode latency was not measured. Revisit if lab use
shows multi-session concurrency dominating.

## Runner-up

```yaml
engine: llama.cpp HIP (same pinned image digest as above)
model: Qwen3.6-35B-A3B
quant: GGUF UD-Q6_K   # unsloth/Qwen3.6-35B-A3B-GGUF @ a483e9e6cbd595906af30beda3187c2663a1118c
                      # sha256 4fe53b148b46f9b88830e2a3055c5b15c3a4d1e3ddc9a1384a108d8b9d59f043
image_digest_or_sha: ghcr.io/ggml-org/llama.cpp@sha256:9c44da4d33fa3e1250ec910d3af7b7acd1154baef3fe0efda53d91ae4a9f4184
listen_port: 8101
```

Pick it instead if the lab needs higher concurrent throughput (73.8 vs 56.9 tok/s at c=4),
a lower memory footprint, or faster cold long-prompt prefill. Same launch args as the
primary, with the model path and alias swapped.

## Scorecard summary

Weights: quality 0.30, TTFT 0.30, tok/s 0.20, ops 0.20. TTFT and tok/s are normalized per
model (ratio-to-best), so the best engine on each model scores 1.0 by construction.
Engines serve different artifacts (GGUF vs FP8), so the score compares engine+artifact pairs.

| engine | model (artifact) | score | quality | TTFT geomean s | mean agg tok/s | cold TTFT 8k s | peak GTT GiB | ready s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| llama.cpp HIP | Coder-30B (GGUF Q8_0) | 1.000 | 4/4 | 0.87 | 47.5 | 6.57 | 36.3 | 6 |
| vLLM ROCm | Coder-30B (FP8) | 0.597 | 4/4 | 4.24 | 8.3 | 20.87 | 43.1 | 103 |
| llama.cpp HIP | Qwen3.6-35B (GGUF UD-Q6_K) | 1.000 | 4/4 | 1.44 | 55.7 | 5.31 | 28.7 | 9 |
| vLLM ROCm | Qwen3.6-35B (FP8) | 0.613 | 4/4 | 5.98 | 11.2 | 19.10 | 48.2 | 235 |

llama.cpp HIP beats vLLM on both models by about 5x on throughput (47.5 vs 8.3, 55.7 vs 11.2 tok/s),
about 3-5x on TTFT, and about 3x on prefill (~1200-1500 vs ~400 tok/s). All four pairs
passed the 7-item ops checklist.

vLLM image: `docker.io/kyuz0/vllm-therock-gfx1151@sha256:f8a7433d662b37b200ca19996d4013288071341ad514e66de69ea4871cfa3966`
(`TRITON_ATTN`, port 8102). Its logs warn that no tuned MoE/FP8 kernel config exists for
`AMD_Radeon_8060S` and Triton JIT spikes appear, so the gap reflects what ships today and a
tuned config could narrow it. vLLM is not recommended on the current stack.

## Engines unavailable or failed

- **SGLang: unavailable** on gfx1151 / ROCm 7.2.0 (image
  `docker.io/lmsysorg/sglang@sha256:a3a6eb293187b20012a5abc8f00423e6ab51d0169113a6e58a91da5614200170`,
  `v0.5.23-rocm720-mi30x`). The image's native kernels (`aiter`, `sgl_kernel`) are built for
  gfx942 only, and no gfx1151 SGLang image exists. Four attempts failed: KV-pool OOM from
  the over-sized pool estimate, aiter JIT build failure (`cvt_pk_fp8_f32` needs `fp8-conversion-insts`),
  an aiter bf16 GEMM segfault, and an `sgl_kernel.rotary_embedding` segfault. No numbers exist
  and none are implied. Details: `../20261121T065325Z/smoke/sglang/UNAVAILABLE.md`.
  Reconsidering it would need a gfx1151 source build of `aiter`/`sgl_kernel` or a newer host ROCm.
- vLLM did not fail. It ran on both models but is much slower (see above).
- vLLM `q36_35b` attempt 1 (`--reasoning-parser qwen3`) is excluded from scoring because the
  shared client reads no `reasoning` deltas, so TTFT was null. Evidence is kept in
  `deep/attempt1-vllm-q36_35b-reasoning-parser-null-ttft/`.

## Deferred deep models

Not run, for time. No failures were observed, so no claim is made about them:
- Qwen3.6-27B (GGUF Q6_K / FP8)
- Qwen3-Coder-Next 80B-A3B (GGUF Q4_K_M / third-party AWQ). It is the most fragile and a large download (~45 GiB per artifact).
- GLM-4.7-Flash (GGUF Q6_K / third-party AWQ). Third-party AWQ and MLA/KV-size risk.

They remain open follow-ups. Since llama.cpp HIP is the clear engine, a llama.cpp-only
sweep of these GGUFs would be cheap, because no vLLM pair is needed.

## Next step

1. **Operator acceptance** of this recommendation (or choice of the runner-up).
2. **Lab wire next (Task 7):** deploy the accepted engine×model to the lab host via
   Ansible, using the pinned digest above.
3. **Production promotion is deferred.** Nothing here touches `inventory/production`.
   Promotion needs a separate decision after lab soak.
