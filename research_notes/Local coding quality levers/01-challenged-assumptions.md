# Challenged assumptions (from local evidence + literature)

Date: 2026-11-25  
Scope: After Stage 0–2 nexus_e2e engx-hard (stamp `20261124T191124Z`).

## Local evidence that contradicts the collaboration campaign

| Observation | Implication |
|---|---|
| dual: **0 supported / 285 dropped** findings | Review never entered the repair path; dual ≠ collaboration |
| dual-lead-deep 100% vs solo-lead 96.7% | Same implementer (lead); lift is noise/variance, not review |
| dual-deep-lead 83.3% < solo-deep 86.7% | Extra topology can *hurt* or at least not help |
| deep always fails H07; rocm always fails H08; lead fails neither | **Specialization / routing** signal, not “need a third critic” |
| lead≡rocm same digest; rocm reasoning **off** | Not three cognitive peers; two models + capacity clone |
| Historical “deep best at hard” failed on this corpus (lead 96.7% > deep 86.7%) | Role labels from inventory ≠ measured competence |

## Assumptions to discard (or demote to hypotheses)

1. **Collaboration is the solution** because three workers exist.
2. **Current pins are the right candidates** (Qwen3.8-27B ×2 + Flash-Next IQ1).
3. **Different GGUF within one family ⇒ useful review diversity.**
4. **Re-running engx-hard under new topology yields new science.**
5. **Triple is the natural next step** after dual.
6. **engx FILE-block chat ≈ Nexus engineering acceptance.**
7. **Capability-mix cutover to same-27B on lead+rocm was quality-optimal** (it optimized sameness/capacity, not diversity).

## Assumptions still open (need different experiments)

1. A **stronger agent harness** (tools + execution feedback + budget-matched sampling) beats today’s engx loop on the *same* model.
2. A **non-Qwen** peer (Devstral / GLM / gpt-oss) changes failure sets enough to matter.
3. **ROCm as long-ctx / sole-tenant larger model** beats ROCm as coding clone.
4. **Task-class routing** from failure fingerprints beats always-lead and beats dual review.
