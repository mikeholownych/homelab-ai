# Local coding quality levers

**Date:** 2026-11-25  
**Trigger:** Operator challenge — stop retesting the same models under collaboration topology; challenge all assumptions; research before the next GPU campaign.  
**Notes:** `research_notes/Local coding quality levers/`  
**Local evidence:** `evaluations/nexus_e2e/evidence/20261124T191124Z/`  
**Prior related:** `reports/CAIS fleet model survey.md`, `docs/superpowers/specs/2026-11-22-lead-rocm-capability-mix-design.md`

---

## Executive take

The three-worker “collaboration for accuracy” campaign asked the **wrong question** with the **wrong peers** and the **wrong harness**.

Stage 2 dual review produced **zero supported findings**. Acceptance moves were implementer variance (lead again), not collaboration. Literature and our own CAIS survey already pointed elsewhere: **harness + execution/verification**, **budget-matched sampling**, **distinct model families / roles**, and **routing by failure type** — not stacking Qwen critics.

**Do not run Stage 3 triple** under the current design. Freeze collaboration theater until a reframed experiment is approved.

---

## What we assumed vs what broke

| Assumption | Status |
|---|---|
| Extra workers / dual review ⇒ higher acceptance | **Falsified** here (noop review; deep→lead dual *below* solo-deep) |
| Current pins are the best candidates | **Unjustified** — Qwen monoculture; Flash-Next IQ1 + Community license; lead≡rocm |
| Different GGUF ⇒ useful judgment diversity | **Weak** within one family; 0 actionable findings |
| engx-hard re-runs measure collaboration | **Mis-specified** — oracle already passed before review |
| Triple is next | **Illogical** — nothing contested to adjudicate |
| Deep is the hard-coding specialist | **Falsified on this corpus** (lead 96.7% > deep 86.7%; deep 0/3 on H07) |
| Same-27B on ROCm is a quality peer | **Falsified as diversity** — capacity clone; reasoning off; unique H08 wipeout |

Useful leftover signal: **complementary failure sets** (H07 vs H08) — a routing story, not a review story.

---

## External research (skeptical)

### Harness verification beats free-form multi-agent theater

- [Rethinking Verification in Agent Harnesses](https://arxiv.org/abs/2610.34577): independent review of **requirements + changes** gained ~4–10 points on TB/SWE at modest cost; trajectory critics cost more without consistent wins.
- [Beyond Passing Tests](https://arxiv.org/abs/2610.38977): at matched budgets, **best-of-n + analyzer ranker** matched/beat reviewer agents; 1/66 techniques beat best-of-n beyond chance on their target.
- [Agentless](https://dl.acm.org/doi/10.1145/3715754) / [SWE-Effi](https://arxiv.org/html/2509.09853): simple pipelines + sampling can beat complex agents; **scaffold×model fit** matters; model often dominates scaffold brand.
- [Thinking Longer, Not Larger](https://arxiv.org/abs/2503.23803): test-time compute on a 32B can approach much larger models on SWE-Verified.

### Same-family / ungrounded review is a known failure mode

- [Homogenization in MAS](https://arxiv.org/abs/2610.09824): correlated blind spots; reviewers get overconfident.
- [Specification as Quality Gate](https://arxiv.org/html/2603.25773): without external spec/tests, generator+reviewer share a prior; circular.
- [Fresh Eyes Beat a Second Family](https://stephens.page/blog/fresh-eyes-beat-a-second-family/paper/fresh-eyes-beat-a-second-family.pdf): “cross-family” gains often reduce to **fresh independent look**; acting on findings ≈ finding them.

### Verifier budget is a first-class design choice

- [SPLIT](https://arxiv.org/abs/2610.23255): allocate sampling vs verification from verifier reliability; fixed rules lose; more LLM judges can hurt precision when correlated.

### Local model landscape (do not treat current pins as destiny)

From `reports/CAIS fleet model survey.md` (still the right *process*): board giants don’t fit B65; deployable challengers include **Devstral Small 2 24B**, **GLM-4.7-Flash**, **gpt-oss-20b**, Gemma 4 31B/26B-A4B; Strix-only ceilings (gpt-oss-120b, DeepSeek V4.1 Flash IQ1, etc.). Capability-mix already said ROCm should not be a coding clone — then cutover made it one.

Public “best local coding” lists (DeepInfra / local guides, Nov 2026) still crown **Qwen3.8-27B**-class for single-GPU coding — which explains why we pinned it, and why **pinning it twice** buys no diversity.

---

## Reframed problem (candidates — pick one product question)

Stop optimizing “three-worker collaboration accuracy.” Pick an explicit objective:

1. **Maximize Nexus task acceptance under local constraints** (harness + models as variables).
2. **Maximize distinct useful capabilities per watt/slot** (orchestrator ≠ coder ≠ long-ctx/vision).
3. **Minimize escaped defects given a fixed inference budget** (sampling + grounded verifiers).
4. **Something else** (operator-defined).

Collaboration may appear *later* as a tactic inside (1) or (3). It is not the goal.

---

## Alternative strategies (ranked hypotheses — not commitments)

Updated with follow-on research: [coding quality levers](1fda2058-d267-481d-86d3-95e7c678ef24), [local model candidates](9b10d5b7-b260-4ad3-8a4a-deb7d32b991b).

| Rank | Strategy | Why it might win | Cost / risk |
|---|---|---|---|
| **1** | **Harness-first** — tools + fail-before/pass-after repro + regression; budget-matched parallel rollouts; execution-gated selection | Largest evidenced gain; dual spent budget on noop review; sampling coverage needs a verifier to become acceptance | Nexus/engx work; no inventory change first |
| **2** | **Break the Qwen monoculture** — deep A/B: Flash-Next-Coder vs Nanbeige4.3-33B vs Devstral Small 2; ROCm → Gemma 4 26B-A4B or GLM-4.7-Flash (not same 27B) | Real diversity; lead 27B can stay as baseline | Live bake-off; license (Qwen Community on Flash-Next); fit/KV smoke |
| **3** | **Measure complementarity (β) before ensembles** — solved-set overlap on ≥100–300 tasks; only then mix generators | Stops building debate/routers on correlated twins | Needs held-out tasks; engx-hard alone is too small |
| **4** | **Routing as cost lever** (optional fingerprint map) — expect savings, prove acceptance lift with paired tests or don’t claim it | Literature: routers ≈ best-single on resolve rate | Overfit risk if claimed as quality win |
| **5** | **Executable critique only** — reviewer must emit a failing test/counterexample that runs; free-text veto banned | Aligns review with the only judge that worked in Agentless-class systems | Still premature until (1) |

Anti-strategies: more engx-hard reps of the same three pins; Stage 3; lead↔rocm “diversity”; pointwise LLM LGTM gates; debate-at-matched-compute as default.

---

## Proposed next research/experiment gate (no GPU until chosen)

1. Operator picks **objective** (section above).
2. Write a **new** design spec that does **not** start from “three-worker collaboration.”
3. First experiment must include a **budget-matched baseline** (e.g. 2× solo samples + oracle pick vs 1× solo + LLM review at equal tokens).
4. Any model change goes through existing CAIS bake-off discipline — not vibe pins.

---

## Open question for operator

Which product question should own the next campaign: **(1) Nexus acceptance / harness**, **(2) capability mix / distinct roles**, **(3) escape-minimizing budget allocation**, or a different sentence of your own?
