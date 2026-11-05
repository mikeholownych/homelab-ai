# Design 07: capability-aware inference scheduling (CAIS)

- **Status:** IMPLEMENTED, TESTED_LOCAL, independently reviewed (same model family, section 13). Not deployed.
  `orchestrator_gateway_cais_mode` is `off` in every inventory.
- **Date:** 2026-11-05.
- **Branch:** `feat/cais`.
- **Requirement:** models earn, keep and lose eligibility for classes of work through evidence. Model identity, size,
  public benchmarks or the model's own claims are never enough. The gateway enforces eligibility in its routing path,
  fails closed, and leaves today's routing unchanged until enforcement is explicitly enabled.
- **Operations:** [docs/operations/cais.md](../operations/cais.md).

## 1. Current state (Phase 0, verified 2026-11-05 against `fb4089d`)

Each finding is graded VERIFIED (code, config or test), INFERRED or UNKNOWN. Live host state was not inspected: this
work stays on the controller and sends no inference.

| # | Finding | Grade |
|---|---|---|
| 1 | One production host, `ai-5820-01`, with two llama.cpp SYCL workers. **lead**, GPU 0: `Qwen3.6-35B-A3B-UD-Q4_K_M`. **deep**, GPU 1: `Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M` (2 shards). Both run 65,536 context, `-np 1`, `max_concurrency: 1` (`inventory/production/host_vars/ai-5820-01.yml:396-443`). The brief's Qwen3-Coder-30B / Qwen3.5-27B pair is out of date: Qwen3.5-27B survives only as a rollback target with capability evidence and no worker. | VERIFIED |
| 2 | Workers are static inventory records (`ORCHESTRATOR_WORKER_SPECS`). There is no discovery or registration API. The lead worker's `public_model_id` is `engineering/b0`; `engineering/lead`, `engineering/deep` and `engineering/lead-reasoning` are aliases. | VERIFIED |
| 3 | Request lifecycle, all inside `OrchestratorRuntime.complete()`: guardrails → shape → RBAC/quotas → response cache → route (pin, alias, or first-match rule table with fallback/canary) → `_eligible()` (status, `valid_until`, inventory labels, drain, capacity/identity block, circuit breaker, API-feature needs) → `_plan` (reasoning policy, exact token count, context fit) → admission (per-worker slots, priority queue, deadline) → `_dispatch` (one pre-generation retry). `_eligible()` is the single filter that pins, fallbacks, canaries and retries all pass through. | VERIFIED |
| 4 | Capability concepts already present: (a) API features (`tools`, `structured_output`, `reasoning`, ...) with declared/verified provenance, keyed by artifact sha256 and enforced per request (`capabilities.py`, `capacity.py:168`); (b) free-form inventory labels (`coding`, `review`, ...) that are asserted, not evidenced, and gate only `navigation`. Neither is a class of engineering competence. | VERIFIED |
| 5 | Model identity: inventory declares `artifact_digest`, `runtime_image_digest`, `revision`. At runtime the gateway compares only the engine-reported model **alias** (`capacity.py:122`). No code hashes the GGUF on disk at deploy or at runtime. The digest is a declared string, re-verified by hand when written. | VERIFIED |
| 6 | Evidence infrastructure: a hash-chained JSONL evidence store whose head is anchored to the journal (`evidence.py`); client-reported outcomes attributed by client (`report_outcome`); the engx corpus (12 base + 10 hard tasks, hidden pytest oracles, bubblewrap, temperature 0, corpus digest); `qualify.py` protocol checks (3 trials, 100%). | VERIFIED |
| 7 | Phases 11–13 hold a richer qualification state machine, a task-class taxonomy and binomial statistics. They are sealed history (manifests), target the retired vLLM workers, and are imported by nothing live. | VERIFIED |
| 8 | Gateway service: user `aihost-gateway`, `ProtectSystem=strict`, writable only in `StateDirectory=/var/lib/aihost-gateway`. Configuration arrives through a root-owned env file. Releases are immutable and identified by commit (`test_gateway_release_identity`). Activation is journaled with automatic recovery. Production runs the **`asgi`** engine (`asgi.py`, Uvicorn; `orchestrator_gateway_engine: asgi` in host_vars overrides the role default `sync`). Both engines implement the CAIS contract and are tested. (Corrected 2026-11-05: the first assessment said `sync`, from the role default.) | VERIFIED |
| 9 | Admission rejects with 429 (queue full) or 504 (deadline). A healthy worker can still be inadmissible (drained, capacity unknown, identity mismatch, breaker open). | VERIFIED |
| 10 | Nexus integration contract: no document in this repository. Nexus is a gateway client with `workload` scope and the `X-AIHost-*` headers. | INFERRED |
| 11 | Whether the deployed release still matches `t5820-gateway-e1ef079868d9`. | UNKNOWN (host not inspected) |

