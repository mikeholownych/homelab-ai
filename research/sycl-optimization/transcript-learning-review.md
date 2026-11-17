# Transcript-to-Codebase Learning Review

**Source:** Four YouTube transcripts captured 2026-11-14 (downloaded + Whisper-transcribed where no subtitles existed).
**Videos:**
1. `ukv-LIOI6_E` — Home AI Platform: multi-GPU inference, semantic routing, RAG, iGPU vision, NPU voice, prompt-injection guardrails
2. `MPeU9H8dMDQ` — DeepSeek V4.1 Flash 1017: causal encoder-decoder, CSA2 compressed KV cache (890 bytes/token), 384 routed experts / 6 active per token
3. `nkb4mfa3S0A` — Prometheus engine: full-model vs 2-bit copy, "bytes per word" cost framing, local vs API trade-offs
4. `0F63pTS8Gt0` — Avalon llama.cpp fork: expert cache, parallel CPU/GPU compute, 47% faster than Strata on AMD RX 7900XT

**Repo state at capture:** `main` branch, tag `v1.0.0` released, working tree clean except `research/sycl-optimization/` (4 untracked dirty files: `engx_ab.sh`, `engx-head.txt`, `kl_gate.sh`, `research_run.sh` — all research harness, no production code touched).

---

## What the transcripts teach us about this codebase

### 1. Semantic routing already exists; the video shows the *user-facing* shape of it

**Transcript 1** describes a single OpenAI-compatible endpoint ("one endpoint you send all traffic to") backed by an LLM semantic router ("Vela") that classifies intent and routes: coding → big model (RTX 3090), voice → NPU, RAG retrieval → small co-located models, vision → iGPU encoder + 3090 decoder.

**Codebase mapping:** `orchestrator_runtime/routing.py` implements deterministic, auditable model routing (`RouteRule`, `Router.decide`, `ROUTING_STRATEGIES` = first_match/fast-failover/least-latency/cost-optimized). `orchestrator_runtime/smart_router.py` adds complexity analysis (`PromptComplexityAnalyzer`, `LatencyTracker`, `CostModel`). `orchestrator_gateway/server.py` exposes `/v1/routes` and the `X-AIHost-Route` header.

**What can be learned:** The video validates the *shape* of the gateway's routing contract — one endpoint, intent-based routing, per-model capability advertising (`/v1/models` includes `vision`, `reasoning`, `tools`). It also surfaces a gap the codebase doesn't yet address: **cross-GPU pipeline splitting** (vision encoder on iGPU, decoder on dGPU) and **NPU voice** (STT/TTS on NPU). The codebase routes whole requests to workers; it does not split a single multimodal request across two accelerators.

### 2. MoE expert routing is a first-class concern in both the video and the codebase

**Transcript 2** describes DeepSeek's architecture: 40-layer backbone split into 20-layer causal encoder + 20-layer decoder, 384 routed experts per FFN layer, 6 active per token (8B params active reading, 16B generating). **Transcript 4** describes Avalon: 48 layers × 512 experts (24,576 total), 10 experts per layer per token (480 experts/token), ~1 GB of expert weights touched per token, expert cache hit rate as the key metric.

**Codebase mapping:** `orchestrator_runtime/routing.py` `RouteRule.matches()` supports `model`, `task_class`, `has_tools`, `min/max_prompt_tokens`, `attempt_gte`, `previous_outcome`, `min/max_complexity`, `complexity_tier` — but **no expert-count or expert-hit-rate awareness**. `orchestrator_runtime/metrics.py` tracks KV-cache hit ratio and per-worker latency but not expert cache hit rate.

