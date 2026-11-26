# Nexus E2E Three-Worker Accuracy — Implementation Plan

> **For agentic workers:** Design-approved work only. This plan is staged evidence gates. Do **not** change host config, deploy services, alter routing, or pin models until the matching stage is operator-authorized. Prefer harness-first changes on mike-dev.

**Goal:** Prove whether coordinated use of the three local workers improves Nexus engineering **task acceptance and accuracy** versus individual-worker baselines, then land only the orchestration/eval pieces justified by that evidence.

**Architecture:** Keep the gateway as one-call→one-worker. Put collaboration, repair, and acceptance in an orchestration plane (evaluation harness first; Nexus product integration later). Score acceptance with deterministic checks and inspectable evidence — never majority vote.

**Tech Stack:** Existing 5820 gateway + three production workers; `evaluations/engx` sandbox patterns; Ansible from mike-dev for any live probes; new harness under `evaluations/nexus_e2e/` (proposed).

**Spec:** `docs/superpowers/specs/2026-11-24-nexus-e2e-three-worker-accuracy-design.md`

---

## File map (proposed; create only when stage authorized)

| Path | Responsibility |
|------|----------------|
| `evaluations/nexus_e2e/README.md` | How to run, metrics definitions, non-goals |
| `evaluations/nexus_e2e/schema/evidence_packet.schema.json` | Acceptance packet schema |
| `evaluations/nexus_e2e/drivers/solo.py` | Single-worker baseline driver |
| `evaluations/nexus_e2e/drivers/dual.py` | Implement + review + investigate |
| `evaluations/nexus_e2e/drivers/triple.py` | Dual + disagreement analyst |
| `evaluations/nexus_e2e/oracles/` | Task packs with hidden tests / scripts |
| `evaluations/nexus_e2e/compare_baselines.py` | Solo vs dual vs triple report |
| `docs/operations/nexus-e2e-collaboration.md` | Operator runbook (later) |

---

## Stage 0 — Freeze facts and baseline harness contract

**Intent:** Lock what “accepted” means before any collaboration claims.

- [x] **Step 0.1:** Confirm live worker identities via gateway (controller → 5820 `/v1/models`): lead / deep / rocm `artifact_digest`, inventory-enriched `runtime_image_digest` / `hardware_class`, `context_limit`.
- [x] **Step 0.2:** Document the **same-artifact** lead≡rocm constraint in the harness README (fail the run if digests unexpectedly diverge without updating the plan).
- [x] **Step 0.3:** Stage-1 corpus = engx **hard**; digest `a2e49329628243ed` (10 tasks).
- [x] **Step 0.4:** Define acceptance = hidden/deterministic oracle pass + evidence packet complete. Explicitly exclude model self-grading.

**Stage 0 acceptance criteria**

- Written contract checked into `evaluations/nexus_e2e/README.md` (when authorized to add files).
- Live digest table captured under `evaluations/nexus_e2e/evidence/<stamp>/fleet_identity.json`.
- No routing/inventory edits.

**Evidence required:** fleet identity JSON; corpus digest; README contract.  
**Status:** Stage 0 complete 2026-11-24 (`evidence/20261124T191124Z/`). Note: live `engineering/interactive-rocm` has `reasoning.mode=off` (budget 0) while lead/deep are `on`/4096 — same GGUF, different reasoning profile.

---

## Stage 1 — Solo baselines (per worker)

**Intent:** Establish per-worker accepted rates under identical tasks/harness.

- [x] **Step 1.1:** Implement `drivers/solo.py`: pin `engineering/deep`, `engineering/lead`, `engineering/interactive-rocm` separately through the **5820 front door**.
- [x] **Step 1.2:** Run N reps (suggest ≥3) temperature 0; record attempt counts, tokens, wall time, pass/fail, worker identity headers. *(done: stamp `20261124T191124Z`, reps=3, finished 2026-11-25T03:43:32Z)*
- [x] **Step 1.3:** Publish `solo_baselines.json` with per-task and aggregate accepted rates. **Best solo = lead 96.7%**; deep 86.7%; rocm 86.7%.

**Stage 1 acceptance criteria**

- All three pins produce comparable evidence packets.
- Best solo peer identified for this corpus (**likely deep** historically — re-measure, do not assume).
- Time/resource metrics recorded but **not** used to pick a winner over accuracy.

**Evidence required:** per-pin result archives; summary table; no collaboration yet.

---

## Stage 2 — Dual collaboration (model-diverse)

**Intent:** Test whether implementer + adversarial reviewer improves acceptance / reduces escapes.

**Default pairing to measure first:** implementer=`deep`, reviewer=`lead` (different artifacts).  
**Secondary pairing:** implementer=`lead`, reviewer=`deep`.  
**Do not** treat lead↔rocm as model-diverse while digests match.