**Gaps:**
- No definition of a class of work.
- No evidence-to-eligibility binding beyond API features.
- No revocation other than editing inventory.
- No fail-closed path for "this request needs a proven model".
- The context window is treated as a configuration value rather than a measured property.

## 2. Architecture

```
            Git (reviewed)                                 controller                        ai-5820-01
 inventory/production/cais/                     evaluations/cais/run_qualification.py   /var/lib/aihost/cais (RO, root)
   capabilities.json  (versioned criteria)  <--  engx corpus via gateway (pinned alias)       |
   ledger.jsonl       (hash-chained grants)  <-- cais_cli grant/revoke (no --force)          |  Ansible copy + SIGHUP
   bundles/*.json     (raw evidence)                                                          v
                                                                          gateway: CaisService.build_snapshot()
                                                                            re-verify sha256 + profile + criteria
   /var/lib/aihost-gateway/cais-suspensions.jsonl (gateway-writable,         re-assess raw trials
        suspend/revoke ONLY) + cais-ledger-heads.json (anti-rollback, both)  -> immutable snapshot
                                                                                       |
 client --X-AIHost-Capability--> complete() -> CaisService.evaluate() --candidates--> _eligible() ∩ candidates
                                                 deny: stable failure_class            -> admission -> re-check -> dispatch
```

The logical components are modules in the existing gateway process, not new services:

| Component | Where | Owns |
|---|---|---|
| Capability registry | `capabilities.json` (`CapabilityCatalog`) | Versioned classes and their criteria |
| Model registry / execution profile | `WorkerRecord` + `profile_identity()` | Identity a qualification binds to |
| Qualification engine | `run_qualification.py` → `assess_bundle()` → `cais_cli grant` | Evidence production and decision |
| Qualification state | `build_snapshot()` over two ledgers | Effective state per qualification |
| Routing/admission gate | `runtime.complete()` + `CaisService.evaluate()` | Enforcement, ranking, denial, evidence |
| Revocation | `cais_cli revoke` (authoritative); admin API (gateway ledger) | Removal, durable |

Control plane versus execution plane is unchanged. Workers only generate tokens. Nexus keeps task decomposition and
final acceptance: it may send a capability header and report outcomes, but it cannot create or change qualification
state.

## 3. Execution-profile identity and scope (§1.2)

`profile_identity(worker)` is the tuple {`model_id`, `artifact_digest`, `runtime_image_digest`, `engine`, `topology`,
`hardware_class`, `reasoning_budget`}. A qualification binds that digest plus four further scopes:
- the capability **and its version**;
- the **reasoning policy** it was evidenced under (applied to every request it serves; client reasoning overrides are
  ignored on capability requests);
- the **context envelope** the trials actually exercised;
- the **suite version** (corpus digest, attempts, max tokens).

| Change | Effect |
|---|---|
| New GGUF, re-quantisation, new runtime image, new engine, other hardware class, other worker reasoning cap | New profile, unqualified |
| Capability definition version bumped | Grant `superseded`, requalify |
| Same artifact + image + engine + topology + hardware class on another GPU, port or worker id | **Equivalent** (placement excluded by design) |
| Worker context lowered below the envelope | Usable envelope = min(envelope, worker context) |
| Request needs more context than the envelope | `context_unsupported` |