**What can be learned:** The videos treat expert-cache hit rate and "bytes per token touched" as the primary performance metrics for MoE serving. The codebase could add:
- An `expert_cache_hit_rate` Prometheus gauge per worker (analogous to existing KV-cache metrics).
- Routing rules that prefer workers with high expert-cache hit rates for the active expert set (a "warm-cache affinity" rule).
- A complexity-tier → expert-budget mapping (the video's "8B active reading / 16B generating" maps to `complexity_tier` → `max_complexity` in `RouteRule`).

### 3. KV-cache compression (CSA2, 890 bytes/token) is a capacity-planning input the codebase doesn't measure

**Transcript 2** details CSA2: 128-token sliding window + 4 compressed global layers (2, 8, 14, 20), 890 bytes/token global KV cache, 437× smaller than uncompressed. **Transcript 4** notes Avalon's KV cache "hasn't grown into yet" holds experts too — memory is shared between KV cache and expert cache.

**Codebase mapping:** `orchestrator_runtime/cache.py` computes shingles/Jaccard for response caching; `orchestrator_runtime/metrics.py` tracks `prompt_tokens_served_from_cache` fraction. There is **no KV-cache byte-size metric** and no per-worker KV-cache pressure signal.

**What can be learned:** If the codebase is to route based on worker capacity (it already routes on latency/cost), KV-cache bytes per token is the missing dimension. A worker near KV-cache capacity should be deprioritized for long-context prompts. The video's 890 bytes/token figure is a concrete calibration target for a `kv_cache_bytes_per_token` planning constant.

### 4. "Bytes per word" cost framing changes the local-vs-API decision

**Transcript 3** argues the real question isn't "full vs fake model" but "what does a word cost in GB?" — local inference on a 12 GB card is slow but private; API is cheap but sends data out. It gives concrete numbers: 1.84 t/s on 32 GB RAM (don't bother), 9.75 t/s on RTX 4090 with 3 GB VRAM reserve (genuinely usable), API at <$0.01 for a card-racing game.

**Codebase mapping:** `orchestrator_runtime/runtime.py` enforces gateway-only access and no-local-origin; `orchestrator_gateway/server.py` has `allow_worker_pinning` (opt-in). There is **no cost model that compares local t/s vs API $/token** for a given prompt size.

**What can be learned:** The video's framing suggests a gateway feature: a "local-vs-API cost advisory" that, given prompt token count, estimates local time-to-first-token (from worker metrics) vs API cost, and surfaces it to privacy-constrained vs cost-constrained callers. This is a policy layer on top of existing routing, not a routing change.

### 5. Expert-cache + parallel CPU/GPU compute is the Avalon playbook the codebase could adopt

**Transcript 4** details Avalon's engine: every byte of idle VRAM is expert cache; compute buffers lent to cache between phases; KV-cache headroom holds experts; 400 MB safety reserve calculated precisely; GPU computes resident experts while 8 CPU cores handle cache misses in parallel; engine dynamically decides CPU-vs-GPU for missed experts. Result: 62.4 t/s vs Strata's 49 t/s (27% from cache+parallelism, 15% from drafting, 47% total).

**Codebase mapping:** `orchestrator_runtime/runtime.py` `complete()` sends one request to one worker. There is **no split execution** (GPU computes resident experts, CPU handles misses) and **no expert-cache abstraction**. `orchestrator_gateway/server.py` worker pinning is opt-in and coarse-grained.

**What can be learned:** This is the biggest architectural gap. The codebase treats workers as black boxes. Avalon shows that within a worker, expert placement (VRAM vs RAM vs CPU) and parallel miss handling are tunable levers. A research direction (matching the existing `research/sycl-optimization/` work) would be to instrument workers to report expert-cache hit rate and resident expert set, then add a routing rule that prefers workers whose resident set overlaps the request's likely active experts.

### 6. Prompt-injection guardrails exist; the video shows them as a reporting-only NPU layer

**Transcript 1** runs "Horizon Labs Prompt Injection Small" on the NPU, reporting-only (not blocking), real-time, low latency.

**Codebase mapping:** `orchestrator_runtime/guardrails.py` implements enterprise inline DLP + prompt-injection heuristics (system-instruction overrides, developer-mode tricks) with `detect_injection` flag and `matched_injections` list. It is blocking-capable, not reporting-only, and runs on the gateway CPU, not an NPU.

