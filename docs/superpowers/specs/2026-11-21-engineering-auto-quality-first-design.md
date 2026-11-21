# Engineering/Auto Quality-First Routing + Seamless Dual-Host Cutover

**Date:** 2026-11-21

**Status:** Spec approved — implementation plan next

**Depends on:**
- `docs/superpowers/specs/2026-11-21-ms-s1-max-production-promotion-design.md` (Phase 3 dual front door / remote ROCm worker)
- Existing gateway intelligence: `orchestrator_runtime/routing.py`, `smart_router.py`, `cais.py`

## Goal

Clients call a **single cluster front door** (`ai-5820-01` gateway) with
`model: "engineering/auto"` (or omit the model) and are routed to the **best-suited**
pool among `lead`, `deep`, and `rocm` by a **quality-first** intelligent router,
with ordered cross-peer failover. Alternatively, clients **pin** an explicit
alias. Monitoring and vllm-top are completed for both hosts so the dual-host
fleet is operable as one cluster.

## Non-Goals

- Requiring CAIS / `X-AIHost-Capability` for every auto request (CAIS remains
  authoritative when present; legacy auto uses `quality_first` without it).
- Removing or renaming existing pin aliases.
- Making the MS-S1 gateway the client front door for `engineering/auto`.
- Silent substitution when a client pins a model that resolves to no worker
  (`policy_denied`, unchanged).
- Qualifying the ROCm profile into the CAIS ledger in this cutover (optional
  follow-on; auto may still select `rocm` via `quality_first` without CAIS).
- Changing gateway *start* readiness so remote rocm is non-blocking (optional
  follow-on; documented only).

## Decisions (operator-approved)

| Topic | Choice |
| --- | --- |
| Router role | Orchestrator gateway is the intelligent model router |
| Client entry | `engineering/auto` or omitted model → auto; else explicit pin |
| ROCm in auto | Full peer — auto may pick lead, deep, or rocm |
| Failover | Cross-peer failover, ordered by best fit |
| Ranking objective | Quality first; latency/load as tie-breakers |
| Front door | Single: `ai-5820-01` gateway only |
| Explicit pins | Keep `engineering/lead`, `deep`, `lead-reasoning`, `interactive-rocm` |
| Approach | `quality_first` strategy on the existing intelligent router |
| Observability | Finish MS-S1 peer monitoring + vllm-top on both hosts |

## Architecture

```
Clients (OpenAI-compatible)
        │
        ▼
 ai-5820-01 gateway  (sole cluster front door)
        │
        ├─ pin alias ──────────────────────────► exact pool (bypass table)
        │
        ├─ X-AIHost-Capability set ────────────► CAIS quality ranking
        │                                         among qualified workers
        │
        └─ engineering/auto / omitted ─────────► quality_first strategy
                                                  rank(lead, deep, rocm)
                                                        │
                              ┌─────────────────────────┼─────────────────┐
                              ▼                         ▼                 ▼
                         lead (local)            deep (local)      rocm (remote
                         Qwen3.6 SYCL           Flash-Next SYCL    HIP Coder-30B
                                                                      on MS-S1)
```

MS-S1 keeps its local gateway for host-local ops and pin traffic; it is **not**
the client auto front door.

## Section 1 — Client contract

- Front door: `ai-5820-01` gateway OpenAI routes (`/v1/chat/completions`, etc.).
- `model: "engineering/auto"` or omitted (when the gateway treats missing model as
  auto) → intelligent choice among lead / deep / rocm. Unknown non-alias model
  names are not auto.
- Pins bypass routing and bind to a pool:
  - `engineering/lead`
  - `engineering/deep`
  - `engineering/lead-reasoning`
  - `engineering/interactive-rocm`
- Optional `X-AIHost-Capability` → existing CAIS evaluate path (default priority
  `quality`); may select a rocm worker only if that profile is qualified and eligible.
- Chosen route is visible via existing evidence and `X-AIHost-Route` (pool + reason).
- Pins never silently land on a different model.

## Section 2 — `quality_first` routing

### Runtime

- Add `quality_first` to `ROUTING_STRATEGIES` in `orchestrator_runtime/routing.py`.
- Behavior when a matched rule has `strategy: quality_first`:
  1. Treat `pool` + `fallback` as an **unordered candidate set**.
  2. Score / sort candidates by ascending rank key:
     1. **Capability / quality fit** — inventory-declared pool quality weights plus
        request shape from `PromptComplexityAnalyzer` (tier + code/reasoning factors).
        Heuristic defaults for this fleet:
        - `complex` / strong reasoning signals → prefer `deep`, then `lead`, then `rocm`
        - code / tool-heavy / interactive → prefer `rocm`, then `lead`, then `deep`
        - `simple` / default → prefer `lead`, then `rocm`, then `deep`
     2. **Complexity match** — pools whose declared strength matches the tier rank higher.
     3. **Live tie-break** — EWMA pool latency from `LatencyTracker`; skip pools with
        open circuit breakers or known unavailability, appending them after healthy peers
        for failover.
  3. Return `pool` = best healthy candidate, `fallback` = remaining candidates in
     ranked order. Existing admission / saturation / attempt failover walks that list.

