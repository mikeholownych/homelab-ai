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
   Additions from the LocalAI review (docs/source read 2026-11-15; not run):
   - 4a. Reliability: model a **busy-watchdog** on the worker/gateway path. A hang is detected by the age of the *oldest in-flight request* (not total traffic),
     so overlapping load cannot mask a stuck backend. Test cancel + graceful stop (bounded ~30 s wait, forced kill only as a second step) against the HEAD image.
   - 4b. Operations: mirror LocalAI's pin pattern. One variable for the llama.cpp commit, base images pinned by digest, a minimal patch queue (empty today),
     APP_REVISION embedded in every image. Record the pin in the Ansible vars alongside the rollback target.
   - 4c. Reliability: with SYCL, LocalAI's docs report a **hang with `mmap: true`**. Our workers use llama.cpp's default mmap setting and have not hung;
     check model load/reload under failure injection on HEAD with default mmap and with `--no-mmap`.
   - 4d. Only if a worker ever serves more than one model: adopt per-model anti-affinity (concurrency groups) and pinned models. Not needed for one model per GPU.
   - 4e. Only if a MoE model larger than VRAM is introduced: evaluate upstream `--moe-cache-size` (field `moe_cache_size`, present in HEAD). Not needed now (both models fit).
   - 4f. If prompt/slot state is ever persisted: treat as private data (random IDs, per-model manifest, size/entry caps, no client-supplied paths).
   Additions from the colibri review (README read 2026-11-15; engine not run, claims unverified):
   - 4g. Operations: automate the correctness gate so any image bump fails a check. A tiny fixed prompt set scored by KL against a CPU reference, run in CI or as an Ansible pre-deploy step,
     with the same pass thresholds we used (KLD within noise of the deployed build, same-top-token not lower). Today the gate is a manual harness run.
   - 4h. Performance/agents: test slot reuse across an interleaved short request. On a `-np 1` worker, send a long (~15K token) agent turn, then a short unrelated request
     (e.g. a title generation), then the next long turn, and measure time-to-first-token for the third request on the deployed build and on HEAD, with `--cache-ram` default and
     with `--cache-ram` raised. Both flags exist in both builds; the behaviour on our workload is unmeasured. Run through the gateway.
   - 4i. Performance (candidate, not a result): MTP speculative decoding. llama.cpp supports MTP drafting in both builds but our worker flags do not use it, and the header region of both
     production GGUFs shows no `nextn`/`mtp` tensor names, so a separate MTP-capable model file would be needed. Check upstream and model sources for an MTP-bearing GGUF of each model
     before any test; accept only if output matches (greedy-equal) and decode speedup repeats beyond variance.
   Additions from the AnythingLLM review (README + router/monitor source read 2026-11-15; not run):
   - 4j. Performance/agents: check route stickiness. Confirm whether the gateway sends follow-up turns of one conversation to the same worker. Each worker holds its own prompt/KV state,
     so bouncing a conversation between workers discards a warm prefix. If it does bounce, measure TTFT with and without a short sticky window (AnythingLLM uses 5 min) before changing anything.
   - 4k. Evidence: record per-request prompt tokens, completion tokens, output tokens/s, duration and a truncated flag (stopped at the output limit) in gateway-level benchmarks.
     Already verified for engx window 1: all 62 recorded attempts across both arms finished with `stop`, so truncation did not cause the T07/T10 failures.
   - 4l. Performance (hypothesis only): reducing tool-definition tokens per request (expose only relevant tools). AnythingLLM claims up to 80% fewer tokens; the claim is unverified and
     not from our workloads. Measure how many prompt tokens Nexus Code's tool definitions use per turn first; if material, A/B a reduced set for task accuracy and prefill time.
   Additions from the Ollama review (docs and source read 2026-11-15; not run):
   - 4m. Operations: image-bump checklist, extending 4b. Before any bump, review the upstream diff for the paths we use (SYCL backend, MoE, flash attention, model loader, server), build and
     inspect the exact source that goes into the image, then run the full gate (KL vs CPU, per-model prefill/decode A/B at 2K/8K/32K, reliability set). Ollama's guide notes a bump can change loading,
     GPU discovery, scheduling inputs, logs and streaming; our Coder-30B regression is the same class of surprise.
   - 4n. Maintainability: any carried patch must be additive, tied to an upstream PR, and have a written removal condition. Ollama's compat patch broke on an upstream file rename (clip.cpp -> mtmd-model.cpp, b12257).
     Our patch queue is empty today; keep it empty unless the Coder-30B fix requires otherwise.
   - 4o. Reliability: confirm gateway behaviour under saturation (bounded queue, explicit 503/overload response, queue-depth metric; Ollama defaults to 512 queued then 503) and that a killed or crashed worker
     leaves a usable last-error in gateway evidence (Ollama captures the runner's last stderr, capped at 8 KB). Add both to the failure-injection set.
   - 4p. Performance (hypothesis): A/B upstream llama.cpp's Vulkan backend against SYCL on the B65 for Coder-30B, Qwen3.6 and Flash-Next (prefill 2K/8K/32K, decode), using the same KL gate.
     Ollama ships Vulkan for Intel by default and has no SYCL build, so its results say nothing about SYCL, but Vulkan may not share the Coder-30B prefill regression. Needs a Vulkan-enabled image build.
   Additions from the vLLM review (docs read 2026-11-15; not run; llama.cpp metric and flag names checked in our sources at 5fc4f3c8 and a956a852):
   - 4q. Evidence: gateway-level latency benchmark. Run a client-side load tool (`vllm bench serve` or GuideLLM) from a client machine against the gateway with an operator-issued key; never from the host
     and never by reading production keys. Fixed seed, request-rate and concurrency sweeps, report TTFT, time per output token and inter-token latency (mean, median, p99), on the deployed build and each candidate.
     Prompt shapes taken from Nexus Code (short, 2K, 8K, 32K). This closes the open "gateway TTFT/ITL" gap.
   - 4r. Evidence: metrics mapping. llama.cpp exposes tokens cached, prompt/predicted tokens and seconds, processing and deferred requests, and speculative-decoding counters; it has no TTFT histogram,
     queue time or KV-usage metric. Derive TTFT and queue time client-side, derive cache-hit ratio as cached prompt tokens over total prompt tokens, and note the mapping for `vllm-top`.
   - 4s. Performance/agents: split the slot-reuse test (4h) by architecture. Run it separately for Coder-30B (full attention) and for Qwen3.6 and Flash-Next (hybrid, checkpoint-based reuse via `--ctx-checkpoints`),
     since hybrid models can only reuse prefixes at saved checkpoints.
   - 4t. Performance (engine comparison, hypothesis): vLLM XPU lists Arc Pro B-Series as validated hardware and Qwen3-Coder-30B-A3B as supported (BF16/online FP8; GPTQ-Int4 checkpoint exists); the host already has
     `vllm/vllm-openai-xpu:v0.29.0`. Check whether it loads and serves Coder-30B on one B65 within 32 GB, then compare latency and engx task accuracy. Weights differ from our GGUF, so the KL gate does not apply;
     label it an engine comparison, not a kernel comparison, and run it through the same bench as 4q.
   Additions from the SGLang review (docs read 2026-11-15; not run):
   - 4u. Reliability: gateway failure semantics, extending 4o. Define and test expected behaviour for a hung or crashed worker and for saturation, using SGLang's router as a reference point:
     per-worker circuit breaker (open after ~5 failures, close after ~2 successes, ~30 s timeout, ~60 s window), bounded FIFO queue with 429 when full and 408 on queue timeout, health checks
     (~30 s interval, 3 failures to mark unhealthy), retries with jitter. Record what our gateway actually does against each, and fix or document gaps. Thresholds are starting points, not targets.
   - 4v. Performance/agents: extend 4s with checkpoint behaviour. For Qwen3.6 and Flash-Next, record whether a request-end checkpoint is kept on a `-np 1` worker (`--ctx-checkpoints`, `--checkpoint-min-step`)
     and measure continuation TTFT when the next turn extends the previous full context versus when it forks mid-prompt. SGLang reports 0.96-0.99 continuation hit rates on agent traces for comparable hybrids
     with checkpoints at divergence and request end; unverified for llama.cpp.
   - 4w. Evidence: realistic load. Extend 4q with trace replay. Replay recorded, sanitised Nexus Code sessions (kept local, no external upload) through the gateway instead of only synthetic prompt sizes,
     and report cache-hit ratio (cached over total prompt tokens), TTFT and total time for the session.
   - 4x. Performance: prompt-cache capacity under context pressure. Measure how many 64K-context conversations the `--cache-ram` default (8192 MiB) retains, and whether an idle conversation can evict one
     that is actively in use. If it can, test raising `--cache-ram` against host RAM headroom (host has 61 GiB shared with both workers).
   - 4y. Engine comparison candidate, extending 4t: SGLang XPU (Arc / Arc Pro B-Series, `intel_xpu` attention backend, native MXFP4 MoE). Same caveats as vLLM: different weights, Python/PyTorch/Triton stack,
     no KL gate; compare on engx accuracy plus latency only, and only after 4t's feasibility check.
   - 4z. Process: add "search upstream issues and PRs first" to the image-bump checklist (4m). Our Coder-30B prefill regression was already reported upstream as #31068 with a documented workaround; search by symptom and backend before spending bisect time.
   - 4aa. Performance: per-op env switches. Upstream gives each SYCL optimisation its own env toggle (e.g. `GGML_SYCL_ENABLE_XMX_ESIMD=0`, `GGML_SYCL_XMX_MAX_COLS=0`). Test a per-worker environment: ESIMD=0 for the Coder worker only, since Qwen3.6 is unaffected. Cover Qwen3.6 and Flash-Next too, applied through Ansible with a rollback.
   - 4ab. Correctness: run `tests/test-backend-ops` (per-op backend-vs-CPU comparison, with a perf mode) on a build with tests enabled. Our images build with tests off, so use a separate research build. Include MUL_MAT_ID and flash attention, and use it to localise the 32K residual.
   - 4ac. Correctness gate: F16 NaN on dense Qwen3.8-27B since #29107 (open #30892); the official Dockerfile defaults `GGML_SYCL_F16=ON`. Any bump gate must include a dense-model sanity check or an explicit F16 note, since our deployed MoEs would not catch it.
   - 4ad. Operations: HEAD adds server router mode and sleep-idle flags. Unverified in b11347; read the HEAD `--help` and test only after the image-pin and rollback work. Not a reason to bump by itself.

   - 4ae. Process (from window 2): the runtime stack bundled in the image (oneDNN, IGC, NEO compute runtime, IGDGMM, Level Zero) is a separate variable from the llama.cpp commit. On HEAD, the stack from upstream commit d5bbcd1f3 (IGC 2.42.6 + NEO 26.40) cuts Coder-30B pp32768 by about 15% against the old pair (IGC 2.34.4 + NEO 26.18); oneDNN is not the cause. Every image bump records the stack versions, benchmarks old and new stack with the same source, and pins the stack explicitly (a Dockerfile override) instead of inheriting upstream's default.
   - 4af. Candidate image for the Coder worker: HEAD source + current oneDNN + old IGC/NEO pair (`head-stackB`). Before any deploy it needs the full gate on every model it would serve (Qwen3.6, Flash-Next, Coder): KL vs CPU truth, pp/tg bench, engx, plus Ansible image pin and rollback.
   - 4ag. Upstream report: IGC 2.42.6 + NEO 26.40 slow long-context (32K) MoE prefill on BMG-G31 (Arc Pro B65) in llama.cpp SYCL; include the XMX-ESIMD #31068 note and the b11347 multi-sequence batch bug (re-search the tracker first, plan 4z).
Harness: `harness/` (restore_baseline.sh, pause_reconcile.sh, research_run.sh, kl_gate.sh, kl_score.sh, kl_cpu_reference.sh, kl_cpu_batch_probe.sh, engx_ab.sh).
Evidence: `evidence/` (raw JSONL, KL outputs, engx results, audits, build log, model SHA-256).
