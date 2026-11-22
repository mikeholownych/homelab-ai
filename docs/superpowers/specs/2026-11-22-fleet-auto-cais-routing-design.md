# Fleet Auto Routing + Live CAIS Qualifications

**Date:** 2026-11-22

**Status:** Draft for operator review

**Depends on:**
- `docs/superpowers/specs/2026-11-21-engineering-auto-quality-first-design.md`
- `docs/design/07-capability-aware-scheduling.md`
- `docs/operations/cais.md`

## Goal

Unpinned client traffic on the single front door (`ai-5820-01`) is routed to the
**best-suited healthy peer** among **lead, deep, and rocm**. Capability requests
under CAIS `enforce` can select any production peer that holds a **live-matching
qualification**. A down or unqualified remote peer never blocks routing to peers
that are up and eligible.

## Non-Goals

- Changing hard pin aliases (`engineering/lead`, `deep`, `lead-reasoning`,
  `interactive-rocm`) or allowing silent pin substitution.
- Multi-provider / cloud marketplace routing.
- Semantic cache, PII redaction product features.
- Making the MS-S1 gateway the client front door.

## Decisions

| Topic | Choice |
| --- | --- |
| Unpinned traffic | Omitted model, `engineering/auto`, and the catch-all `default` rule all use `quality_first` over `{lead, deep, rocm}` |
| Simple / medium / unknown shape | Single fit band `{lead, deep, rocm}` ordered by quality weight then latency (no lead-first demotion of rocm) |
| Complex / reasoning-heavy | Prefer `deep`, then `{lead, rocm}` |
| Code / tools | Prefer `deep`, then `lead`, then `rocm` (coding CAIS on deep/lead; rocm primary is general/visual, coding-optional) |
| Pins | Unchanged; bypass the table |
| Availability | Healthy peers only for primary selection; open-breaker / unhealthy peers trail for failover; gateway stays `ready` when any worker is healthy (already) |
| CAIS mode | Keep `enforce` |
| Qualifications | Every production worker must have **fresh, grantable** evidence for the capabilities its **role** expects; ledger grants must match **current** `profile_identity` (artifact + runtime image + hardware_class + topology + reasoning budget) |
| Capability set (this change) | **deep:** live `coding.routine` + `coding.complex` grants (coding specialist). **lead:** at least `coding.routine` after capability-mix cutover (orchestrator floor, not coder-first). **rocm primary:** general/visual tenant — **no** coding CAIS required (OCR/img bolt-ons are separate, not coding capabilities) |

## Current gaps (verified 2026-11-22)

1. **Inventory routing:** `default` is `lead → deep` only (no rocm). `quality_first` simple band is lead-first.
2. **CAIS mode:** already `enforce` and `valid: true` on the live gateway.
3. **Live qualifications:** only one ledger grant — `coding.routine` for Flash-Next (deep) under runtime image
   `sha256:2f494061…`. Production workers now declare runtime `sha256:6cd97c37…`. Stale grants do not satisfy
   “actual qualified profiles” for the live fleet.
4. **On-disk results:** lead `coding.routine` / `coding.complex` bundles exist under `evaluations/cais/results/` but
   `cais_cli assess` returns `qualified: false` (confidence / infra thresholds). They must not be granted.
5. **ROCm primary:** post capability-mix cutover, the general text tenant (`Qwen3.8-27B` on MS-S1) does not require coding CAIS; legacy Coder-30B lacked grants and is replaced — not a blocker for fleet-auto once Section 1 lands.

## Architecture

```
Client (Nexus / OpenCode / …)
        │
        ▼
 ai-5820-01 gateway
        │
        ├─ pin alias ──────────────────────────────► exact pool
        │
        ├─ X-AIHost-Capability set ───────────────► CAIS evaluate
        │     among workers whose live profile_digest
        │     has a qualified grant for that capability
        │     then quality / latency among eligible
        │
        └─ omitted / engineering/auto / other unpinned
              ─────────────────────────────────────► quality_first
                    candidates = {lead, deep, rocm}
                    skip unhealthy; failover ordered by fit
```

## Section 1 — Unpinned routing

### Behavior

- Omitted / blank model continues to normalize to `engineering/auto` (existing).
- `engineering-auto` rule: `strategy: quality_first`, `pool: lead`,
  `fallback: [deep, rocm]`, `fallback_on_saturation: true` (candidate set is the
  union; order comes from ranking).
- `default` (`match: {}`): **same** strategy and candidate set as `engineering-auto`
  so unknown non-alias model names are not a second, weaker policy.
- `preferred_pool_bands`:
  - complex / reasoning ≥ 0.3 → `[["deep"], ["lead", "rocm"]]`
  - tools or code ≥ 0.2 → `[["deep"], ["lead", "rocm"]]` (prefer coding-qualified peers)
  - else → `[["lead", "deep", "rocm"]]` (one band; weights + latency only)
