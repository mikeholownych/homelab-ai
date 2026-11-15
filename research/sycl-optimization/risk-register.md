# Risk register
| Risk | Likelihood | Impact | Status / mitigation |
|---|---|---|---|
| HEAD kernels untested on IQ1_M hybrid model (worker 2) | medium | high | Test before any deploy; no reorder kernel for IQ1_M |
| Unreliable behaviour under long context / sustained load on HEAD | unknown | high | NOT TESTED; run 64K + soak |
| Upstream HEAD is a moving target; image built from unreleased commit | medium | medium | Pin SHA + digest; rebuild reproducibly from official Dockerfile |
| Deployed b11347 multi-sequence bug (KLD 0.34 at n_seq=2) | present | low today (`-np 1`) | Blocks `-np>1` on current build; report upstream |
| Reconcile timer restarts stopped workers during experiments | observed | medium | pause/restore scripts |
| Evidence only single-GPU; Gen3 x16 multi-GPU behaviour unknown | unknown | medium | NOT TESTED |
| Candidate image unpinned base images (node:24, intel/deep-learning-essentials tag) | medium | medium | Pin by digest before production use |
| Coder-30B (qwen3moe) long-prompt prefill regresses on HEAD: -8% @2K, -13% @8K, -19% @32K | confirmed | high for agentic coding | Bisect in progress: good 493253fe, bad 39febd2a (16 SYCL commits); not the compiler, not #29245, not MMID_SCHED; no env toggle recovers it. No deploy for the Coder route until located and fixed or reported upstream |
| HEAD helps Qwen3.6 and Flash-Next but hurts Coder-30B, so a single image pin may be wrong | medium | medium | Evaluate per-worker image pins in the Ansible change; keep Coder route on deployed build until resolved |
| Hung or stuck backend not detected (watchdog design from LocalAI review) | unknown | high | NOT TESTED; add busy-watchdog keyed on oldest in-flight request plus graceful-then-forced stop to reliability set (plan 4a) |
| SYCL hang with `mmap: true` (LocalAI docs) | unknown | medium | Our default-mmap workers have not hung; verify under load/reload and with `--no-mmap` (plan 4c) |
| Image provenance drift: llama.cpp commit, base images, APP_REVISION not recorded together | medium | medium | One pinned commit variable, digest-pinned bases, embed APP_REVISION, record pin + rollback target in Ansible vars (plan 4b) |
| LocalAI's llama.cpp pin (8ca5a800) already contains the regressed range | likely | low | Informational: other Intel users likely affected; include in the upstream report once bisected |
| Correctness gate is manual; an image bump could ship without running it | medium | high | Automate KL-vs-CPU on a fixed prompt set as a pre-deploy check (plan 4g) |
| Long agent prompt may be re-read after an interleaved short request on a `-np 1` worker | unknown | medium (agent latency) | NOT MEASURED; slot/prompt-cache test through the gateway (plan 4h) |
| MTP speculative decoding unusable without an MTP-bearing GGUF | likely | low (missed speedup, no risk) | Candidate only; check model sources first (plan 4i). Colibri's reported +15-30% is unverified and not on our hardware |
| Third-party performance claims (colibri) taken at face value | low | medium | Treat as hypotheses; adopt only after our own end-to-end A/B |
| Conversation bounces between workers, losing warm prefix state | unknown | medium (agent latency) | NOT MEASURED; check gateway routing stickiness (plan 4j) |
| Benchmarks omit truncation/token accounting, so a stop-at-limit could pass as a quality result | low | medium | Record truncated flag and token counts (plan 4k); engx window-1 data checked: 0 of 62 attempts truncated |
| Tool-definition tokens inflate prefill on long-prompt regime (where HEAD regresses on Coder-30B) | unknown | medium | Measure Nexus Code tool-token share first (plan 4l); AnythingLLM 80% claim is unverified |
| Third-party chat/RAG front ends add telemetry and outbound connections (AnythingLLM default-on telemetry, CDN/GitHub fetches) | low | medium | If ever fronting the gateway: disable telemetry, enforce egress rules, keep gateway-only policy |
| An image bump changes behaviour in paths we did not check (loader, scheduler, streaming, per-model kernels) | present (Coder-30B regression) | high | Bump checklist and full gate before any deploy (plan 4m) |
| Carried patch breaks on upstream refactor or lingers after upstream fixes the issue | low today (queue empty) | medium | Additive patches only, upstream PR linked, removal condition recorded (plan 4n) |
| Gateway behaviour under worker saturation unknown (unbounded wait vs bounded queue and 503) | unknown | medium | NOT TESTED; add to failure injection with queue-depth metric (plan 4o) |
| Worker crash leaves no usable error in gateway evidence | unknown | medium | NOT TESTED; capture last worker stderr in evidence on failure (plan 4o) |
| Vulkan backend might avoid the Coder-30B SYCL prefill regression, or be worse elsewhere; untested | unknown | medium | Hypothesis only; A/B on the B65 before drawing any conclusion (plan 4p) |
| No gateway-level TTFT/ITL evidence for any candidate; microbenchmarks may not predict agent latency | present | high | Add client-side load benchmark through the gateway (plan 4q) |
| llama.cpp metrics lack TTFT, queue time and KV usage, so evidence and monitoring have blind spots | present | medium | Derive client-side, map to vllm-top vocabulary (plan 4r) |
| Prefix-reuse results from one model family wrongly applied to the other (full-attention vs hybrid checkpointing) | medium | medium | Test Coder-30B and the hybrids separately (plan 4s) |
| Engine comparison with vLLM confounded by different weights/quantisation | high if attempted | medium | Compare on engx accuracy plus latency only; label as engine comparison (plan 4t) |
| vLLM XPU may not fit or run Coder-30B on one 32 GB B65 | unknown | low | Feasibility check before any comparison (plan 4t) |
| Gateway behaviour on a hung worker, queue overflow and queue timeout is undefined or undocumented | unknown | high | NOT TESTED; define expected semantics and test (plan 4u) |
| Hybrid-model (Qwen3.6, Flash-Next) prefix reuse limited to saved checkpoints; agent continuation may re-prefill more than expected | unknown | medium | NOT MEASURED; checkpoint behaviour test (plan 4v) |
| Synthetic prompts mispredict agent behaviour (cache reuse, tool loops) | medium | medium | Trace replay of sanitised Nexus Code sessions (plan 4w) |
| `--cache-ram` default (8192 MiB) too small for several 64K conversations; idle may evict active | unknown | medium | NOT MEASURED; capacity test and host RAM headroom check (plan 4x) |
| Recorded sessions used for replay contain private data | medium | medium | Sanitise, keep local, never upload (plan 4w) |
| SGLang XPU comparison confounded by weights and stack | high if attempted | low | Engx accuracy plus latency only, after vLLM feasibility (plan 4y) |
