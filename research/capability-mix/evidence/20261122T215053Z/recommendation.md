# Capability-mix campaign recommendation

**Date:** 2026-11-22 (UTC `20261122T215053Z`)

**Status:** Operator wrap — models chosen; fleet-auto CAIS matrix aligned in
`docs/superpowers/specs/2026-11-22-fleet-auto-cais-routing-design.md`.

## Summary

Dual-track campaign (Track L on `ai-5820-01`, Track R on `ai-ms-s1-max-01`) replaces
the failing lead and coder-first rocm pins with a **capability mix**: lead =
orchestrator with a `coding.routine` floor; deep = unchanged coding specialist with
live grants; rocm = general/long-context text plus on-demand visual bolt-ons.

## Winners

### Lead (`ai-5820-01`)

| Field | Value |
| --- | --- |
| Model | **Qwen3.8-27B** (UD Q4_K_M) |
| Role | General orchestrator (multi-step tools + routing/decomposition) |
| CAIS | Grant **`q-coding.routine-412a2b3ad304-85f81041`** on live profile |
| Reasoning | On, budget **4096** (must match inventory policy used for the grant) |
| Evidence | `research/capability-mix/evidence/20261122T184929Z/`, `…/190405Z/`; engx `2026-11-22` |

### Rocm primary (`ai-ms-s1-max-01`)

| Field | Value |
| --- | --- |
| Model | **Qwen3.8-27B** (UD Q4_K_M) — **replaces Coder-30B** as interactive-rocm primary |
| Role | General / long-context text (not coder-first) |
| CAIS | **Coding grants not required** for the primary pin |
| Evidence | `research/capability-mix/evidence/20261122T212239Z/r-text-qwen38-27b.md` (R-text smoke PASS) |

### Deep (`ai-5820-01`)

Unchanged pin. Holds live **`coding.routine`** and **`coding.complex`** on runtime
`sha256:6cd97c37…` (ledger grants 2026-11-22). Remains the coding/reasoning specialist
for capability-shaped traffic and coding-heavy auto bands.

## Track R bolt-ons (lab-proven, not yet gateway aliases)

| Bolt-on | Stack | Access | Evidence |
| --- | --- | --- | --- |
| **R-ocr** | GLM-OCR (llama.cpp multimodal) | On demand, loopback | `research/capability-mix/evidence/20261122T212800Z/` |
| **R-img** | ComfyUI + SDXL-Turbo | On demand, loopback | `research/capability-mix/evidence/20261122T213219Z/` |

Video generation is **deferred** (non-goal for this campaign).

## Routing / CAIS expectations (fleet-auto)

- Unpinned and `engineering/auto`: `quality_first` over `{lead, deep, rocm}`.
- **Coding-shaped** unpinned traffic: prefer **deep**, then **lead**, then rocm.
- **CAIS `enforce`:** deep must hold live coding grants; lead must hold at least
  `coding.routine` after cutover; rocm primary does **not** need coding grants.

## Follow-ups

1. **Gateway:** add OCR and image-generation aliases / workers that call R-ocr and
   R-img bolt-ons (design seam only documented in inventory comments today).
2. **Video:** revisit when a Strix-feasible stack is chosen; no hard requirement.
3. **Reconcile:** re-enable hourly reconcile timers only after reconcile snapshot
   includes fleet-auto + capability-mix inventory (per fleet-auto spec Section 5).
4. **CAIS profiles:** update `evaluations/cais/profiles/rocm.json` to reflect general
   rocm primary (Qwen3.8-27B) rather than Coder-30B coding specialist assumptions.
5. **Fleet-auto implementation:** continue `docs/superpowers/specs/2026-11-22-fleet-auto-cais-routing-design.md`
   (inventory bands, contract tests, live validation) — separate from this campaign wrap.

## References

- Design: `docs/superpowers/specs/2026-11-22-lead-rocm-capability-mix-design.md`
- Plan: `docs/superpowers/plans/2026-11-22-lead-rocm-capability-mix.md`
- Fleet-auto CAIS: `docs/superpowers/specs/2026-11-22-fleet-auto-cais-routing-design.md`
- Index: `research/capability-mix/README.md`