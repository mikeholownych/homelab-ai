# aihost closeout: reconciliation of tasks/todo.md against reality

- **Started:** 2026-10-07, from the operator brief "AIHOST: complete all remaining authorized non-deferred work".
- **Starting SHA:** `5ceabf9addd7ef7858fdb7ebd5dd58683307380d` (main == origin/main).
- **Untracked at start:** `tasks/`, `evaluations/engx/`, `docs/defects/`.
- **Out of scope:** Nexus development. The "Future evolution" section of todo.md stays DEFERRED.
- **Execution authorization:** On 2026-10-07 the operator explicitly directed completion of all remaining `tasks/todo.md` work, leaving only clearly deferred work undone. This includes the qualification gates and production promotion after those gates pass; it supersedes earlier approval uncertainty and "no production change without separate authorization" wording in historical defect notes.

Classification: ACTIVE_REQUIRED, SATISFIED_BY_EXISTING_EVIDENCE, SUPERSEDED, DEFERRED_EXPLICITLY, BLOCKED.
Evidence references are to files in this repository or to `ai-5820-01` paths that were inspected on 2026-10-07.

## A. Unchecked items in todo.md

| # | Item (todo.md) | Class | Evidence / reason |
|---|---|---|---|
| 1 | G0 paper screen | SATISFIED_BY_EXISTING_EVIDENCE (except the "--jinja tool calls" clause, which moves to #31) | Revisions pinned in `ai-5820-01:~/engx/fetch-wave1.sh`; licenses Apache-2.0/MIT checked via HF model_info (session 2026-10-06). Tool-call template behaviour was never exercised, so it is carried by Q-TOOLS. |
| 2 | G1 load/smoke at prod flags, VRAM headroom | Load: SATISFIED (`~/engx/logs/server-b-flashnext-gsq-64k.log`: `n_ctx_slot = 65536`; every candidate served 30 task-runs). VRAM headroom: ACTIVE_REQUIRED, folded into Q-LONGCTX | Headroom was never recorded: xpu-smi memory fields returned N/A and llama.cpp could not verify the Flash-Next fit. |
| 3 | G2 llama-bench speed / regression threshold | SUPERSEDED | Replaced by measured per-attempt decode tok/s from instrumented runs (`evaluations/engx/REPORT-2026-10-07.md` serving table). The operator ruled quality over speed (2026-10-06), so no threshold applies. Speed at depth is measured in Q-LONGCTX. |
| 4 | G3 quality | SATISFIED | `evaluations/engx/REPORT-2026-10-07.md`, `~/engx/results/eng-hard-*.json` |
| 5 | G4 promotion via Ansible inventory | SATISFIED (W-PROMOTE) | Commit `998189a` pins Qwen3.6-35B-A3B lead and Flash-Next deep artifacts, budgets and qualification evidence; production was re-converged after the rollback drill. See `evaluations/engx/QUALIFICATION-QFINAL-2026-10-09.md`. |
| 6 | Baseline incumbents on hard corpus | SATISFIED (stale checkbox) | `~/engx/results/eng-hard-lead-q3coder30b-q4km-nothink.json`, `eng-hard-deep-q35-27b-q4km-nothink.json` |
| 7 | Wave-1 downloads | SATISFIED (stale checkbox) | `ai-5820-01:/var/lib/local-ai/models/gguf/{qwen3.8-27b,muse-glimmer-30b,qwen3.6-35b-a3b,glm-4.7-flash,flashnext-gsq-coder}/`; fetch log `~/engx/logs/fetch-wave1.log` ends with `== DONE` |
| 8 | Execution note: clean up stale `model_selection_controls.serving_model` | SATISFIED_IN_WORKING_TREE | `inventory/production/group_vars/inference.yml` now leaves the unselected model and TP unset; inventory assertions were updated. |
| 9 | engx note "results under /var/lib/aihost/evidence/engx" | SUPERSEDED | The remote-origin policy moves engx to the client side; results are kept client-side and in the repository (W-ORIGIN / Q-*). |
| 10-12 | vllm-top: design, implement, verify | SATISFIED (W-VTOP) | v1.0.2 discovery and policy-violation display; v1.0.2 live checks covered ad-hoc server appearance, stopped state, deduplication, expiration and no gateway monitoring-port probes. Dynamic gateway worker state is reconciled every health poll and v0.10.2 is live. See the checked items in `tasks/todo.md`. |
| 13-17 | Gateway-only access: design, candidate path, Ansible enforcement, detection, verify | SATISFIED (W-ACCESS) | Inventory-derived nftables enforcement runs before workers; gateway uid 995 alone can connect to 8000/8001. Direct connects as mike/root/aihost-runtime were refused and the denial counter increased. Remote candidate qualification and vllm-top detection were exercised; remote probes to 8000/8001/8003 were refused. |
| 18-20 | No work initiated on the aihost: design, remote eval path, enforce + verify | SATISFIED (W-ORIGIN) | On-host originators were archived and retired. The remote TLS gateway denies host-origin workload; local monitoring remains available. Q-BUDGET, Q-TOOLS, Q-LONGCTX and Q-FINAL ran from the remote controller using Ansible-managed candidate aliases. |
| 21-23 | Dynamic limits: design, implement, remove max_output_tokens | SATISFIED (W-LIMITS) | Design 01 is accepted; engine observation, exact/fallback tokenization, finite bounds, fit checks, admission/429, AIMD, mismatch evidence, client limits and `/v1/tokenize` are implemented and covered by gateway tests. Cleanup commit `159898f` removes obsolete record/inventory fields; release `t5820-gateway-159898f` was deployed and a fresh OpenCode production request returned `READY`. No fixed output-token default remains. |
| 24-35 | R1-R12 | IMPLEMENTED, TESTED, DEPLOYED; LIVE-VERIFIED WITH ENGINE LIMITS | Design 03 is accepted. The `f31218c` gateway release contains R1-R12; the full `make test` run passed (1,141 passed, 16 skipped). Production exercised TLS/SSE, candidate drain/swap, route reasoning/capabilities, quotas/auth boundaries and reboot/restart. The deployed production engine is llama.cpp; vLLM adapter/cancellation paths are fixture-tested only because no vLLM worker is deployed. |
| 36 | Unbounded reasoning remediation design and production config | SATISFIED (W-REASON) | Design 02 is accepted. Lead and deep workers now have evidence-backed server budgets 8192/4096; route policy and finite completion bounds are enforced by the deployed gateway, covered by Q-BUDGET and gateway tests. |
| 37 | Choose the budget from bounded data, adding points if needed | SATISFIED (Q-BUDGET) | Flash-Next selects 4096; Qwen3.6 selects 8192 under quality-over-speed. Both 2048/4096/8192 sweeps completed through the remote TLS gateway. `evaluations/engx/QBUDGET-2026-10-08.md`. |
| 38 | Awaiting: defect remediation authorization | SATISFIED (authorized by operator brief 2026-10-07 section 2) | n/a |
| 39 | Awaiting: lead swap to Qwen3.6 | SATISFIED as a decision (brief section 1); execution is in W-PROMOTE | n/a |
| 40 | Awaiting: deep choice | SATISFIED as a decision: Flash-Next, with Qwen3.8 as fallback, gated by qualification | n/a |
| 41 | Awaiting: Glimmer | SATISFIED: DROP (brief section 1) | n/a |
| 42 | Budget sweep 2048/8192 | SATISFIED (Q-BUDGET) | Flash-Next and Qwen3.6 sweeps at 2048/4096/8192 complete; see `evaluations/engx/QBUDGET-2026-10-08.md`. |
| 43 | Long-context qualification | SATISFIED (Q-LONGCTX) | Flash-Next passed through 59K; Qwen3.6 passed through 55,833 exact prompt tokens with 8,192 reasoning budget and correctly rejected 67,327 tokens. Qualification JSON and reports retained under `evaluations/engx/`. |
| 44 | Tool-calling / multi-turn qualification | SATISFIED (Q-TOOLS) | Both selected models passed all seven synthetic categories and 20/20 read-only Nexus replay cut points through the remote TLS gateway; see qualification reports under `evaluations/engx/`. |
| 45 | Flash-Next mmap page-cache monitoring | SATISFIED (Q-MMAP + monitoring role) | Worker major-fault and GGUF page-cache snapshots bracketed qualification; `evaluations/engx/results/qmmap-20261008/` and Flash-Next report. |
| 46 | Re-qualify via gateway from a remote client | SATISFIED (Q-FINAL) | Both selected models completed candidate Q-BUDGET/Q-TOOLS/Q-LONGCTX and passed authenticated production-alias inference after reboot and after rollback restoration; see the Q-FINAL report. |
| 47 | Capability fields (reasoning_controllable, reasoning_budget, output_contract_compliance) | SATISFIED for selected artifacts | `/v1/models` after final re-convergence reports digest-matched verified reasoning control, output-contract, tools and streaming evidence for both promoted production artifacts. |
| 48 | Sequencing proposal | SUPERSEDED by the execution DAG below | This document. |
| 49 | Q-FINAL production promotion, reboot and rollback | SATISFIED_WITH_RECORDED_LIMITATIONS | The controlled reboot, GPU enumeration, worker/gateway health and both production aliases passed after adding a `Requires=user-runtime-dir@UID.service` dependency. The generic validator still has 22 `NOT_TESTED` checks. A revert/re-converge rollback served both prior models, but the pre-promotion deep model returned 422 on its default reasoning route and served only with explicit reasoning off. See `evaluations/engx/QUALIFICATION-QFINAL-2026-10-09.md`. |

## B. Live gateway cutover (2026-10-07)

- OpenCode provider `t5820` uses `https://10.0.8.5:8443/v1`. The original self-signed CA:TRUE certificate was used directly as a leaf, copied only to app config paths, and absent from OS trust; the existing OpenCode process had no additive CA environment. Ansible now creates a controller-held private CA, installs a SAN/EKU-constrained leaf, and deploys only the public root to the gateway controller, OS trust and configured client paths. OpenCode 1.18.34 (official binary SHA-256 verified) completed a real authenticated request after a live leaf rotation; native SSE and trust-negative checks also passed. A dated backup of the prior client config remains in the user's config directory. The old user tunnel unit is disabled.
- Ansible applied `users`, `inference_policy`, and `orchestrator` roles only. This avoided reapplying unrelated roles that would recreate scheduled benchmark units. Gateway uid is 995; the gateway and both llama worker services are active.
- nftables allows remote gateway traffic from `10.0.8.95/32`, rejects local non-gateway connections to worker ports, drops non-loopback worker traffic, and counts denials. Probes as `mike`, `root`, and `aihost-runtime` to worker ports 8000 and 8001 were refused; a TCP connect as `aihost-gateway` succeeded.
- Authenticated remote `/v1/models` and `/v1/chat/completions` returned HTTP 200; the chat response was `OK`. A host-origin authenticated chat request returned HTTP 403. Local `/health` and `/metrics` returned HTTP 200; the `vllm-top-console.service` is active.
- Gateway evidence was moved to `/var/lib/aihost-gateway/t5820-gateway-persistent.jsonl` because the previous shared evidence directory was inaccessible to the isolated service identity. The migration preserves the full original file as a byte prefix and leaves source and intermediate copies intact. Verification reports preexisting `previous_hash` breaks beginning near line 4329; chain integrity remains unresolved.
- Two rollout corrections were required: use Ansible's `regex_search` filter correctly, and load the TLS certificate through systemd credentials so the service does not traverse the protected `/etc/local-ai` tree. Focused tests, role lint, and playbook syntax validation pass after these corrections.

## C. Additional defects found during this reconciliation (code review 2026-10-07)

Gateway startup correction during the 2026-10-07 rollout:
- The first restart failed because the service account could not traverse `/etc/local-ai` to read the new client registry. That parent is deliberately protected from the isolated gateway uid.
- The registry contains token digests only; its Ansible destination is now `/var/lib/aihost-gateway/clients.json`, inside the service's private state directory. Plaintext client tokens remain root-only under `/etc/local-ai/orchestrator/clients/` and reach workers through systemd credentials.
- Deployment is incomplete until Ansible is re-applied and remote TLS `/health`, authenticated `/v1/models`, and systemd readiness pass.

These are added to todo.md and folded into the named workstream:

| ID | Finding | Workstream |
|---|---|---|
| N1 | The gateway overwrote provider `finish_reason`; an output-limit truncation (`length`) reached the client as a normal stop. | W-REASON; fixed, tested and included in the deployed `f31218c` release. |
| N2 | Evidence hash chain reset and permissive chain-break verification. | R11; persisted-chain continuation and strict link validation are tested and included in the deployed `f31218c` release. Existing legacy chain breaks remain preserved and are not represented as repaired. |
| N3 | Streaming was simulated and disconnects did not stop worker generation. | R1 / R7; upstream SSE and disconnect cancellation are tested and included in deployed `f31218c`; production SSE is verified. Live forced-disconnect proof is not separately recorded. |
| N4 | Retired vLLM units `aihost-vllm-worker1/2` were installed. `vllm_xpu` was still in `playbooks/inference.yml`; on-host vLLM validate/benchmark scripts remained. Inventory now binds vLLM to loopback, the vLLM role is removed from the inference play, and Ansible removed the retired units and originators after archive verification. | W-CLEAN / W-ORIGIN |
| N5 | The host firewall had hand-made ufw rules; 8001 was not covered by the temporary deny. | SATISFIED: Ansible installs inventory-derived nftables policy for worker and candidate ports, including 8001, before workers start. It retires the superseded UFW temporary denies. Live non-gateway probes to 8000/8001/8003 were refused. |
| N6 | The gateway selection treated `max_concurrency` from inventory as authoritative, and `eligible()` used estimated context. | SATISFIED by W-LIMITS: engine-observed capacity governs eligibility and concurrency; mismatch evidence, exact counting and bounded admission are covered by tests and the deployed `f31218c` release. |

## D. Execution DAG (CLOSED WITH RECORDED LIMITATIONS)

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
