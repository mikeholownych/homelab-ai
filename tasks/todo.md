# Model re-evaluation for llama.cpp workers (ai-5820-01)

Status: EXECUTION AUTHORIZED (2026-10-07). Operator instruction: "continue with all of the remaining work in todo.md, only the work clearly marked as deferred should be left undone." This supersedes earlier approval uncertainty and "no production change without separate authorization" language below. Follow the recorded execution DAG; leave only `Future evolution` deferred.

## Why
The current pools were chosen under constraints that no longer hold. Qwen3.8-27B was rejected in Phase 12
only because vLLM XPU lacked the linear-attention kernels. Both GPUs now run llama.cpp SYCL, which already
serves the same `qwen3_5` architecture (Qwen3.5-27B) on GPU 1.

## Fixed constraints (verified 2026-10-06)
- 2x Arc Pro B65, 32 GB each, PCIe Gen3 x16 (C422). A cross-card split pays the Gen3 penalty.
- Host: 8 cores, 61 GiB RAM (~50 available), 404 GB free on /var/lib/local-ai.
  CPU expert offload (`--n-cpu-moe`) will be slow on 8 cores.
- llama.cpp b11347 (`5fc4f3c8c`, IntelLLVM 2026.1.1). It has `--fit`, `--lazy-mode`, `--load-mode`,
  `--n-cpu-moe` and `--spec-type`.
- Topology: lead pool on GPU 0, deep pool on GPU 1, `max_concurrency: 1` each, 64K context, gateway fallback between the pools.
- Already on disk: Qwen3-Coder-30B-A3B Q4_K_M, Qwen3.5-27B Q4_K_M, Qwen3.5-9B Q4_K_M,
  Devstral-Small-2-24B Q4_K_M.

## Candidates
| # | Model | Pool | Fit | Notes |
|---|-------|------|-----|-------|
| C1 | Qwen3.8-27B (dense, Gated DeltaNet hybrid) Q4_K_M ~17.1 GB / Q5/Q6 | deep | 1 card, ~19-25 GB at 32-128K | Direct successor to the incumbent. Highest prior. |
| C2 | Qwen3.8-Flash-Next-GSQ-RCO-Coder (pruned 512->256-expert MoE) | deep or both | 29.6 GB resident + 28.8 GB n-gram table mmap'd (`--lazy-mode`) | ~2 GB VRAM left on one card, so small context. Never reported on SYCL. Its IQ-type kernels may be slow on SYCL. |
| C3 | Qwen3.8-Flash-Next GSQ-RCO (unpruned) Q2_0 | both cards | 37.6 GB resident | Only fits by merging both GPUs into one pool: loses the lead/deep split and pays the Gen3 penalty. Stretch candidate only. |
| C4 | Devstral Small 2 24B Q4_K_M (on disk) | deep/lead | 1 card | Strongest non-Qwen local coder. Zero download cost. |
| C5 | Qwen3.6-35B-A3B (MoE) | lead | 1 card | Possible successor to Qwen3-Coder-30B-A3B for the fast pool. |
| C6 | GLM-4.7-Flash (30B-A3B MoE, MIT) Q4_K_M ~17 GB | lead | 1 card | Published SWE-bench Verified score 59.2; built for tool calling. Lead-pool challenger to Qwen3-Coder-30B. |
| C7 | Muse Glimmer 30B | deep | ~24.6 GB with vision; less without | Published SWE-bench Verified score 76.0. Its speed numbers rely on DFlash (likely CUDA-only), and its AD-IQ quants are untested on SYCL. |
| C8 | Gemma 4 31B (dense), Nemotron 3.5 Lightning 30B-A3B (Mamba hybrid) | either | 1 card | Lower priority: Nemotron's SWE-bench Verified score is 51.6, and its SSM kernels on SYCL are unverified. |

Quant lever: every card has 13+ GB unused at Q4_K_M. Re-test the winners at Q5_K_M/Q6_K. Decode is bandwidth-bound, so measure
the speed cost against the quality gain.
Published scores are leads, not evidence: Devstral (published SWE-bench Verified 68.0, "best coding" in atomic.chat 2026-08) was LAST on engx (66.7%).

Ruled out on size (2026-10-06): Kimi K3 (2.8T) and K2.6 (1T, ~350 GB at 2-bit); DeepSeek V4.1-Flash (552B) and V4-Pro (1.6T);
GLM-5.3-Flash (320B/18B active, est. 80-100 GB at 1-2 bit, so it needs both GPUs plus CPU offload on 8 cores).
DeepSeek R1-Distill-32B fits but is an older Qwen2.5-based model.

Incumbents (controls): Qwen3-Coder-30B-A3B Q4_K_M (lead), Qwen3.5-27B Q4_K_M (deep).