`hardware_class` is declared per worker in inventory (`intel-arc-pro-b65-32g`), never inferred. A future AMD
unified-memory or NVIDIA node is a different class: its profiles start unqualified and need their own evidence. No
platform is hard-coded.

## 4. Capability classes (§4.2)

Defined: **`coding.routine`** (engx base, 12 tasks) and **`coding.complex`** (engx hard, 10 tasks). Both are measured
by executable hidden tests run in a sandbox, at most 3 attempts with test feedback.

Deliberately **not defined yet**, because no defensible measurement exists in this repository:
- `debugging.*` and `refactoring.large`: 1–3 engx tasks each; a per-discipline split is statistically meaningless.
- `review.code`, `review.architecture` and `review.security`: no oracle for review quality. A second model agreeing is
  not one.
- `reasoning.extended`: no suite.
- `tool_use.reliable`: `qualify.py` checks the protocol, not recovery after tool failures.
- `context.long`: the needle suite exists. An envelope is per qualification; a standalone class is redundant.

Each needs a versioned suite with an oracle before it can be added. Unknown capability strings are rejected
(`capability_unknown`). Clients cannot define classes.

## 5. Evidence, assessment and statistics (§5)

A bundle (`cais-evidence-bundle/v1`) records:
- suite identity, profile identity and digest, reasoning policy and measured context envelope;
- executor (script sha256, git commit, host) and the serving identity observed before and after the run;
- per trial: outcome (`pass` / `fail` / `infra_error`), attempts, latency, context and the **final files that were
  graded**.

`assess_bundle()` is deterministic. The gateway re-runs it at every load:
- **Unit = distinct task.** Repeats at temperature 0 are correlated, so a task passes only if every repeat passed;
  disagreement is reported as `unstable_tasks` and counts as failure. 50 repeats of 12 tasks still yield n = 12.
- **Functional gate:** one-sided Wilson lower bound ≥ threshold at the stated confidence, and n ≥ `min_tasks`. The
  thresholds were fixed before any evidence existed:
  - `coding.routine`: LB ≥ 0.60 at 0.9, which requires ≥ 10/12;
  - `coding.complex`: LB ≥ 0.45 at 0.9, which requires ≥ 7/10.
- **Deterministic gates:** trials marked `gate` must all pass, so an average can never hide them.
- **Operational gate:** `infra_error` trials are excluded from n, but a rate above `max_infra_error_rate` makes the
  evidence insufficient rather than favourable.
- **Performance** (p50/p95 latency and TTFT) is reported, not gated, and used only for latency-priority ranking.

**Independence (§5.2).** The roles are kept apart: candidate (reached only through the gateway), fixtures and oracle
(the engx corpus), executor (controller), scorer (pytest under bubblewrap, re-runnable with `run_qualification.py
rescore` without the model) and decision (`assess_bundle`, recomputed by the gateway). Every current bundle is
`internal`: the corpus was written in this repository. Criteria may require `independent`; nothing is promoted to it
automatically.

**Contamination (§5.4).** The engx corpus is public within this repository and has been run against these models
before. Memorisation cannot be excluded, and no withheld partition exists. This is recorded as a limitation, not
solved.

## 6. Qualification state machine (§4.4)

Evaluation lifecycle (`CANDIDATE` → `EVALUATING`) lives on the controller: a candidate profile is an inventory record
with `role: candidate`, evaluated through its qualification-scoped alias. The gateway models only eligibility. The
directive's `UNREGISTERED`, `DISCOVERED`, `DEGRADED` and `RETIRED` were not needed:
- a profile absent from the ledger is unqualified;
- discovery does not exist;
- statistical degradation is a suspension with a reason code;
- retirement is a revocation.