### Inventory (5820)

- Add a dedicated `quality_first` route rule whose match selects **only**
  auto traffic: `model: [engineering/auto]` and, if the router already treats a
  missing model as auto, the same rule (or a paired rule) for omitted model.
  Candidate set: `lead`, `deep`, `rocm`.
- Do **not** widen the catch-all `default` rule (`match: {}`) to include `rocm` or
  `quality_first` — arbitrary unknown model names must not silently become
  multi-pool auto (R8: only omitted / `engineering/auto` choose freely).
- Do **not** register `engineering/auto` as a model alias (aliases bypass the table).
- Keep existing pin aliases and non-auto rules (`interactive-rocm`, escalate, etc.).
- Pool quality weights for ranking are declarative (inventory or router defaults)
  so operators can retune without code changes.

### Interaction with CAIS

- If the request carries a capability requirement, CAIS remains the authority for
  worker eligibility and ranking among qualified profiles.
- `quality_first` applies to non-CAIS auto traffic and to narrowing pool preference
  before worker admission when CAIS is not engaged.

## Section 3 — Topology, readiness, observability

### Topology

- Sole client front door: `ai-5820-01`.
- Remote worker `ms-s1-hip-coder30b` remains in the 5820 worker list (`pool: rocm`).
- MS-S1 local gateway stays for ops / local pins; not required for client auto.

### Readiness

- Gateway readiness continues to observe configured workers, including remote rocm.
- A down remote worker reduces auto capacity; ranked failover still serves Intel pools.
- Making remote rocm non-blocking for gateway *process start* is explicitly out of
  scope for this cutover.

### Monitoring

- Phase 3 already enabled MS-S1 node scrape and reconcile targeting; this cutover
  **verifies** those paths and closes gaps only where missing: dashboard panels
  for the `rocm` pool and auto complexity / route metrics (`aihost_requests_by_complexity_tier_total`,
  route decision visibility), and confirm Alloy/reconcile timers are healthy.

### vllm-top

- Enable `vllm_top_console_enabled` on MS-S1 (already true on 5820).
- 5820 console reflects gateway-known workers including remote rocm; MS-S1 shows
  local HIP worker state.

## Section 4 — Validation, rollout, success criteria

### Tests

- Unit: `quality_first` ranking by complexity/code/reasoning; unhealthy preferred
  pool → next best fit; pins still bypass; strategy rejected if misspelled.
- Contract: 5820 inventory exposes auto candidates covering lead/deep/rocm; pin
  aliases unchanged.

### Live probes (5820 front door)

- Auto simple/interactive → prefers lead or rocm (not deep unless only healthy).
- Auto code/tool-heavy → may select rocm.
- Auto complex/reasoning → prefers deep.
- Pins still hit exact pools.
- With rocm unavailable, auto still completes via Intel failover.

### Observability checks

- MS-S1 metrics scraped; dashboards show rocm + auto complexity tiers; reconcile
  timer present; vllm-top active on both hosts.

### Rollout

1. Implement runtime + tests; bump gateway release id on 5820.
2. Inventory: auto `quality_first` rule + pool weights; MS-S1 vllm-top + obs/reconcile gaps.
3. Gateway quality gate + targeted pytest.
4. Ansible deploy 5820 gateway and MS-S1 obs/vllm-top.
5. Live probes; open PR.

### Success criteria

- One client URL for the cluster.
- `engineering/auto` quality-first routes across lead/deep/rocm with ordered failover.
- Explicit pins unchanged and hard.
- Monitoring and vllm-top complete on both hosts.

## Error handling

| Condition | Behavior |
| --- | --- |
| Pin to unknown / empty pool | Existing `policy_denied` / no silent substitute |
| All candidate pools unavailable | Existing capacity / worker unavailable errors |
| Preferred pool saturated | Walk ranked fallback (`fallback_on_saturation` as configured) |
| Circuit breaker open on preferred | Skip to next ranked healthy candidate; broken pool remains later in fallback |
| CAIS deny | Existing CAIS failure classes unchanged |

## Components touched (expected)

| Area | Touch |
| --- | --- |
| `orchestrator_runtime/routing.py` | `quality_first` strategy |
| `orchestrator_runtime/smart_router.py` | Optional helpers for quality weights / fit score |
| `tests/` | Ranking + inventory contract tests |
| `inventory/production/host_vars/ai-5820-01.yml` | Auto rule, pool weights, release bump |
| `inventory/production/host_vars/ai-ms-s1-max-01.yml` | vllm-top enable |
| Observability dashboards / host_vars | Verify MS-S1 scrape + reconcile; add rocm/auto panels if missing |
| Gateway release artifact | Deploy bumped release to 5820 |

## Out of scope follow-ons

- CAIS qualification grant for the HIP Coder-30B execution profile.
- Non-blocking gateway start when remote rocm is down.
- Deprecating the MS-S1 client-facing gateway entirely.