- Circuit-open / unavailable pools are ranked after healthy ones (existing
  `quality_first` behavior). Admission/`_eligible` continue to refuse drained or
  identity-mismatched workers.

### Inventory / tests

- Update `ai-5820-01.yml` routes and any contract tests that assert `default`
  excludes rocm or encode lead-first simple bands.
- Keep pin aliases and the dedicated `interactive-rocm` rule.

## Section 2 — Live CAIS qualifications (required in this change)

“CAIS-on” is not a mode flip. Success means **`GET /v1/cais` lists qualified
grants whose `profile_digest` matches each live production worker** for the
capabilities below.

### Required matrix

| Worker | Pool | Capabilities that must end qualified (or documented fail-closed) |
| --- | --- | --- |
| `b0-live-llama-worker1` (post capability-mix) | lead | **`coding.routine` required** (orchestrator floor); `coding.complex` optional if a fresh run meets criteria |
| `b0-live-llama-deep-worker2` | deep | **`coding.routine` + `coding.complex` required** on **current** runtime digest (live coding specialist) |
| `ms-s1-hip-*` (rocm primary, post capability-mix) | rocm | **None required** for coding CAIS — general/long-context text; OCR/img bolt-ons are out of band for this matrix |

A peer that fails assess remains **unqualified** for that capability (fail-closed).
It stays in legacy `quality_first` candidate sets but **must not** win CAIS
capability routing for that class.

### Procedure (per docs/operations/cais.md)

For each row in the matrix:

1. Build `profile.json` from the **live** inventory worker record (current
   `artifact_digest`, `runtime_image_digest`, `hardware_class`, `topology`,
   `reasoning_budget`, and the pin alias’s reasoning policy).
2. Run `evaluations/cais/run_qualification.py` through the front door with the
   pin that resolves to exactly that worker (`engineering/lead`,
   `engineering/deep`, and `engineering/interactive-rocm` only when re-validating
   a coding-shaped rocm alias — not required for the general rocm primary).
3. `rescore` the result; `cais_cli assess` must report `qualified: true` before
   any grant.
4. `cais_cli grant` into `inventory/production/cais/` (bundle + ledger line).
5. Deliver via gateway role / reconcile; confirm `GET /v1/cais` shows the new
   `qualification_id` with `state: qualified` and that a capability request can
   select that worker (`X-AIHost-Qualification-Id`).

### Stale grant cleanup

- Re-qualify deep on the current runtime image even though an older
  `coding.routine` grant exists.
- Do not grant historical lead bundles that assess `qualified: false`.
- After new grants land, revoke or leave superseded stale digests inert (they
  no longer match live workers).

## Section 3 — Client / agent path

- Unpinned Nexus / OpenCode traffic benefits immediately from Section 1.
- Capability-aware selection requires `X-AIHost-Capability` (e.g.
  `coding.routine`). Enabling that header on coding sessions is in scope so CAIS
  is exercised in production agent traffic, not only by curl.
- Pins remain available for operators who need a hard peer.

## Section 4 — Validation

| Check | Pass criteria |
| --- | --- |
| Route unit tests | `default` and `engineering/auto` share all-three `quality_first`; simple band is one band |
| Contract tests | Inventory routes/weights match the decisions table |
| Live `/health` | Three workers registered; `ready` true with any subset healthy |
| Live `/v1/cais` | `mode=enforce`, `valid=true`; **deep** holds live `coding.routine` + `coding.complex`; **lead** holds at least `coding.routine` after cutover; **rocm primary** may have zero coding grants |
| Capability probe | `X-AIHost-Capability: coding.routine` lands on **deep** and/or **lead** when qualified; rocm primary is not required to participate |
| Failover | Stop or break rocm → unpinned traffic continues on lead/deep without gateway `ready=false` |
| Pin | `engineering/interactive-rocm` still binds only to rocm |

## Section 5 — Rollout

1. Land inventory + router band changes; converge 5820 gateway; bump reconcile snapshot so hourly reconcile cannot regress routes.
2. Run CAIS qualifications for **deep** (routine + complex) and **lead** (routine minimum) against live pins; grant only `qualified: true` bundles; deliver ledger. **Skip** coding qualification for rocm primary unless an optional coding alias is introduced later.
3. Enable / confirm agent `X-AIHost-Capability` on coding workloads.
4. Verify Section 4 checks; leave reconcile timers enabled only after snapshot includes this commit.

## Success criteria

- Unpinned work is selected across **all three** production pools by fit, not by “prefer 5820.”
- Remote unavailability does not take down routing to healthy local peers.
- CAIS `enforce` is backed by **real, current** coding grants on **deep** (routine + complex) and **lead** (routine minimum); rocm primary remains eligible for unpinned `quality_first` without coding qualifications.
