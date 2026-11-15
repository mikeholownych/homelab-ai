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