## Gates (stop at the first failure for each candidate)
- [x] G0 Paper screen (SATISFIED: revisions pinned in ~/engx/fetch-wave1.sh, licenses checked; the tool-call template clause moved to Q-TOOLS, see docs/closeout/00-reconciliation.md #1): GGUF exists from a trusted quantizer, pin the sha256, license OK, chat template works with `--jinja` tool calls.
- [x] G1 Load/smoke (load SATISFIED: every candidate served 30 task-runs; VRAM headroom moved to Q-LONGCTX, reconciliation #2) on a single card at production flags (`-ngl 99 -fa on -c 65536 -np 1`). Record VRAM headroom.
      The 64K context is mandatory for drop-in replacement. For C2, record the maximum context achievable.
- [x] G2 Speed: SUPERSEDED by measured per-attempt decode tok/s (REPORT-2026-10-07 serving table) and the operator ruling quality>speed; speed at depth is measured in Q-LONGCTX (reconciliation #3). `llama-bench` pp512/tg128 at depths 0 / 16K / 48K, plus warm prompt-cache reuse.
      A candidate must not regress decode tok/s for its pool by more than an agreed threshold (TBD with operator).
- [x] G3 Quality (SATISFIED: evaluations/engx/REPORT-2026-10-07.md): the same engx engineering bench that justified the current routes, on the same tasks and seeds,
      with incumbents re-run in the same window.
- [ ] G4 Promotion (ACTIVE: W-PROMOTE): Ansible inventory change only (`llama_cpp_container_workers` and `orchestrator_gateway_workers`
      digest, revision and evidence_ids). Rollback = revert the commit and re-converge.

## Execution notes
- Test one GPU at a time. The gateway fallback keeps serving on the other pool, so production runs on
  one pool for the test window.
- Downloads go to /var/lib/local-ai/models/gguf, ~150 GB worst case if every candidate is fetched.
  Fetch only after G0 passes.
- [x] Cleaned stale `model_selection_controls.serving_model` (qwen3.8, TP=2) in group_vars; model and TP are now unset.

## engx bench (found 2026-10-06)
- The harness was written in nexus-code session 5e99063d, in its /tmp scratchpad, and run from /tmp/evalx
  on the host. The host's /tmp was wiped at the 2026-10-04 reboot.
- Preserved (uncommitted) in `evaluations/engx/`: engx.py, engx_tasks.py, engsum.py, the recovered results table
  and the vLLM-vs-llama accuracy comparison. The host has pytest 9.0.2 and bwrap.
- Limitation: 12 tasks x 3 reps. Only 5 tasks discriminate (T02, T07, T08, T10, T11); the other 7 are solved by every
  model. The incumbent deep model already scores 86%, so a stronger candidate will hit the ceiling. G3 needs a
  harder extension, ideally around 10 more tasks at T07/T10 difficulty, or results will be noise.
- (SUPERSEDED by the remote-origin policy: engx runs on the client; results go to the repository, reconciliation #9.)

## Operator decisions (2026-10-06)
1. Extend the bench with harder tasks first: YES.
2. Topology is NOT fixed: merge both GPUs into one pool if that is measurably the best setup. C3, and C2 with long context, are in scope.
   The comparison must include "one big model on 2 cards" vs "two pools".
3. Quality beats speed: rank by validated rate first. Speed only breaks ties, or disqualifies a model if it is unusable
   (agree a hard floor at G2, e.g. < 5 tok/s decode).

## Bench extension (in progress)
- [x] engx.py: ENGX_CORPUS (base|hard|all), ENGX_MAX_TOKENS (thinking models), ENGX_OUT (no /tmp), run metadata + corpus hash
- [x] engx_tasks_hard.py: 10 tasks at T07/T10 difficulty (spec-heavy, multi-bug, migration, perf, root cause)
- [x] selfcheck on host (2026-10-06: all 22 tasks OK, base corpus unchanged): every task fails initially, reference passes hidden
- [x] Baseline incumbents on hard corpus (SATISFIED: ~/engx/results/eng-hard-{lead,deep}-*-nothink.json) (both pools) before any candidate
      Running since 2026-10-06 09:41Z on ai-5820-01:~/engx. Protocol matches Oct 3: NOTHINK=1, MAX_TOKENS 4096, 3 reps,
      direct to worker ports 8000/8001. Results in ~/engx/results, logs in ~/engx/logs.
- [x] Phase A candidates (operator: evaluation takes precedence over serving, 2026-10-06 09:47Z).
      runqueue.sh per GPU: waits for that GPU's baseline, `systemctl stop`s its production worker, pulls jobs from
      ~/engx/queue.txt (wave 1), runs cand.sh (pinned prod image + flags, port 8002/8003), restarts the worker when the queue is empty.
      Production workers WILL be down during this window. If anything aborts, restore with:
      `sudo systemctl start aihost-llama-worker1 aihost-llama-worker2`.
      Run 1 (10:13-12:02Z): only Qwen3.8-27B ran. The other four never started: "conmon: Failed to get working directory".
      Cause: after a worker unit (PrivateTmp=true) restarted, aihost-runtime's rootless podman namespace had a private /var/tmp.
      Fixed: cand.sh now runs podman from /var/lib/aihost-runtime and fails fast if `podman run` fails. Requeued at 12:49Z (run 2).
      Interim hard-corpus results (NOTHINK, 3 reps): Qwen3.8-27B 73.3% (22/30), Qwen3.5-27B 70.0% (21/30), Qwen3-Coder-30B 10.0%.
      The 27Bs are statistically tied but complementary: Qwen3.8 solves H03 and H07, Qwen3.5 solves H01 and H02 reliably; neither solves H08.
      Harness issues found 2026-10-06 ~15:15Z (invalid artifacts moved to ~/engx/logs/invalid/):
      - GLM-4.7-Flash scored 0/30 because it writes `### FILE: x.py` WITHOUT code fences: 75/90 attempts were rejected as format
        before any test ran. The parser now falls back to unfenced FILE sections when there are no fenced blocks (selftest added;
        74/75 of GLM's rejected replies now parse). GLM is requeued as c-glm47flash-q4km-r2. Effect on earlier runs: only replies
        with zero fenced blocks are affected (lead baseline had 1 such attempt), so results are effectively unchanged.
      - Muse Glimmer reasons even with enable_thinking=false (probe: reasoning_content present). Under 4096 tokens every attempt
        truncated (~520 s/task). The NOTHINK run was aborted at 17/30 and requeued as t-glimmer30b-q4km under Phase B settings.
      Phase A result (NOTHINK, 3 reps, hard corpus), 2026-10-06 16:04Z:
        Flash-Next GSQ Coder (1 GPU, CTX 32K, lazy n-gram table) 80.0% | Qwen3.8-27B 73.3% | Qwen3.5-27B 70.0% |
        Qwen3.6-35B-A3B 70.0% (75 s/task, about 2.5x faster) | Qwen3-Coder-30B 10.0%. GLM rerun (fixed parser) in progress.
      Runner fixes 16:10Z:
      - server logs were always empty (rootless journald log driver); now --log-driver k8s-file;
      - a container that dies during load now fails fast instead of waiting out the 15-min health timeout.
      Flash-Next queued first in Phase B at CTX 65536 (production context) with a 32K fallback job behind it.
      GLM-4.7-Flash rerun with the fixed parser: 3.3%. Failures are genuine (wrong results, broken code, degenerate repetition
      loops until max_tokens). Dropped; not run in Phase B.
      Flash-Next at CTX 65536 LOADS on one card (n_ctx_slot=65536). llama.cpp warned "failed to fit params to free device memory"
      (could not verify the fit, n_gpu_layers forced to 99). Its Phase B run is the evidence: check for request errors/OOM at long
      context before trusting 64K.
- [x] Phase B (thinking on, ENGX_MAX_TOKENS=16384, 3 reps, hard corpus), queued 2026-10-06 ~14:00Z behind Phase A on the same
      runqueue: t-q35-27b-q4km (incumbent deep, same flags as prod), t-q38-27b-q4km, t-q36-35b-a3b-q4km. Add the best of
      Glimmer/GLM/Flash-Next if Phase A puts it near the top. Then: interpret results, implications for the follow-up
      workstreams, and any newly apparent work (operator instruction).
- [x] Wave-1 downloads (SATISFIED: files under /var/lib/local-ai/models/gguf/*; fetch log ends DONE) (G0 passed: repos exist, licenses Apache-2.0/MIT, revisions pinned in ~/engx/fetch-wave1.sh),
      into /var/lib/local-ai/models/gguf/<name>/:
      Qwen3.8-27B UD-Q4_K_M 16.5G, Muse-Glimmer-30B Q4_K_M 16.8G, Qwen3.6-35B-A3B UD-Q4_K_M 22.1G,
      GLM-4.7-Flash Q4_K_M 18.3G, Flash-Next-GSQ-RCO-Coder IQ1_M 29.6G + 28.8G

## Non-actions
- Do not replace either production worker before G3 evidence exists.
- Do not adopt quality claims from model cards (e.g. SWE-bench retention) as evidence; they are leads only.

## Goal of the inference platform (operator, 2026-10-06)
Efficiency, resilience and maximised provider effectiveness. Every follow-up workstream below is judged by its measured effect
on these three, not by feature count.
- Efficiency: useful work per GPU-hour (slot utilisation, prefix-cache reuse, no idle or thrashing capacity).
- Resilience: work survives worker/gateway restarts, model swaps and overload (drain, backpressure, safe retry, fallback).
- Provider effectiveness: the right model and settings for each request, proven by outcome evidence (R10, qualification), not
  assumed.

## Governing principle for all follow-up workstreams (operator, 2026-10-06)
"Own what you control. Report what you observe. Don't assume responsibility for decisions you cannot make authoritatively."
Generalised: "Each layer observes what it doesn't control, exposes what it knows, and takes responsibility for what it does control."
- Gateway: enforce limits and safety server-side, report live limits and state, never depend on client ingestion.
- vllm-top: observe and report, including policy violations; it does not act on processes or servers.
- aihost: does not change clients (e.g. Nexus). Client-side changes are recorded as operator decisions.

## Follow-up: vllm-top engine-agnostic discovery and monitoring (operator-approved 2026-10-06; partially implemented)
TARGET END STATE (operator): whatever inference server is running (vLLM, llama.cpp, something else) is picked up and monitored
automatically. That holds whether it is a gateway worker, a systemd unit or an ad-hoc process/container, and whether it started
before or after the console.

Found during the model evaluation: while candidates served on :8002/:8003 with both production workers stopped, the TTY1
console showed nothing working.
Progress in vllm-top 0.7.0–0.9.2: gateway worker telemetry is engine-neutral, per-worker health/pool/route data is shown,
and gateway instances are supported independently of vLLM. The production binary and Ansible build source were verified at
v0.9.2. A separate legacy checkout at `/home/mike/Projects/vllm-top` is v0.8.0 and is not used by the deployment role.
The prior deployed candidate was v0.10.0. Expected-stopped handling was deployed as v0.10.1; dynamic worker-status
reconciliation v0.10.2 was deployed via the `vllm_top_console` role on 2026-10-07.

Accepted design (`docs/design/06-vllm-top-engine-agnostic.md`):
- Discovery driven by listening sockets, not process names. Periodically walk /proc/net/tcp{,6} LISTEN sockets, then
  fingerprint each with bounded, read-only, no-inference GETs. Process cmdline/systemd stay as hints for attribution only.
- Engine adapters behind one trait that normalises to a common model (model id, running/queued requests, prompt and decode
  tok/s, KV/context use, health, auth state):
  - vLLM: /metrics vllm:*
  - llama.cpp: /metrics llamacpp:*, /props, /slots
  - Ollama: /api/version, /api/ps
  - SGLang: /get_server_info, sglang:*
  - TGI: /info
  - Fallback: any OpenAI-compatible /v1/models, shown as "unknown engine, limited metrics" instead of hidden.
- Continuous re-discovery: new servers appear and gone ones are marked down, with no console restart.
- Gateway workers are merged with their directly discovered endpoints, not double-counted.
- Engine-independent GPU activity view (per-GPU utilisation/memory/power from sysfs/xpu-smi), so busy hardware with an
  unrecognised server is still visible.
- Keep the discover.rs rules: never read other processes' config/env, never harvest credentials. Auth-protected endpoints show
  as "auth required", not blank.

- [x] Design doc and review (adapter trait, fingerprint rules, refresh cadence, dedupe with gateway; `docs/design/06-vllm-top-engine-agnostic.md`)
- [x] Implement socket-driven discovery, engine fingerprints, periodic lifecycle, gateway dedupe and policy-violation display
      in vllm-top/ with per-engine fixtures. Candidate v0.10.0; all 139 Rust tests pass and release build succeeds.
- [x] Deploy v0.10.0 via the vllm_top_console role and verify the production version (service active; host reports v0.10.0).
- [x] Deploy v0.10.1 expected-stopped semantics and verify host reports v0.10.1.
- [x] Dynamically reconcile gateway worker state on each 5-second /health poll so stopped workers disappear and resumed
      workers return without restarting the console. Regression coverage delivers stopped and healthy gateway snapshots to one
      running App instance and verifies removal/reappearance; v0.10.2 deployed and live version verified.
- [ ] Verify live on ai-5820-01:
  - [ ] an ad-hoc llama-server started after the console appears;
  - [x] an intentionally stopped worker remains in gateway inventory with `status=stopped`, does not degrade gateway health,
        is not probed or assigned failure counters, and is omitted from vllm-top inference instances. Live: gateway healthy,
        ready/can_route true, 2/2 serving workers, 3 configured/1 stopped; worker2 drained/inactive, 0 failures, no stats;
        health/availability Prometheus gauges are 0; vllm-top --once exits 0 and lists only worker1 and candidate.
  - [x] gateway workers are not double-counted in the live inventory (one row per gateway worker in `vllm-top --once`).
  - [ ] an unrecognised OpenAI-compatible server shows with limited metrics.

## Policy: gateway-only access to inference workers (operator, 2026-10-06; end-state requirement)
"Any change to the inference workers should mean the active worker is accessed via the gateway. No direct workload requests
should ever be allowed."

Current state (checked 2026-10-06):
- Workers bind 127.0.0.1 only.
- Worker API keys are 0400 aihost-runtime.
- nftables drops external :8000.
Gaps:
1. The gateway runs as the SAME uid as the workers (aihost-runtime), and any sudoer can read the keys. Today's evaluation
   reached :8000/:8001 directly with the keys via sudo. Nothing on loopback distinguishes the gateway from any other local
   client.
2. Ad-hoc servers (the evaluation candidates on :8002/:8003) run with no API key and no firewall rule. Anything local can
   use them.
3. The external drop rule names :8000 only, not :8001 or future worker ports.
4. Qualification/benchmark tooling (engx, cand.sh) targets worker ports directly, so the evaluation path is not the production path.

- [x] Design (review before implementing): accepted in `docs/design/04-gateway-only-worker-access.md` (2026-10-07).
  - Run the gateway as its own uid.
  - nftables output rule on lo: tcp dport {worker ports, generated from llama_cpp_container_workers / orchestrator_gateway_workers}
    is accepted only for meta skuid <gateway uid>; everything else is dropped and counted.
  - Alternative to weigh: workers on unix sockets readable only by the gateway.
  - Keys readable only by the gateway uid.
- [ ] Candidate/qualification path through the gateway: register a candidate as a non-routable pool reachable only by explicit
      model alias (like engineering/deep). engx then points at the gateway. No more direct-port evaluation runs after this lands.
- [x] Enforce via Ansible: inventory-derived nftables policy, atomic reload and syntax preflight are live; gateway runs as uid 995 with worker credentials handed through systemd; remote TLS listener is live at `10.0.8.5:8443`, allowed for `10.0.8.95/32`; both llama workers and gateway are active (2026-10-07).
- [ ] Detection: vllm-top's engine-agnostic discovery flags any inference server NOT registered with the gateway as a policy
      violation. Health/metrics remain observable via the gateway's /health engine_stats.
- [x] Verify direct worker-port connects to 8000 and 8001 are refused from `mike`, `root`, and `aihost-runtime`; gateway uid 995 connects; direct-denial counter increments; remote authenticated chat succeeds; local workload is refused with HTTP 403 (2026-10-07).
- [ ] Verify vllm-top shows the violation for an ad-hoc server after W-VTOP.
Note: the 2026-10-06 model evaluation (in progress) uses direct worker access. It predates this policy and is a one-off. The
chosen model's final qualification will be re-run through the gateway once the path above exists.

## Policy: no work initiated on the aihost (operator, 2026-10-06; end-state requirement)
"Work should never be initiated from the aihost, only from a remote call to that host."
Together with gateway-only access: work = remote client -> gateway (network listener) -> worker. Nothing on ai-5820-01 itself
(shells, scripts, timers, benchmark harnesses, sudo) originates inference work.

Current state (checked 2026-10-06):
- The gateway listens on 127.0.0.1:8010 only (orchestrator_gateway_host default), so remote clients can only arrive through an
  SSH tunnel. Tunnelled traffic reaches the gateway FROM LOOPBACK and is indistinguishable from work started on the host.
- The engx harness, cand.sh and runqueue.sh all ran ON the host today.

Live state (checked 2026-10-07): OpenCode uses `https://10.0.8.5:8443/v1` and trusts the fetched gateway certificate; this
client is allowlisted as `10.0.8.95/32`. The TLS gateway and nftables policy are active. A remote OpenCode request returned
`OK`; a host-origin workload request returned 403. Local `/health` and `/metrics` return 200. The user SSH tunnel is disabled.

- [x] Design (review before implementing): accepted in `docs/design/05-remote-origin-only.md` (2026-10-07).
  - The gateway listens on the host's VLAN address (eno1.2) behind nftables allowlisting the client subnet(s), with gateway auth
    (and TLS, or an mTLS/WireGuard decision).
  - The gateway refuses workload endpoints from local peers (127.0.0.0/8, ::1, the host's own addresses). /health and metrics
    stay readable locally for vllm-top.
  - SSH tunnels stop being a supported client path.
  - Inventory every host-side component that calls the gateway or workers (timers, gateway self-checks, smoke/validate plays)
    and convert workload-generating ones to remote execution or to non-inference probes.
- [x] On-host originator retirement: archive verified byte-for-byte against all 115 non-cache files in the retired engx tree; Ansible removed that checkout, the disabled benchmark timer/service, retired vLLM unit files, and benchmark/vLLM helper binaries (2026-10-07).
- [ ] Remote evaluation path: engx runs from a client machine (the bwrap sandbox runs on the client; give the client python
      pytest) against the gateway's candidate alias pool. Retire cand.sh/runqueue.sh as on-host tools. Candidate lifecycle
      (start/stop a candidate worker) is done by Ansible from the controller, not by scripts on the host.
- [x] Enforce via Ansible and verify the gateway path: remote TLS listener and nftables allowlist are live; remote authenticated chat returned HTTP 200; host-origin workload returned 403; loopback `/health` and `/metrics` return HTTP 200. The former OpenCode SSH tunnel is disabled (2026-10-07).
- [ ] Verify vllm-top engine-agnostic discovery behavior after W-VTOP; the console service is active and the local health/metrics endpoints respond.
Note: operator decision 2026-10-06: the full 2026-10-06 evaluation (Phase A AND Phase B thinking-on) completes as is, on-host,
as a one-off exception that predates this policy. Skew review: quality/pass-fail is unaffected (same prompts, same llama.cpp flags).
Speed is approximate (runs were sometimes parallel, with sandbox CPU contention), so watch H10's wall-clock limits.
Re-qualifying the chosen model through the remote gateway path is still required before promotion.

## Gateway: live, dynamic limit management per worker (operator, 2026-10-06)
"The gateway should match the worker token max for whatever model is running, so it neither artificially restrains nor floods
the workers." Refined: "it should be aware of the actual limits of whatever worker is running, and manage the limits
dynamically."

Found: orchestrator_gateway_workers[].max_output_tokens (1024) is loaded but never applied. runtime.py:499 only clamps max_tokens
to a hand-set context_limit using an ESTIMATED prompt size. context_limit and max_concurrency are static inventory values that
drift from reality (model swaps, -c/-np changes).

Target behaviour: the gateway keeps a live capacity model for each worker and admits, sizes and paces work against it.
1. Discover and re-discover identity and hard limits from the engine, not inventory (engine adapters shared with vllm-top):
   - llama.cpp /props: n_ctx, total_slots, model, chat template. Per-slot context is n_ctx / n_parallel unless kv-unified.
   - vLLM /v1/models: max_model_len, plus /metrics.
   Refresh on every health cycle. An identity or limit change (model swap, restart with new flags) updates the capacity
   model immediately and is logged as evidence.
2. Track live state continuously:
   - llama.cpp: /slots, /metrics (llamacpp:requests_processing, kv usage, tokens/s)
   - vLLM: vllm:num_requests_running/waiting, gpu_cache_usage
   - GPU memory/thermal state
3. Exact sizing, not estimates: count prompt tokens with the worker's own tokenizer (/tokenize, or a cached tokenizer for that
   model). max_tokens defaults to and is clamped by the real remaining context of the slot that will serve the request.
   No fixed 512/1024.
4. Admission control and backpressure:
   - Dispatch only when the worker has a free slot / KV headroom.
   - Otherwise queue in the gateway, route to a fallback pool where the route allows, or return 429 + Retry-After.
   - Never queue blindly inside the worker.
5. Adaptive concurrency: start from discovered slots/batch capacity, then adjust dynamically (e.g. AIMD) from observed latency,
   time-to-first-token, decode tok/s, KV pressure and errors. Throttling or degradation lowers the limit; recovery raises it again.
6. Inventory values become expectations only. A mismatch with observed raises an alert and evidence. Whether it also blocks
   routing until reconciled is a policy decision for the design review.
7. Visible: the gateway's /health and engine_stats expose the live capacity model, so vllm-top shows limits, headroom and
   queue per worker.
Client-facing gaps found 2026-10-06 while reviewing Nexus context handling (Nexus itself NOT modified; read-only review):
   a. Report the live limits to clients (today /v1/models returns ids only, server.py:155):
      - /v1/models per alias: context_length, max_completion_tokens, also max_model_len for vLLM-style clients, plus a
        limits_version that changes whenever any limit changes.
      - The alias limit is what the gateway can GUARANTEE: the minimum over every worker the alias can reach (pool + fallbacks).
        Alternatively, fallback only goes to workers where the exact request fits. Never a number that holds for one worker only.
      - Capabilities alongside limits, per alias (operator, 2026-10-06):
          tools/function calling (+ parallel tool calls), structured output (json_schema / grammar), vision/image input,
          reasoning (supported, default on/off, budget control), streaming, FIM/infill, embeddings, plus the serving model
          identity (model id, quantization, artifact digest, engine + version).
        Each capability carries its PROVENANCE:
          - "declared" = discovered from the engine (e.g. llama.cpp /props chat template advertises tools, mmproj loaded
            means vision);
          - "verified" = proven by a gateway probe or qualification evidence (evidence id + date, e.g. engx results).
        Never report an assumed capability.
        Alias capabilities are the INTERSECTION over every worker the alias can reach, which is what the gateway can guarantee.
        The same capability model drives R9 (capability-checked routing): one source of truth for routing and reporting.
      - Every response carries the live numbers in headers (e.g. X-Context-Limit, X-Prompt-Tokens [exact],
        X-Context-Remaining, X-Limits-Version, X-Served-Model), so a long session notices a model swap without re-polling.
      - Rejections are machine-readable: context_length_exceeded with exact prompt_tokens / limit / requested output, so the
        client can compact precisely; 429 + Retry-After for capacity, not context.
      - Client ingestion is OUTSIDE aihost control (operator, 2026-10-06). Design principle that follows: the gateway must be safe
        for clients that ignore all of this. Server-side defaults (completion/reasoning budget when max_tokens is absent),
        exact-token clamping, fit-checked fallback and structured rejections must work with no client cooperation. Reporting
        limits is an aid for capable clients, never a requirement.
   b. Count what is actually sent: today the gateway estimate is sum(len(content))//4 (runtime.py:438). It ignores the tools
      schema, assistant tool_calls arguments and chat-template overhead, so tool-heavy agent prompts are underestimated.
      Use the worker tokenizer over the fully rendered request.
   c. Requests WITHOUT max_tokens (Nexus never sends one) bypass the clamp entirely (runtime.py:499 only clamps a supplied
      value), so the worker generates until its context is full. Apply a route/worker default completion budget (including
      a reasoning budget, see R8) when the client omits it.
   d. Offer a token-count endpoint through the gateway (e.g. /tokenize per alias) so clients can budget exactly.
- [ ] Design doc and review (per-engine adapter contract; tokenizer strategy; admission/queue/429 semantics; adaptive
      algorithm and bounds; interaction with routing/fallback and the gateway-only policy)
- [ ] Implement with tests:
  - model swap with different n_ctx/slots is picked up without config edits;
  - exact-token clamping at the context boundary;
  - saturation gives queueing/429 rather than worker overload;
  - concurrency adapts under induced slowdown and recovers;
  - mismatch alerting.
- [ ] Remove max_output_tokens and the ORCHESTRATOR_MAX_OUTPUT_TOKENS=512 default once dynamic sizing lands.

## Gateway: smart-routing capabilities (operator approved all 12, 2026-10-06; not started)
Already present: deterministic first-match route table (model alias, task_class, has_tools, prompt size) with fallback pools;
X-Session-ID affinity hashing for warm prompt caches; bearer auth; streaming with tool-call index repair; health with failure
counting; evidence log; metrics.
Each item gets a short design note and review before code, ships via Ansible, and has tests. Suggested first batch: R1, R2, R3, R5
(small, and each fixes a problem that will hit soon with one slot per pool).
- [ ] R1 Cancellation: when a client disconnects or times out, abort generation on the worker and free the slot (llama.cpp and
      vLLM both stop on connection close; verify per engine). Evidence and metrics record cancellations.
- [ ] R2 Priority and fairness: interactive / batch / background classes (header + per-client default). Interactive goes first;
      fair share between clients. Ties into R6 and the dynamic admission queue.
- [ ] R3 Deterministic escalation: rules like "attempt >= 2 -> deep" (X-Attempt header) or client-reported failure -> deep pool,
      recorded in evidence. No LLM-based router.
- [ ] R4 Shadow and canary routing: mirror N% of a route to a candidate pool (outputs compared and logged, never returned) or send
      it a small live share. This becomes THE qualification path under the gateway-only and remote-origin policies, replacing
      on-host engx runs.
- [ ] R5 Drain and safe swap: per-worker drain state (no new admissions, in-flight completes, then restart or swap); Ansible model
      swaps drain first; drain state visible in /health and vllm-top.
- [ ] R6 Per-client identity, quotas and budgets: a key per client; client id on every evidence record; per-client token budgets
      and rate limits that return 429 with Retry-After.
- [ ] R7 Deadlines and safe retries: client deadline header; queued requests expire at the deadline; retry/fallback only BEFORE
      the first streamed token, never mid-stream.
- [ ] R8 Reasoning control per route: route-level enable_thinking and reasoning-token budget; reasoning_content presented the same
      way across engines. Defaults are set from Phase B (thinking-on) evaluation evidence.
- [ ] R9 Capability-checked routing: detect requirements (response_format/json_schema, tools, vision, long context) and route only
      to capable workers (capabilities discovered with the dynamic limits). Clean rejection otherwise.
- [ ] R10 Outcome feedback loop: an endpoint where clients report pass/fail per request id; success rate per route and pool from
      production data; route-table changes cite this evidence.
- [ ] R11 Evidence integrity and data handling: hash-chained, tamper-evident evidence log; explicit prompt policy (store / redact /
      hash only), default hash-only plus metadata, because prompts may contain secrets.
- [ ] R12 Graceful gateway restart: drain the gateway itself (stop accepting, finish in-flight streams) on restart/redeploy;
      systemd stop timeout sized to it.
Deliberately excluded for now: an LLM-based prompt classifier in the router (breaks deterministic/auditable routing; R3 covers
most of the value), on-demand model loading per request (30-90 s load), embeddings/rerank endpoints until a client needs them.

## Future evolution (operator idea, 2026-10-06; LATER, not authorized): workload management, efficient worker use, model switching
Builds on: dynamic limits, R1 cancel, R2 priority, R5 drain/swap, R7 deadlines, R10 outcomes, engine adapters, vllm-top.
Topics to shape when it is picked up:
- Queueing as a first-class gateway function:
  - per-class queues (interactive / batch / background) with deadlines and fair share;
  - an async job API (submit -> id -> poll/stream/callback) for long agent or batch work, so clients don't hold connections;
  - queue state exposed (depth, wait estimates).
- Efficient worker use:
  - pack work to free slots;
  - decide per model whether to run more parallel slots (llama.cpp -np with kv-unified) versus one large-context slot,
    measured rather than assumed;
  - keep prefix-cache affinity as a scheduling input. Evidence from Nexus 2026-10-04: prefix-cache reuse dominates cost on this
    stack, so a "fairer" scheduler that breaks cache locality can cost more than it saves.
- Model switching:
  - demand-driven loading/unloading of models onto GPUs (warm set vs cold set), using R5 drain first;
  - swap cost is about 30-90 s, so add hysteresis/minimum residency to avoid thrash;
  - queue-aware decisions (switch only when the backlog for a cold model justifies it);
  - several small models per 32 GB card where they fit;
  - the route table resolves to "model capability", and the scheduler decides placement.
- Batch windows: run benchmark/qualification and background jobs when interactive demand is low (this replaces ad-hoc
  "stop the workers" evaluation runs like 2026-10-06).
- Principle check: the gateway/scheduler owns placement and admission; it reports queue/placement state; clients own their intent
  (class, deadline). The scheduler never guesses intent it cannot know.

## DEFECT (open 2026-10-07): unbounded reasoning on the deep route. See docs/defects/2026-10-07-unbounded-reasoning-deep-route.md
- [ ] Remediation design: evaluate (1) worker hard budget, (2) client-selected route/profile policy enforced server-side,
      (3) gateway total generation bounds including a default when max_tokens is absent, (4) distinct telemetry for budget
      exhaustion. Fail closed. No production change without separate authorization.
- [ ] Choose the budget from Phase B BOUNDED data (4096 is the first point only); add budget points if the distributions require it.

## Phase B redesign (operator-approved 2026-10-07)
- UNBOUNDED_REASONING runs terminated 2026-10-07 ~04:00Z. Evidence preserved unchanged in ~/engx/evidence/UNBOUNDED_REASONING/:
  complete Qwen3.5 run; partial Flash-Next 64K (16 task runs) and 32K (2 task runs); full server logs; scheduler logs.
- THINKING_ON_BOUNDED_4096: server --reasoning-budget 4096 + end-of-budget instruction; all other controls identical to the
  unbounded runs: corpus, 3 reps, validators, CTX, temperature 0, ENGX_MAX_TOKENS 16384, GPU assignment. Models: Flash-Next 64K
  (gpu0), Qwen3.5-27B (gpu1), Qwen3.8-27B (gpu0), Qwen3.6-35B-A3B (gpu1).
- Glimmer THINKING_OFF: server --reasoning off. Results are accepted only if /props, the launch command and per-attempt reasoning
  tokens prove reasoning is actually disabled.
- Harness instrumentation (2026-10-07). Per attempt it records:
  - exact reasoning/answer tokens via the engine tokenizer;
  - server timings and estimated TTFT;
  - budget_reached, valid_final_answer, termination class;
  - partial results after every task.
  Tasks, validators and scoring are unchanged.
- Report requirements:
  - per-model/run fields as specified;
  - comparison THINKING_OFF vs THINKING_ON_UNBOUNDED vs THINKING_ON_BOUNDED_4096, never pooled;
  - failures classified as MODEL_CAPABILITY vs SERVING_CONFIGURATION_FAILURE vs REASONING_BUDGET_EXHAUSTION.

## Evaluation COMPLETE 2026-10-07 12:21Z. Report: evaluations/engx/REPORT-2026-10-07.md
Production restored with its original config (both workers healthy via the gateway). No production change made.
Headline:
- Current lead Qwen3-Coder-30B: 10%.
- Candidates BOUNDED_4096: Flash-Next 90%, Qwen3.8 86.7%, Qwen3.6 80% (58.6 tok/s), Qwen3.5 70%.
- UNBOUNDED reasoning failures are SERVING_CONFIGURATION_FAILURE.
Awaiting operator decisions:
- [x] Defect remediation AUTHORIZED (operator brief 2026-10-07 section 2) (worker budget + gateway default bound + telemetry; value from the budget sweep)
- [x] Lead-pool swap to Qwen3.6-35B-A3B DECIDED (operator brief section 1); execution tracked in W-PROMOTE
- [x] Deep-pool choice DECIDED: Flash-Next, with Qwen3.8-27B as fallback if operational qualification fails (operator brief section 1); execution in Q-*/W-PROMOTE
- [x] Glimmer: DROPPED (operator brief 2026-10-07)
New work made apparent (report section 6):
- [ ] Reasoning-budget sweep 2048/8192 (+12288 if needed)
- [ ] Long-context qualification (32-60K real transcripts); mandatory for Flash-Next (64K fit unverified by llama.cpp)
- [ ] Tool-calling / multi-turn agentic qualification (replay Nexus sessions)
- [ ] Flash-Next mmap n-gram table: page-cache residency and major-fault monitoring
- [ ] Re-qualify the chosen models through the gateway from a remote client (depends on R4 candidate alias pool)
- [ ] Capability fields: reasoning_controllable, reasoning_budget, output_contract_compliance (verified)
- [x] Sequencing proposal: SUPERSEDED by the execution DAG in docs/closeout/00-reconciliation.md, informed by the above (next deliverable)

## Closeout workstream (operator brief 2026-10-07): complete all non-deferred authorized work
Operator confirmation (2026-10-07): all remaining work in this file is authorized for completion, including production worker promotion and the required qualification/deployment/reboot/rollback checks. Only work explicitly marked deferred is excluded.
Reconciliation, classification and execution DAG: docs/closeout/00-reconciliation.md. Designs (each with a review section):
docs/design/01-06.
New findings from the code review (folded into the workstreams):
- [x] N1 finish_reason overwritten (runtime.py hid `length`) → fixed in shared working tree; deployment remains part of W-REASON
- [x] N2 evidence hash chain resets on gateway restart → persisted continuity and strict link verification implemented in shared working tree; deployment remains in R11
- [x] N3 simulated streaming; client disconnect does not stop generation → real upstream SSE and disconnect cancellation implemented in shared working tree; deployment remains in R1/R7
- [x] N4 retired vLLM units/role/scripts still installed; vllm_xpu host 0.0.0.0 in inventory → loopback inventory binding, vLLM role removed from the inference play, and retired units/on-host originators removed via Ansible after archive verification; live service state checked
- [ ] N5 hand-made ufw rules; inference port policy incomplete (8001) → W-ACCESS/W-ORIGIN
- [ ] N6 inventory max_concurrency/context treated as authoritative; eligibility uses estimates → W-LIMITS

## TLS client-compatibility defect (operator-directed 2026-10-07)
The gateway URL is `https://10.0.8.5:8443/v1`; OpenCode config is `/home/mike/.config/opencode/opencode.jsonc`.
Observed original server cert at `/etc/local-ai/orchestrator/tls/gateway.crt` (public copy
`evidence/ai-5820-01/gateway-tls-original-selfsigned-ca-leaf.crt`): SHA-256 `33:BE:41:FD:26:DE:F5:18:57:5D:BD:19:32:52:56:A6:D0:77:AD:FC:53:08:E1:72:B0:EF:B7:0C:82:05:9F:77`;
subject and issuer `CN=ai-5820-01`; Basic Constraints critical `CA:TRUE`; Key Usage and EKU absent; SAN `IP:10.0.8.5,DNS:ai-5820-01`;
valid 2026-10-07 14:40:53Z to 2029-01-09 14:40:53Z. This is a self-signed CA used directly as the TLS server leaf (one certificate served).
OpenCode uses the IP, which matches SAN. TCP and TLS negotiation work; default OS/OpenSSL chain verification fails with self-signed certificate.
Hostname/IP checks and chain verification pass when explicitly given that certificate. The certificate was copied to application config paths,
not installed into `/etc/ssl/certs`; OpenCode standalone ELF is Bun-based (BoringSSL markers), and its running process lacked
`NODE_EXTRA_CA_CERTS`. OpenCode 1.18.35 is installed here (reported issue says 1.18.34). With explicit `NODE_EXTRA_CA_CERTS` using the copied
certificate, OpenCode completed a real authenticated request, confirming additive trust support and locating the original failure at runtime
trust configuration. No verification bypass was used.

Correction deployed: controller-only CA key `/home/mike/.local/share/aihost/pki/ai-5820-01/gateway-ca.key` (mode 0600);
public root `evidence/ai-5820-01/gateway-ca.crt`, SHA-256 `4D:28:6A:BD:F7:1E:86:42:95:4C:56:4F:06:8E:85:CE:8B:ED:2E:F7:C5:74:2B:AB:DF:04:06:DF:2E:32:C6:43`, valid 2026-10-07 through 2036-10-04,
CA:TRUE pathlen 0, keyCertSign+cRLSign. Current leaf `evidence/ai-5820-01/gateway-server.crt` and host path `/etc/local-ai/orchestrator/tls/gateway.crt`,
SHA-256 `35:2D:6F:20:12:91:20:56:D8:06:1E:F8:D6:07:DB:69:56:D4:8C:06:49:92:8D:CE:E3:4E:4F:7E:F5:3C:02:2B`, subject `CN=ai-5820-01`,
issuer `CN=AIHost T5820 Gateway Root CA`, valid 2026-10-07 through 2029-01-09, CA:FALSE, digitalSignature+keyEncipherment,
EKU TLS Web Server Authentication, SAN IP 10.0.8.5 and DNS ai-5820-01. Gateway serves the leaf only; the root is the trust anchor and no intermediate exists.
Ansible installs the public root at `/usr/local/share/ca-certificates/aihost-t5820-gateway-ca.crt`, controller OS trust, and both OpenCode/Nexus client CA paths;
`NODE_EXTRA_CA_CERTS` points to the Nexus CA copy. The original self-signed cert was preserved under an explicit superseded filename.

- [x] Isolate original failure and reproduce diagnostic additive CA trust without disabling verification.
- [x] Design correction: controller-held private CA, CA-signed server leaf with correct SAN, CA:FALSE and serverAuth EKU; CA key never leaves
      the controller; documented in `docs/design/05-remote-origin-only.md`.
- [x] Deploy and verify the generated private CA and leaf through Ansible; publish only the public CA trust anchor and public leaf evidence.
- [x] Install/configure CA trust on the exact remote client and relaunch OpenCode with additive trust; verify OS and runtime trust separately.
- [x] Prove untrusted failure (pre-fix OpenCode returned `self signed certificate`; untrusted Node TLS returns `UNABLE_TO_VERIFY_LEAF_SIGNATURE`);
      configured trust; IP and DNS SAN verification; gateway auth (unauthenticated request 401); OpenAI completion; SSE (`text/event-stream`, events,
      expected text and `[DONE]`); host-origin 403; and remote worker ports 8000/8001/8003 blocked.
- [x] Rotate/redeploy the server leaf and prove trust remains with the unchanged CA; official OpenCode 1.18.34 release binary checksum verified
      (`0f22479647226d1d2dd99595d20082ee7bda3870b62dc6a90b41efc1a71d7e9a`) and completed a real request after rotation. Reapplying Ansible was idempotent.