```
              grant (authoritative, evidence re-verified)
   (none) ───────────────────────────────────────────────▶ QUALIFIED ──time ≥ expires_at──▶ EXPIRED ─┐
                      ▲   │ suspend (authoritative or gateway)                                        │
     reinstate(lifts  │   ▼                                                                           │ new grant
     every active     SUSPENDED ──revoke──▶ REVOKED (terminal for this id) ◀──revoke── QUALIFIED     │ (new id,
     suspension id)                                                                                    │ new evidence)
   catalog version bump ─▶ SUPERSEDED     evidence/scope/integrity failure ─▶ INVALID     issued_at>now ─▶ PENDING
```

| Transition | Authority | Evidence required | Persistence |
|---|---|---|---|
| grant | Operator, via Git-reviewed authoritative ledger | Bundle that passes `assess_bundle` against the current definition, profile match, validity ≤ policy | Git + delivered file |
| suspend / revoke | Operator (authoritative) **or** gateway admin API (`admin` scope) | Reason code; attributed authority | fsync'd append (gateway) / Git |
| reinstate | Operator (authoritative only) | Must list every active suspension id it lifts | Git |
| expire / pending / superseded / invalid | Derived at load / evaluation time | — | Recomputed, never stored |

Every transition carries a timestamp (`recorded_at`), a reason code, an authority and a chain hash. Restart and reload
recompute the state from both ledgers. A revocation cannot be lost by:
- a restart, worker reconnect or re-registration, because state is not process-local;
- a ledger rollback, truncation or deletion, because the anti-rollback baseline (`cais-ledger-heads.json`, the
  accepted length and head of **both** ledgers) refuses any ledger that does not extend the accepted one;
- a lost baseline, because ledgers with records but no baseline fail closed (`anti_rollback_baseline_missing`) until
  an admin re-baselines explicitly (`POST /v1/admin/cais/rebaseline`, evidenced as `cais_rebaselined` with the
  previous and new heads). Only a gateway whose ledgers are both empty baselines silently. A baseline that cannot be
  written also fails closed;
- a gateway-ledger forgery, because grant-type events there invalidate the whole snapshot.

Limit: the baseline lives in the gateway's own state directory. It defends against accidental and administrative
loss (restore from an old backup, a deleted file, a Git revert), not against a compromised gateway process. The
journal-anchored evidence chain records every ledger head the gateway loaded, so such tampering stays detectable.

Writers (reload, suspend, rebaseline) are serialised by a write lock and build the next snapshot outside the swap
lock, so requests never wait for a rebuild. Each request sees one immutable snapshot. A suspend or revoke that would
change nothing (already suspended, or revoked) is refused with 409 and writes no record.

## 7. Routing and admission (§4.5, §4.6)

Capability requests skip the rule table entirely.
1. `evaluate()` takes the production workers whose profile holds a `qualified` grant for the capability, within the
   context envelope, and inside the explicit model/alias/pin restriction and client pool RBAC.
2. Candidates are ranked deterministically:
   - `quality`: (−LB, EWMA latency, worker_id);
   - `latency`: (EWMA latency, −LB, worker_id).
   The latency snapshot used is recorded in the decision.
3. The existing `_eligible()` (health, drain, breaker, capacity, identity, API features) is intersected with the
   candidates. Admission runs as before. After a slot is granted the gateway re-checks that the qualification is
   still effective **and** that the worker granted is still the qualified profile (role, profile digest, context): a
   re-registration while queued cannot run the request on a different artifact or runtime. A lapse releases the slot
   and denies.
4. Retries and same-model failover stay inside the candidate set. `X-AIHost-Fallback: none` restricts to the single
   best candidate.

Qualification is a gate; performance only ranks inside the gate.

## 8. Client contract (§6)

Request headers are additive, OpenAI bodies are unchanged, and unknown values are rejected (400 `cais_request_invalid`):

| Header | Values | Default |
|---|---|---|
| `X-AIHost-Capability` | catalog name, e.g. `coding.routine` | absent = legacy routing |
| `X-AIHost-Qualification` | `required` | `required` |
| `X-AIHost-Min-Context` | integer tokens | 0 (the gateway still applies its conservative prompt estimate) |
| `X-AIHost-Routing-Priority` | `quality` \| `latency` | `quality` |
| `X-AIHost-Fallback` | `qualified_only` \| `none` | `qualified_only` |
| `X-AIHost-Deadline-Ms` (existing) | integer ms | none |