- [x] **Step 2.1:** Implement dual driver: implement → deterministic check → if fail, repair loop (cap 3) → if pass, review → investigate each finding → repair only `supported` findings → re-check.
- [x] **Step 2.2:** Run same corpus/reps as Stage 1. *(finished 2026-11-25T16:12:33Z on stamp `20261124T191124Z`)*
- [x] **Step 2.3:** Compare to best solo: dual-lead-deep **100%** beats solo-lead 96.7%; dual-deep-lead 83.3% does not. 0 escapes; 0 supported findings (all dropped). See `dual_vs_solo.md`.

**Stage 2 acceptance criteria**

- Dual either **improves accepted rate** or **reduces escapes** with accepted rate ≥ solo − ε (operator-set ε, suggest 0), **or** is explicitly documented as not worth it.
- Every accepted task has a complete evidence packet.
- No majority vote in the driver.

**Evidence required:** `dual_vs_solo.md` with controlled comparison; raw archives.

**Stop / decide:** If dual never helps, do not build triple; revisit model mix instead.

---

## Stage 3 — Triple collaboration (disagreement-only)

**Intent:** Use the third worker only when dual leaves contested claims.

- [ ] **Step 3.1:** Implement triple path: run dual; if contested `supported`/`refuted` conflict remains, call analyst with **only** contested claims + repo excerpts + failing tests.
- [ ] **Step 3.2:** Prefer analyst pool whose artifact differs from both prior roles when possible; if impossible (lead≡rocm), record “hardware-only diversity” and measure separately.
- [ ] **Step 3.3:** Compare triple vs dual on the subset that triggers disagreement (primary) and full corpus (secondary).

**Stage 3 acceptance criteria**

- Triple improves resolution of contested tasks without lowering oracle rigor.
- Calls avoided when dual already clean-pass.
- Clear accounting of redundant third calls.

**Evidence required:** disagreement subset report; full-corpus delta vs dual.

---

## Stage 4 — Policy freeze + Nexus integration design

**Intent:** Codify when solo/dual/triple fire; integrate with Nexus without weakening acceptance.

- [ ] **Step 4.1:** Write operator policy table (task_class → mode) from Stage 1–3 numbers.
- [ ] **Step 4.2:** Specify Nexus hooks: role prompts, attempt caps, evidence packet upload, cloud exception flag (off by default).
- [ ] **Step 4.3:** List gateway gaps only if needed (e.g., optional `X-AIHost-Role` for evidence) — still one-call→one-worker.

**Stage 4 acceptance criteria**

- Policy document reviewed by operator.
- Nexus change list scoped; **no** silent pin substitution; local-gateway-first preserved.
- Still no permanent model reassignment unless Stage 5 authorized.

**Evidence required:** policy doc; Nexus interface notes.

---

## Stage 5 — Model-mix decision (only if measurement demands)

**Intent:** If Stage 2–3 show lead≡rocm review is worthless, decide whether rocm should regain a distinct artifact (capability-mix tension with “same as lead for capacity”).

- [ ] **Step 5.1:** From evidence, choose one: keep same-as-lead (capacity/failover only) **or** distinct rocm artifact for collaboration diversity.
- [ ] **Step 5.2:** If distinct: new bake-off plan (separate campaign); do not hitch to this harness silently.
- [ ] **Step 5.3:** CAIS re-qualify any new `profile_identity` before CAIS-routed use.

**Stage 5 acceptance criteria**

- Written decision with numbers.
- No inventory change without explicit operator authorization and CAIS procedure.

---

## Evaluation plan (controlled comparison)

### Constants across arms

- Same task corpus + digest  
- Same temperature / tool sandbox / hidden tests  
- Same attempt caps  
- Same front door (`ai-5820-01`)  
- Same evidence schema  
- Fresh or controlled prompt-cache policy (document which)

### Arms

| Arm | Description |
|-----|-------------|
| Solo-deep | Pin deep |
| Solo-lead | Pin lead |
| Solo-rocm | Pin interactive-rocm |
| Dual-deep→lead | Implement deep, review lead |
| Dual-lead→deep | Implement lead, review deep |
| Triple | Dual + analyst on disagreement only |

### Primary outcomes

- Accepted task rate  
- Escape rate (oracle fail after clean review path)  
- False-finding rate  
- Supported-finding precision  
- Repair success given supported findings  
- Evidence completeness rate  

### Secondary outcomes

- Wall time, tokens, worker call counts, saturation/failover events  

### Decision rule

Promote a collaboration policy only if primary outcomes improve (or escapes drop without acceptance regression) on the sealed corpus with ≥ planned reps. **Do not** promote on latency wins alone.

---

## Out of scope for this plan

- InferSSD promotion  
- tok/s / context-size optimization campaigns  
- Gateway multi-agent merging  
- Cloud routing inside the gateway  
- Defining CAIS `review.*` without an oracle  

---

## Operator decisions

1. **Design approved** 2026-11-24.  
2. **Stage 0–1 authorized** 2026-11-24 (choice A): harness + engx-hard solo baselines on mike-dev; no host/routing changes.  
3. **Stage-1 corpus = engx-hard** (digest `a2e49329628243ed`). Evidence stamp: `evaluations/nexus_e2e/evidence/20261124T191124Z/`.
