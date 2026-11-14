# SYCL inference optimization investigation — ai-5820-01

Branch `research/sycl-optimization`. Window 1 run 2026-11-14. Status: **research success on one candidate; production deployment NOT done.**
Host was restored to the original validated configuration (gateway ready, 2/2 workers, pinned image `sha256:2f494061…`, reconcile timer re-enabled).

## Headline

Upstream llama.cpp HEAD `a956a852c9c8bc1fb07206364838ddef299178c0` (2026-11-14) built unmodified with the official `.devops/intel.Dockerfile`
(oneAPI 2026.2.0) beats the deployed build `b11347` (`5fc4f3c8c`) on Qwen3.6-35B-A3B Q4_K_M, GPU 0, with unchanged model hash and flags:

| llama-bench (5 reps) | deployed b11347 | HEAD a956a852 | change |
|---|---|---|---|
| pp512 t/s | 815 ± 18 | 1399 ± 8 | +72% |
| pp2048 t/s | 1335 ± 6 | 1801 ± 2 | +35% |
| pp8192 t/s | 1299 ± 13 | 1778 ± 2 | +37% |
| tg128 t/s | 62.2 ± 0.8 | 81.2 ± 1.4 | +30% |

Correctness (KL divergence vs CPU ground truth, same model, 3 chunks x 2048): HEAD 0.0046 / deployed 0.0047 at n_seq=1 (equivalent).
At n_seq=2 (`-b 4096`) the **deployed build is wrong (KLD 0.338, same-top-token 82%)** while HEAD stays correct (0.0047, 96.6%).
Production uses `-np 1`, so it does not hit that bug today; it matters for any concurrent-slot configuration.

Task accuracy (engx base corpus, 12 tasks x 2 reps, production flags, reasoning budget 8192): HEAD 23/24, deployed 22/24
(failures: HEAD T10; deployed T07, T10). No regression; n is too small to claim improvement. Wall time 1884 s vs 2865 s.

## Decision matrix

| Optimization | Target | Accuracy | Performance | Stability | Integration cost | Decision |
|---|---|---|---|---|---|---|
| Upstream HEAD build (grouped XMX MoE GEMM #29245, MoE scheduler #30156, DPAS FA, graphs) | Qwen3.6-35B-A3B / GPU0 | PASS (KLD, engx) | PASS (+30..72%, 5 reps) | NOT TESTED | Low-medium: new pinned image, no patches | **EXPERIMENT FURTHER** (adopt after remaining gates) |
| Same build on worker 2 model (Qwen3.8-Flash-Next IQ1_M) | GPU1 | NOT TESTED | NOT TESTED | NOT TESTED | - | EXPERIMENT FURTHER (IQ1_M has no reorder kernel) |
| da3dsoul MoE-cache patch | MoE expert cache | - | author reports tie with `-ncmoe` | - | 68 conflicts vs HEAD, **no licence** | REJECT |
| Raudbjorn fork | A770 | - | no Battlemage data; AOT list omits bmg-g31 | - | merge base 1500 commits old | REJECT (ideas already upstream) |
| snailium b70 | build/config reference | - | unverified on 2 GPUs/MoE | - | no code changes | MONITOR UPSTREAM |
| intel/ipex-llm | - | - | - | archived 2026-01 | - | REJECT |
| Strata-Void | different engine | - | unproven | - | unpinned base image | REJECT |
| Fused MoE gate/up for MUL_MAT_ID, IQ1_M reorder | - | - | - | - | upstream gap | EXPERIMENT FURTHER |
| Hot/cold expert cache, offload (`-ncmoe`) | larger MoE | NOT TESTED | NOT TESTED | - | - | NOT TESTED |
| KV quant, 4K-64K context, prefix reuse | both | NOT TESTED | NOT TESTED | - | - | NOT TESTED |
| Multi-GPU (tensor/layer split) | both | NOT TESTED | NOT TESTED | - | - | NOT TESTED |
| Reliability/failure injection | HEAD | - | - | NOT TESTED | - | NOT TESTED |

## Acceptance gates for the HEAD build

Compatibility PASS (reproducible build, loads, runs on both-GPU host) · Correctness PASS on tested scope · Performance PASS (repeated, beyond variance) ·
Reliability NOT TESTED · Operations NOT TESTED (no Ansible/gateway integration, no rollback test of a new image) · Maintainability: pin by SHA; image built
from an unmodified upstream commit, so patch boundary is empty.

## Limits and honesty notes

- Throughput numbers are llama-bench microbenchmarks plus engx wall time; gateway-level TTFT/ITL/concurrency not measured.
- Baseline and candidate ran at different times with worker 2 serving on GPU 1 in both; no randomized ordering. Cold/warm JIT effects not separated.
- Candidate image reports `build_commit: unknown` (APP_REVISION not embedded); provenance is the image label + pinned SHA + digest in `evidence/build/`.
- Perplexity (15.5 base corpus) is on repo docs/code text, not a standard benchmark; used only for relative KL.
- Independence: all verification was executed by the same agent; the CPU ground truth and the self-comparison control are the independent checks. No separate reviewer ran.
- `--reasoning-budget-message` omitted in both research arms (identical); `-np 1 -fa on -b 4096 -ub 2048 -c 65536` match production.
- Qwen3-Coder-30B-A3B (brief's Workstream A target) is not deployed or on the host; Qwen3.6-35B-A3B was used.

## Incident / operations notes

- The workstation timer `aihost-reconcile.timer` (hourly ~:03) restarts stopped workers; it was paused during the window (`harness/pause_reconcile.sh`) and re-enabled by `harness/restore_baseline.sh`.
- Research servers use ports 18100+ (outside the nftables worker port sets); production policy and unit files were never modified.
- The gateway-only rule suspension ended with this window; no unregistered servers remain.

## Next window (proposed order)

1. HEAD on Qwen3.8-Flash-Next IQ1_M (GPU1): KLD vs CPU, engx, bench.
2. Long context 16K/32K/64K retrieval + KV quant (q8_0) on HEAD, both models.
3. Concurrency (`-np 2`) now that HEAD is correct at n_seq=2; also confirm and report the b11347 multi-sequence bug upstream.
4. Reliability set (crash/restart, cancel, VRAM exhaustion bounded), then Ansible image-pin change + rollback test, then deploy.

Harness: `harness/` (restore_baseline.sh, pause_reconcile.sh, research_run.sh, kl_gate.sh, kl_score.sh, kl_cpu_reference.sh, kl_cpu_batch_probe.sh, engx_ab.sh).
Evidence: `evidence/` (raw JSONL, KL outputs, engx results, audits, build log, model SHA-256).