Response headers on capability requests: `X-AIHost-Routing-Decision`, `X-AIHost-Capability`,
`X-AIHost-Execution-Profile`, `X-AIHost-Qualification-Id` and `X-AIHost-Qualification-Evidence` (independence).
Streams send them before the first token. `GET /v1/cais` returns the capability matrix and qualification state.

Errors use the OpenAI error envelope, `{"error": {"code": <failure_class>, "message", "details": {"cais": <decision>}}}`:

| failure_class | HTTP | Meaning / client action |
|---|---|---|
| `cais_disabled` | 503 | Enforcement is not enabled on this gateway; do not assume qualification |
| `cais_request_invalid` | 400 | Malformed capability header |
| `capability_unknown` | 400 | Not in the catalog (the message lists known classes) |
| `qualification_state_unavailable` | 503 | Ledger unreadable, broken or rolled back: fail closed |
| `no_qualified_model` | 422 | No profile holds the qualification (`details.cais.rejected` per worker) |
| `qualification_expired` / `_suspended` / `_revoked` | 422 | The only matching qualification is not effective; escalate or wait for requalification |
| `context_unsupported` | 422 | Exceeds every qualified envelope |
| `policy_denied` | 403 | The named alias/pin/pool excludes every qualified profile, or qualified workers lack a required API feature |
| `worker_unavailable` | 503 | Qualified profiles exist but none is healthy and admissible now |
| `quota_exceeded`, `capacity_exhausted`, `deadline_exceeded` (existing) | 429/429/504 | Admission, unchanged |
| `qualification_revoked` (in flight) | 409 | Revoked during execution. Already-streamed tokens cannot be withdrawn; the client must discard the output |

Edge semantics:
- Revocation **while queued**: denied, never executed.
- Revocation **during execution**: cancelled, 409, the stream ends with an `error` event.
- Runtime restart during execution: the existing 503 `gateway_restarting`, and the request is not replayed.
- Missing capability header: legacy.
- Qualified requests are never cached.
- `model`: an alias, served model name or pin narrows the choice. An omitted model or `engineering/auto` lets CAIS
  choose among every qualified profile. Any other name that resolves to no worker is `policy_denied`; it is never
  silently served by a different model.
- Revocation during execution on an engine adapter that cannot be cancelled: the non-streamed answer is withheld
  (409) rather than delivered under a withdrawn qualification. Expiry mid-flight does not cancel: the qualification
  held at dispatch, and expiry is a calendar boundary, not evidence of a fault.
- `details.cais` in client errors omits ledger heads and ranking inputs; the evidence record keeps them.

## 9. Evidence and integrity (§6.1, §8)

Each capability decision appends `cais_routing_decision` to the existing evidence chain. It records:
- the request id, outcome and policy version;
- the eligible candidates with their rank keys, and every rejected worker with its reason;
- the selected worker, execution profile, qualification id and bundle sha256;
- the model id and artifact digest;
- both ledger heads and the mutable inputs (latency snapshot, time).

Prompts are not recorded. Ledger loads append `cais_state_loaded`.

What the mechanism **proves**:
- A grant references bytes that still hash to what was granted.
- Those bytes, re-assessed now, meet the current criteria for the exact profile.
- The authoritative ledger has not been edited in place or rolled back since the gateway last saw it.
- Every removal recorded anywhere applies.

What it **does not prove**:
- That the operator who committed the ledger ran the evaluation honestly. Git review and attribution are the control;
  there is no signature.
- That the worker process serves the bytes its digest names. The gateway sees only the engine's alias; the digest is
  checked by hand.
- That the suite measures real-world competence, or that the models had not seen it.

No new cryptographic trust system was introduced. Signing ledger records with a Vault transit key is the next step if
operator-level forgery enters the threat model.

## 10. Security boundaries (§7.3, AC-14)

