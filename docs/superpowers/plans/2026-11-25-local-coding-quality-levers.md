# Local Coding Quality Levers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans`. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Raise deterministic acceptance under local constraints via harness best-of-n + execution selection, then bake-off distinct model candidates — not LLM collaboration theater.

**Architecture:** Selection and budgeting in `evaluations/nexus_e2e/`; gateway remains one-call→one-worker; candidates via existing candidate/alias patterns; production pins unchanged until CAIS evidence.

**Tech Stack:** engx hard corpus, 5820 gateway, Ansible from mike-dev, on-disk GGUFs (Devstral Small 2, GLM-4.7-Flash already on ai-5820-01).

**Spec:** `docs/superpowers/specs/2026-11-25-local-coding-quality-levers-design.md`

---

## File map

| Path | Responsibility |
|------|----------------|
| `evaluations/nexus_e2e/drivers/best_of_n.py` | N independent implement samples; pick first that passes hidden oracle (or none) |
| `evaluations/nexus_e2e/scripts/run_bon_vs_solo.sh` | Budget-matched BoN vs solo compare |
| `evaluations/nexus_e2e/scripts/compare_bon_vs_solo.py` | Summary markdown |
| `evaluations/nexus_e2e/scripts/analyze_complementarity.py` | Pairwise β (joint all-fail) and solved-set overlap |
| `playbooks/candidate_engx_probe.yml` | Candidate probe + engx subset experiment under durable transaction |
| `evaluations/nexus_e2e/evidence/<stamp>/` | Results + `decision_memo.md` |

---

### Task 1: Best-of-n driver + unit tests

**Files:**
- Create: `evaluations/nexus_e2e/drivers/best_of_n.py`
- Modify: `tests/unit/test_nexus_e2e_harness.py`
- Reuse: `drivers/common.py`, engx `run_task` / `validate`

- [x] **Step 1:** Failing tests for selection: prefer oracle-pass sample; if none pass, mark fail; count samples/tokens.
- [x] **Step 2:** Implement `best_of_n.py` (`--pin`, `--n`, `--temperature`, `--reps`, stamp/out). Also `ENGX_TEMPERATURE` in engx.py.
- [x] **Step 3:** `pytest tests/unit/test_nexus_e2e_harness.py` green.

### Task 2: Budget-matched BoN vs solo (lead pin)

- [x] **Step 1:** Run solo lead `--reps 1` max_attempts=1 on full hard; record tokens (`20261125T193127Z`: 80.0%, 6051 mean tokens).
- [x] **Step 2:** Run BoN `n=3` temperature 0.2 on same tasks/reps (`20261125T193127Z`: 90.0%, 8362 mean tokens, 1.3 mean samples).
- [x] **Step 3:** Write `bon_vs_solo.md` under evidence stamp (including matched-token comparison vs Stage 1 `solo-lead` repair 96.7% at 8289 mean tokens).

### Task 3: Challenger inventory + smoke

- [x] **Step 1:** Confirm digests for Devstral + GLM-4.7-Flash on 5820 (see `evidence/20261125T193127Z/candidates/README.md`).
- [x] **Step 2:** Inventory candidate profiles `devstral-small2` + `glm47-flash` added to `ai-5820-01.yml` (plus non-reasoning budget=0 support in `candidate.yml`, `--limit` in `candidate_recovery.py`, and `expected_gateway_workers` in `verify_candidate_restoration.py`).
- [x] **Step 3:** Candidate-role smoke + `engx-hard` subset `{H02,H03,H07,H08}` via durable transaction (`devstral-small2` 0/4, `glm47-flash` 0/4; both `restored_verified`).

### Task 4: Deep / ROCm decision memo

- [x] **Step 1:** Compute pairwise complementarity β (`complementarity.md`) and write keep/replace recommendation (`evaluations/nexus_e2e/evidence/20261125T193127Z/decision_memo.md`).
- [x] **Step 2:** Operator gate: run CAIS `coding.complex` on `lead` (`Qwen3.8-27B`) — qualified (`19/20` trials, `9/10` tasks, `pass_lower_bound: 0.7176`, `rescore` 0 mismatches, granted locally as `q-coding.complex-412a2b3ad304-b1d7481e`). Follow up with PR review + gateway ledger delivery + routing/candidate PR (both on-disk non-Qwen challengers rejected).

---

## Operator decisions

1. Design approved 2026-11-25 (full authorization to proceed).  
2. Stage 3 collaboration remains frozen.  
3. Production pin swaps still require CAIS evidence before converge.
