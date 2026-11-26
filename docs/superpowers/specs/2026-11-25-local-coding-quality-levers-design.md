# Local Coding Quality Levers (Reframe)

**Date:** 2026-11-25  
**Status:** Approved by operator authorization (“proceed… fully authorized”)  
**Supersedes (as primary campaign):** three-worker collaboration-first accuracy (Stage 3+ frozen)  
**Evidence / research:** `reports/Local coding quality levers.md`, `research_notes/Local coding quality levers/`, nexus_e2e stamp `20261124T191124Z`

---

## 1. Objective

**Maximize deterministic task acceptance under local inference constraints**, measured by hidden/oracle checks at a **fixed token/time budget** — not by multi-model agreement.

Secondary: distinct useful fleet roles; cost/latency. Collaboration is a late, optional tactic — not the goal.

## 2. Non-goals

- Stage 3 triple / free-text LLM↔LLM review as default  
- More engx-hard reps of the same three production pins expecting topology wins  
- Treating lead≡rocm same-digest as quality diversity  
- Swapping production pins without CAIS bake-off evidence  

## 3. Strategy order (locked)

1. **Harness-first** — tools/repair loop already in engx; add **best-of-n** with **execution-gated** selection; budget-matched vs single-sample solo.  
2. **Break Qwen monoculture** — candidate bake-offs using on-disk challengers first (`Devstral-Small-2-24B`, `GLM-4.7-Flash` on 5820). Deep A/B vs Flash-Next; ROCm role ≠ coding clone of lead.  
3. **Complementarity (β)** — solved-set overlap before any ensemble/debate.  
4. **Routing for cost** — only claim acceptance lift if paired tests show it.  
5. **Executable critique only** — failing test/counterexample; never free-text veto.

## 4. Acceptance / evaluation rules

- Oracle = hidden/deterministic checks (engx-hard initially; Nexus pack when available).  
- Every comparison is **budget-matched** (tokens or wall, declared).  
- Report pass rate, always-fail, flaky, mean tokens/secs, and for BoN: `n`, selection rule, oracle coverage vs selected.  
- Production pin changes require CAIS profile identity + qualification per `docs/operations/cais.md`.

## 5. Architecture

```
mike-dev harness (nexus_e2e / engx)
        │  best-of-n | solo | candidate smoke
        ▼
 ai-5820-01 gateway (unchanged one-call→one-worker)
        │
   production pins + candidate aliases (bake-off only)
```

Gateway stays dumb. Selection lives in the harness (execution judge).

## 6. Success criteria (campaign)

- BoN+execution selection **beats** single-sample solo at matched mean tokens **or** is documented as not worth it on engx-hard.  
- ≥1 non-Qwen (or clearly distinct) candidate completes smoke + engx subset with identity recorded.  
- Written decision: keep / replace deep and/or reset ROCm role — with numbers.  
- No Stage 3 unless executable-critique experiment is later authorized with a real verifier.