- Workload, qualification and telemetry clients can request capabilities and read a reduced `/v1/cais` (capabilities,
  qualification states, envelopes, expiry). `admin` and `monitoring` clients get the full view (authorities, bundle
  digests, ledger heads, problems). No client scope can write qualification state except the removal-only admin API.
- `X-AIHost-Capability` is validated (dotted lowercase, ≤ 64 characters) before anything is recorded.
- Admin error bodies never carry filesystem paths; the journal keeps the detail.
- Ansible asserts the parent of `/var/lib/aihost/cais` is root-owned and not group/other-writable.
- Known, accepted limits: delivery copies files but does not purge ones removed from Git (a stale bundle is inert:
  only ledger-referenced, digest-matching bundles count); the admin `detail` field is free text stored in the gateway
  ledger and evidence, so operators must put a ticket reference there, not prompt content.
- `admin` clients can only **remove** eligibility through the gateway ledger.
- Grants and reinstatements exist only in the authoritative directory. That directory is read-only to the gateway
  process under `ProtectSystem=strict`, and grant-type records in the gateway ledger invalidate CAIS.
- Workers cannot self-assert anything: identity comes from inventory, the observed alias must match, and placement
  never widens eligibility.
- Bundle file names are restricted to `[A-Za-z0-9._-]`, which blocks path traversal.
- Metric labels are bounded: unknown capabilities become `unknown`, and digests and ids never appear in labels.

## 11. Performance (AC-11)

The budget for `CaisService.evaluate()` is **p99 ≤ 5 ms** at 16 workers and 16 qualifications. Measured on the
controller under the gateway quality gate, with qualification state cached per snapshot until the next validity
boundary and profile digests memoised: **p50 0.25 ms, p99 0.43 ms**.

Production observes the same cost as `aihost_cais_decision_seconds`. A capability request also skips the response
cache; that is intentional and is not counted in the budget.

## 12. Acceptance criteria

The **Grade** column is the strongest evidence so far:
- `TESTED_LOCAL`: unit or integration tests with stubbed inference;
- `BLOCKED`: needs approval or live access.

| AC | Test(s) | Grade |
|---|---|---|
| AC-01 legacy compatibility | `test_legacy_requests_are_untouched…`, existing gateway suites unchanged and green | TESTED_LOCAL |
| AC-02 capability eligibility | `test_only_qualified_profiles_are_selected…`, `test_explicit_model_alias_or_pin…` | TESTED_LOCAL |
| AC-03 provenance | `test_grant_is_rederived_from_evidence…`, decision evidence test | TESTED_LOCAL |
| AC-04 durable revocation | `test_revocation_is_durable_across_restart…`, `test_ledger_rollback…`, `test_truncating_or_deleting_the_gateway_suspension_ledger…`, `test_deleting_the_anti_rollback_baseline…`, `test_reload_after_an_authoritative_revocation…` | TESTED_LOCAL |
| AC-05 no silent fallback | drained-qualified-worker case in AC-02 test; `fallback=none` ranking test | TESTED_LOCAL |
| AC-06 determinism | `test_ranking_is_deterministic…` (inputs captured) | TESTED_LOCAL |
| AC-07 heterogeneous workers | profile-scope test (`hardware_class`, engine, image); no platform constants | TESTED_LOCAL at the interface; no second hardware class exists |
| AC-08 context eligibility | `test_context_envelope_is_enforced` | TESTED_LOCAL |
| AC-09 evidence integrity | tamper, missing-bundle, forged-grant and gateway-ledger-forgery tests | TESTED_LOCAL |
| AC-10 failure isolation | `test_subsystem_failure_denies_qualified_work…`, invalid-mode test | TESTED_LOCAL |
| AC-11 performance | `test_routing_overhead_is_within_budget` (section 11) | TESTED_LOCAL |
| AC-12 independent validation | `rescore` re-grades without the model; pipeline test proves it catches tampering. Live evidence on a production profile has not been collected. | TESTED_LOCAL (mechanism) / BLOCKED (live run needs approval) |
| AC-13 recovery and rollback | Restart/reload/rollback tests; procedures in docs/operations/cais.md. Not drilled on the host. | TESTED_LOCAL / BLOCKED |
| AC-14 security boundaries | HTTP privilege test, gateway-ledger forgery test, independent audit | TESTED_LOCAL |
| AC-15 end to end | `test_cais_pipeline.py`: runner → real gateway HTTP → **stub** worker → sandboxed hidden tests → bundle → rescore → grant → enforcement → revoke → denial. **Mocked inference: not a live qualification.** | TESTED_LOCAL / BLOCKED (live) |