**What can be learned:** The video validates the guardrails' existence but suggests a deployment pattern: lightweight injection detection on low-power accelerators (NPU/iGPU) as a pre-filter before the request reaches the main model. The codebase could add an `injection_prefilter` stage with `report_only` mode matching the video's "reporting, not blocking" posture.

### 7. Benchmark methodology lessons apply directly to the repo's research harness

**Transcript 4** is essentially a master class in reading benchmark tables: same machine, same night, greedy decoding, 512 tokens, median of 3 runs; version skew matters (Strata 0.43 in the table vs 0.2.8 today); hardware generation matters (RDNA 3 7900XT vs RDNA 4 R9700); file-vs-file confounds engine-vs-engine (Avalon reads 13% more bytes/token yet wins); perplexity ≠ task performance; one-developer projects move fast and have bugs (expert file size counted 3×).

**Codebase mapping:** `research/sycl-optimization/` already embodies several of these lessons: KL-divergence correctness gate (`kl_gate.sh`), CPU/GPU baseline vs candidate scoring, transient research units on ports 18100-18199 (outside policed worker ports), production unit files never modified, `restore_baseline.sh` planned.

**What can be learned:** The transcript reinforces the harness design and adds specific checks to encode:
- Pin exact engine versions in bench logs (the video's "what exact version" question).
- Record model file identity (SHA-256) alongside results — the repo already has `kl-corpus.sha256` and model SHA-256 computation in flight.
- Report hardware generation explicitly (Xe GPU gen, RAM speed, PCIe gen) — the environment-baseline.md captures GPU firmware and kernel but not PCIe generation or RAM timings.
- Median of N runs, not single runs — verify `llama-bench` invocation uses median.

---

## Recommended actions (Ship-Learn-Next style)

These are **research directions**, not production changes. v1.0.0 is released; no production code should be touched for this.

| # | Idea | Source transcript | Repo hook | Effort |
|---|------|-------------------|-----------|--------|
| 1 | Add `expert_cache_hit_rate` Prometheus gauge per worker | 0F63pTS8Gt0, MPeU9H8dMDQ | `orchestrator_runtime/metrics.py` | Small |
| 2 | Add `kv_cache_bytes_per_token` planning constant + worker KV pressure signal | MPeU9H8dMDQ | `orchestrator_runtime/metrics.py`, `cache.py` | Small |
| 3 | Warm-cache-affinity routing rule (prefer worker whose resident experts overlap request) | 0F63pTS8Gt0 | `orchestrator_runtime/routing.py` `RouteRule.matches()` | Medium |
| 4 | Local-vs-API cost advisory (t/s vs $/token given prompt size) | nkb4mfa3S0A | `orchestrator_gateway/server.py` policy layer | Medium |
| 5 | `report_only` prompt-injection prefilter mode (NPU/iGPU pre-filter pattern) | ukv-LIOI6_E | `orchestrator_runtime/guardrails.py` | Small |
| 6 | Enforce benchmark rigor in research harness: pin engine versions, record model SHA-256, record RAM/PCIe gen, median-of-N | 0F63pTS8Gt0 | `research/sycl-optimization/harness/` | Small |
| 7 | Cross-accelerator pipeline split (vision encoder on iGPU, decoder on dGPU) — research only | ukv-LIOI6_E | `research/sycl-optimization/` | Large |

**Suggested first rep (this week):** Item 6 — audit the research harness against the video's benchmark-methodology checklist and add version/model-file/hardware-generation pinning to `kl_gate.sh` and `research_run.sh`. This is small, shippable, and directly applies the most concrete lesson from the transcripts.

---

## Verification

- All four transcripts downloaded and transcribed to `/tmp/*_transcript.txt` (253 + 176 + 248 + 373 lines).
- Codebase greps confirm: routing (`routing.py`, `smart_router.py`), guardrails (`guardrails.py`), metrics (`metrics.py`), cache (`cache.py`), research harness (`research/sycl-optimization/harness/`) all exist as mapped above.
- No production code was modified; `v1.0.0` tag untouched; semantic versioning requires no bump for a research/learning record.
- Tests: full suite previously passed (1398 passed, 33 skipped, 0 failed); no new tests added for this learning review.
