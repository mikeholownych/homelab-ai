# aihost closeout: reconciliation of tasks/todo.md against reality

- **Started:** 2026-10-07, from the operator brief "AIHOST: complete all remaining authorized non-deferred work".
- **Starting SHA:** `5ceabf9addd7ef7858fdb7ebd5dd58683307380d` (main == origin/main).
- **Untracked at start:** `tasks/`, `evaluations/engx/`, `docs/defects/`.
- **Out of scope:** Nexus development. The "Future evolution" section of todo.md stays DEFERRED.

Classification: ACTIVE_REQUIRED, SATISFIED_BY_EXISTING_EVIDENCE, SUPERSEDED, DEFERRED_EXPLICITLY, BLOCKED.
Evidence references are to files in this repository or to `ai-5820-01` paths that were inspected on 2026-10-07.

## A. Unchecked items in todo.md

| # | Item (todo.md) | Class | Evidence / reason |
|---|---|---|---|
| 1 | G0 paper screen | SATISFIED_BY_EXISTING_EVIDENCE (except the "--jinja tool calls" clause, which moves to #31) | Revisions pinned in `ai-5820-01:~/engx/fetch-wave1.sh`; licenses Apache-2.0/MIT checked via HF model_info (session 2026-10-06). Tool-call template behaviour was never exercised, so it is carried by Q-TOOLS. |
| 2 | G1 load/smoke at prod flags, VRAM headroom | Load: SATISFIED (`~/engx/logs/server-b-flashnext-gsq-64k.log`: `n_ctx_slot = 65536`; every candidate served 30 task-runs). VRAM headroom: ACTIVE_REQUIRED, folded into Q-LONGCTX | Headroom was never recorded: xpu-smi memory fields returned N/A and llama.cpp could not verify the Flash-Next fit. |
| 3 | G2 llama-bench speed / regression threshold | SUPERSEDED | Replaced by measured per-attempt decode tok/s from instrumented runs (`evaluations/engx/REPORT-2026-10-07.md` serving table). The operator ruled quality over speed (2026-10-06), so no threshold applies. Speed at depth is measured in Q-LONGCTX. |
| 4 | G3 quality | SATISFIED | `evaluations/engx/REPORT-2026-10-07.md`, `~/engx/results/eng-hard-*.json` |
| 5 | G4 promotion via Ansible inventory | ACTIVE_REQUIRED (W-PROMOTE) | Operator authorized the target: lead Qwen3.6-35B-A3B, deep Flash-Next (fallback Qwen3.8-27B). |
| 6 | Baseline incumbents on hard corpus | SATISFIED (stale checkbox) | `~/engx/results/eng-hard-lead-q3coder30b-q4km-nothink.json`, `eng-hard-deep-q35-27b-q4km-nothink.json` |
| 7 | Wave-1 downloads | SATISFIED (stale checkbox) | `ai-5820-01:/var/lib/local-ai/models/gguf/{qwen3.8-27b,muse-glimmer-30b,qwen3.6-35b-a3b,glm-4.7-flash,flashnext-gsq-coder}/`; fetch log `~/engx/logs/fetch-wave1.log` ends with `== DONE` |
| 8 | Execution note: clean up stale `model_selection_controls.serving_model` | ACTIVE_REQUIRED (W-CLEAN) | Still present: `inventory/production/group_vars/inference.yml` names qwen3.8-27b-instruct with TP=2. |
| 9 | engx note "results under /var/lib/aihost/evidence/engx" | SUPERSEDED | The remote-origin policy moves engx to the client side; results are kept client-side and in the repository (W-ORIGIN / Q-*). |
| 10-12 | vllm-top: design, implement, verify | ACTIVE_REQUIRED (W-VTOP) | `vllm-top/src/discover.rs` still matches vLLM cmdlines only and discovers once at startup. |
| 13-17 | Gateway-only access: design, candidate path, Ansible enforcement, detection, verify | ACTIVE_REQUIRED (W-ACCESS) | Gateway runs as `aihost-runtime` (unit template `User={{ orchestrator_gateway_user }}` = host_runtime_account); worker keys are 0400 aihost-runtime; ufw is hand-made (`8000/tcp DENY # AIHost-B0-temporary-api-block`), with no rule for 8001. |
| 18-20 | No work initiated on the aihost: design, remote eval path, enforce + verify | ACTIVE_REQUIRED (W-ORIGIN) | Gateway binds 127.0.0.1:8010. The workstation reaches it through an SSH tunnel (workstation `127.0.0.1:18010` listening). On-host inference originators exist: `roles/benchmarking/files/run_benchmark.py`, `roles/vllm_xpu/files/validate_vllm.py` (`/usr/local/libexec/local-ai-validate-vllm`, `local-ai-run-benchmark`), `tools/t5820_stream_probe.py`, `~/engx/{cand.sh,runqueue.sh,engx.py}`. |
| 21-23 | Dynamic limits: design, implement, remove max_output_tokens | ACTIVE_REQUIRED (W-LIMITS) | `runtime.py:438` estimate is chars/4 over content only; `:499` clamps only a supplied max_tokens; `server.py:155` /v1/models returns ids only. |
| 24-35 | R1-R12 | ACTIVE_REQUIRED (W-R) | Operator approved all 12. None is implemented (code review 2026-10-07). |
| 36 | Defect remediation design | ACTIVE_REQUIRED (W-REASON) | `docs/defects/2026-10-07-unbounded-reasoning-deep-route.md`. Production deep worker has no `--reasoning-budget` (`llama_cpp_container_default_args`). |
| 37 | Choose the budget from bounded data, adding points if needed | ACTIVE_REQUIRED (Q-BUDGET) | REPORT section 3.3: 4096 is binding for Qwen3.8/Qwen3.6/Flash-Next, so 2048 and 8192 points are needed. |
| 38 | Awaiting: defect remediation authorization | SATISFIED (authorized by operator brief 2026-10-07 section 2) | n/a |
| 39 | Awaiting: lead swap to Qwen3.6 | SATISFIED as a decision (brief section 1); execution is in W-PROMOTE | n/a |
| 40 | Awaiting: deep choice | SATISFIED as a decision: Flash-Next, with Qwen3.8 as fallback, gated by qualification | n/a |
| 41 | Awaiting: Glimmer | SATISFIED: DROP (brief section 1) | n/a |
| 42 | Budget sweep 2048/8192 | ACTIVE_REQUIRED (Q-BUDGET) | see #37 |
| 43 | Long-context qualification | ACTIVE_REQUIRED (Q-LONGCTX) | 64K was never filled by engx prompts (REPORT section 1). |
| 44 | Tool-calling / multi-turn qualification | ACTIVE_REQUIRED (Q-TOOLS) | engx is single-shot file output only. Replay inputs: `~/.nexus/sessions/*.json` (read-only). |
| 45 | Flash-Next mmap page-cache monitoring | ACTIVE_REQUIRED (Q-MMAP + monitoring role) | Not implemented. |
| 46 | Re-qualify via gateway from a remote client | ACTIVE_REQUIRED (Q-FINAL) | Depends on W-ACCESS, W-ORIGIN, R4, W-LIMITS. |
| 47 | Capability fields (reasoning_controllable, reasoning_budget, output_contract_compliance) | ACTIVE_REQUIRED (W-LIMITS capabilities) | Not implemented. |
| 48 | Sequencing proposal | SUPERSEDED by the execution DAG below | This document. |

## B. Additional defects found during this reconciliation (code review 2026-10-07)

These are added to todo.md and folded into the named workstream:

| ID | Finding | Workstream |
|---|---|---|
| N1 | The gateway overwrites the provider finish_reason: `runtime.py:584` sets `normalized_finish_reason = "tool_calls" if tool_calls else "stop"`. An output-limit truncation (`length`) reaches the client as a normal stop, which hides budget exhaustion and truncation from clients and telemetry. | W-REASON (telemetry) |
| N2 | Evidence hash chain resets on every gateway restart: `EvidenceStore` starts `previous=None` without reading the persisted file. The chain is not continuous across restarts. | R11 |
| N3 | Streaming is simulated: the upstream call is non-streaming and the gateway emits SSE after completion. A client disconnect does not stop worker generation. | R1 / R7 |
| N4 | Retired vLLM units `aihost-vllm-worker1/2` remain installed. `vllm_xpu` is still in `playbooks/inference.yml` with `vllm_xpu_service_enabled: true`, `vllm_xpu_host: 0.0.0.0`, plus on-host vLLM validate/benchmark scripts. Stale, and a latent direct-access path. | W-CLEAN / W-ORIGIN |
| N5 | The host firewall is hand-made ufw (temporary-block comments), not Ansible-managed. The inference port policy is incomplete (8001 open to RFC1918). | W-ACCESS / W-ORIGIN |
| N6 | The gateway selection treats `max_concurrency` from inventory as authoritative, and `eligible()` uses the estimated context. | W-LIMITS |

## C. Execution DAG (ACTIVE_REQUIRED)

```
W1  commit evaluation artifacts + reconciliation ───────────────────────────────┐
W2  design records (all workstreams, each with a review section) ──────────────┤
                                                                               ▼
W3  gateway foundation: engine adapters, live capacity model, exact tokenizer,
    capability model (DECLARED/VERIFIED), finish_reason pass-through (N1)
        │
        ├──► W-REASON  worker budget (inventory), route reasoning policy (=R8),
        │              gateway default/total bounds, exhaustion telemetry
        ├──► W-LIMITS  admission/queue/429, adaptive concurrency, fit-checked fallback,
        │              client-facing limits/capabilities/headers, /tokenize, mismatch evidence
        │              ─► R9 capability routing
        ├──► R1 cancel ─► R7 deadlines/retries ─► R2 priority/fairness ─► R6 identity/quotas
        ├──► R3 escalation, R10 outcomes, R11 evidence integrity (N2), R12 graceful restart
        └──► R5 drain/safe swap ─► R4 shadow/canary + candidate aliases
                                    │
W-ACCESS  gateway uid, key ownership, nftables skuid on inventory worker ports ◄─┤
W-ORIGIN  remote listener (TLS), local-origin refusal, client allowlist, retire
          on-host originators (N4), remote engx, candidate lifecycle via Ansible ◄┘
W-VTOP    engine-agnostic discovery (independent; consumes the gateway /health schema
          for dedupe and policy violations)
W-CLEAN   stale model_selection_controls, vLLM remnants (N4)
        │
        ▼
Q-BUDGET (2048/8192) ─► choose budget ─► Q-LONGCTX, Q-MMAP, Q-TOOLS, capability VERIFIED
        │  (all remote client → gateway candidate alias)
        ▼
W-PROMOTE lead Qwen3.6, deep Flash-Next (or Qwen3.8 fallback) via Ansible, with rollback
        ▼
Q-FINAL system qualification + reboot + rollback drill ─► todo.md reconciliation ─► closeout
```

Ordering rationale:
- W3 is shared by W-REASON, W-LIMITS and R9 (one capability/limits source of truth).
- R5 precedes R4 and promotion (swaps must drain).
- W-ACCESS and W-ORIGIN must exist before any remote qualification (Q-*). Final qualification must use the real supported path.
- Q-BUDGET must precede promotion (the budget is part of the promoted config).
- Interim containment: the worker-side budget is deployed early on the current deep worker with 4096 (the demonstrated working
  point) as a fail-safe, then replaced by the chosen value at promotion.