## 13. Review

Two independent reviews (code and security) ran on `feat/cais`. Their findings and how each was handled are recorded
in `tasks/todo.md` (CAIS review section). The reviewers are the same model family as the author, so independence is
limited to role separation.

## 14. The critical question (§18)

> How does homelab-ai decide that a model has earned a class of work, enforce it, and revoke it, without the model's
> word or Nexus-specific orchestration?

- **Authority that defines eligibility:**
  - the versioned capability catalog (criteria fixed before evidence);
  - the operator, through a Git-reviewed append-only ledger.

  The gateway re-derives every grant and can only remove eligibility.
- **Evidence that establishes it:**
  - a bundle of per-task results graded by hidden executable tests in a sandbox, bound to one execution profile;
  - re-scorable without the model;
  - passing a confidence bound over distinct tasks plus deterministic gates.
- **Component that enforces it:** `OrchestratorRuntime.complete()` → `CaisService.evaluate()`, intersected with
  `_eligible()`, re-checked after admission. This is the one path every capability request takes, streaming or not,
  pinned or aliased, retried or failed over.
- **Conditions that invalidate it:**
  - expiry;
  - catalog version change;
  - a different profile (any identity field);
  - a context requirement beyond the envelope;
  - an evidence hash or scope mismatch;
  - suspension or revocation in either ledger;
  - ledger corruption or rollback, which invalidates **all** qualifications.
- **Mechanism that prevents bypass:**
  - no capability request reaches the rule table, cache, canary or shadow;
  - aliases and pins only narrow the choice;
  - the gateway ledger cannot grant;
  - clients have no write path;
  - grants are verified, never trusted.
- **Process that restores eligibility:**
  - a new evaluation run → a new bundle → `cais_cli grant` → Git review → deploy;
  - or, for a suspension, an authoritative `reinstate` naming every suspension it lifts.

  A revocation is never undone, only superseded by a new grant.
- **Limits:**
  - competence is measured on a small in-repo corpus that the models may have seen;
  - the operator is trusted, not cryptographically bound;
  - runtime artifact identity rests on a hand-verified digest plus the engine alias;
  - eligibility says the profile *met a bar on a suite*, not that a particular answer is correct. Nexus keeps final
    acceptance (section 15).

## 15. Nexus integration and feedback (§9)

Nexus asks for a class with `X-AIHost-Capability`, optionally `X-AIHost-Min-Context`, `X-AIHost-Routing-Priority`,
`X-AIHost-Fallback: none` and a deadline. It receives the identity headers above, or a failure class it can act on
(escalate to cloud on `no_qualified_model` / `qualification_*`, retry later on `worker_unavailable`). Escalating to
cloud is Nexus's decision. The gateway never routes outside the cluster.

Outcomes reach the gateway through the existing `POST /v1/outcomes`:
- They are attributed to the client, keyed by request id (only the client that was served can report on it), and
  joined to route, pool and artifact in evidence.
- **Gap:** reports are not deduplicated. A repeated report for the same request increments the outcome totals again,
  and contradictory reports are not reconciled. This is the existing endpoint's behaviour and was left unchanged
  (AC-01).
- They are **never** read by eligibility. They are review input: an operator may suspend on them.
- They are circular when Nexus's acceptance was itself judged by the same model. Only build/test results that Nexus
  executed are worth weighing.
- Automatic suspension from outcome statistics is deliberately not implemented. A client must not be able to demote a
  model, and nothing defines how to reconcile contradictory reports.
