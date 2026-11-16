# Benchmark results (windows 1-2, 2026-11-14/15)

Raw data, scripts and per-step notes: `evidence/window1/`, `evidence/window2/README.md`, `evidence/correctness/`. All numbers are llama-bench on the host's own GPUs
(B65, one model per GPU, -fa 1 -b 4096 -ub 2048), 3-5 reps unless noted; t/s. Deployed = pinned production image b11347 (IGC 2.34.4 / NEO 26.18 era stack).
Nothing here was measured through the gateway (see "Not tested").

## Candidate: HEAD source (a956a852) + current oneDNN + old IGC/NEO pair (`head-stackB`), GPU_SYCL_ENABLE_XMX_ESIMD=0
| model (GPU) | pp512 | pp2048 | pp8192 | pp32768 | tg128 | KLD vs CPU | deployed KLD |
|---|---|---|---|---|---|---|---|
| Qwen3.6-35B-A3B Q4_K_M (0): candidate | 1413.6 | 1818.6 | 1811.6 | 1674.3 | 75.0 | 0.004700 | 0.0047 |
| Qwen3.6 deployed | 815 | 1335 | 1299 | n/a | 62.2 | | |
| Qwen3-Coder-30B-A3B Q4_K_M (0): candidate | 1333.6 | 1730.3 | 1580.2 | 1079.3 | 92.1 | 0.005617 | 0.00563 |
| Coder deployed | 1027 | 1597 | 1478 | 1023 | 92.9 | | |
| Qwen3.8-Flash-Next IQ1_M (1): candidate | 596.4 | 716.2 | 696.2 | n/a | 19.2 | 0.015054 | 0.0153 |
| Flash-Next deployed | 434.6 | 677.5 | 666.6 | n/a | 19.5 | | |

## What drives the result (findings)
1. The newer llama.cpp source is faster on Qwen3.6 and Flash-Next, and on Coder-30B once `GGML_SYCL_ENABLE_XMX_ESIMD=0` (upstream issue #31068, maintainer-confirmed workaround).
2. The upstream image's newer IGC 2.42.6 + NEO 26.40 stack costs Coder-30B about 15% at 32K prefill. oneDNN is not the cause. Source commits are not the cause (revert of #30156 changed nothing).
3. The new stack decodes about 7-8% faster than the old pair, so the choice is workload dependent (agent sessions: long prefill, short decode).
4. Accuracy: KL against a CPU reference is equivalent for deployed, HEAD and candidate on all three models. The deployed b11347 has a latent multi-sequence batch bug at `-b 4096` with 2 sequences (KLD 0.338) that `-np 1` avoids.
5. engx (Qwen3.6): HEAD 23/24 vs deployed 22/24, no truncations; Coder and Flash-Next engx not run.

## Not tested (do not infer from this document)
Gateway-level TTFT/latency, `-np 2` concurrency, multi-GPU, long-context retrieval and KV quantisation, reliability and failure injection, expert cache, an independent reviewer, engx on Coder/Flash-Next, the Ansible image pin and rollback, soak/duration runs.
