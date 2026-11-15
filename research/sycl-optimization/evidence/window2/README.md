# Window 2 (2026-11-15) — Qwen3.8-Flash-Next IQ1_M on GPU 1, deployed b11347 vs HEAD a956a852

llama-bench (-ngl 99 -fa 1 -b 4096 -ub 2048, 5 reps):
| test | base t/s | HEAD t/s | change |
|---|---|---|---|
| pp512 | 434.6 ± 2.0 | ~595 (reps 2-5; rep 1 = 44.6 warm-up outlier, mean 484 ± 246) | +37% |
| pp2048 | 677.5 ± 4.7 | 740.1 ± 3.5 | +9% |
| pp8192 | 666.6 ± 3.4 | 721.1 ± 2.5 | +8% |
| tg128 | 19.5 | 23.0 | +18% |

CPU ground-truth KL (3 chunks x 2048, n_seq=1): base KLD 0.0153 (93.06% same top), HEAD KLD 0.0159 (93.29%) — equivalent within error.
Note: first-rep pp512 outlier on HEAD is one-time JIT/warm-up (44.6 t/s); production sees it once per server start.
Correction to window 1: Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf IS on the host (/var/lib/local-ai/models/gguf); it is the brief's primary target and is still to be benchmarked.

## Qwen3-Coder-30B-A3B-Instruct-Q4_K_M on GPU 0 (llama-bench, -fa 1 -b 4096 -ub 2048, 3 reps)
| test | base t/s | HEAD t/s | change |
|---|---|---|---|
| pp512 | 1026.8 | 1305.8 | +27% |
| pp2048 | 1596.5 | 1472.0 | **-8%** |
| pp8192 | 1477.7 | 1282.6 | **-13%** (re-run interleaved x2: 1481 vs 1298, confirmed) |
| pp32768 | 1022.7 | 829.6 | **-19%** |
| tg128 | 92.9 | 99.7 | +7% |
KV q8_0: pp2048 1587→1421 (-10%), pp32768 1015→822 (-19%), tg128 83.6→89.8 (+7%).
Toggles tried on HEAD at pp8192 (no effect, 1287-1303): GGML_SYCL_ENABLE_MKL_FA=0, ENABLE_XMX_ESIMD=1, ENABLE_GRAPH=1.
CPU-truth KL (3 chunks): base KLD 0.00563 (95.18% same top), HEAD 0.00614 (95.18%) — equivalent.

**Finding:** HEAD is NOT uniformly faster. On the brief's primary target (qwen3moe arch) it regresses prefill for prompts >=2K
tokens by 8-19%, the regime agentic coding lives in. Qwen3.6-35B (qwen35moe) and Flash-Next gain. Cause unidentified
(candidates: grouped-MoE prefill path for qwen3moe, or oneAPI 2026.2 vs 2026.1); a bisect is needed before any deployment.
