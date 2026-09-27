# Phase 4 Independent Baseline Verification and Verification of Evaluation Scope

---

## 1. Executive Summary of Audit

Prior to beginning live heterogeneous operations and evidence-based routing in Phase 5, the Phase 4 baseline was independently audited, cryptographically verified against its checksum manifest, and retested in the isolated `phase5-live-hetero` workspace.

### Audit Findings
- **Baseline Git Revision**: `45b736f` (branch `phase4-model-eval` / `phase5-live-hetero`)
- **Isolated Worktree**: `/home/mike/Projects/aihost/.worktrees/phase5-live-hetero`
- **Integrity Manifest**: All 73 tracked files in `phase4/evidence/manifest.sha256` verified intact via `sha256sum -c` (0 mismatches, 0 errors).
- **Automated Regression Suite**: 115 tests passing across all historical phases:
  - Phase 0 (Offline Vertical Slice): 39 tests passing
  - Phase 1 (Controlled Live Boundary): 16 tests passing
  - Phase 2 (Durable Multi-Worker DAG): 17 tests passing
  - Phase 3 (Operational Work-Order Service & Cohort): 24 tests passing
  - Phase 4 (Model Qualification & Routing Matrix): 19 tests passing
  - Total: 115 passing, 0 failing, 0 skipped.
- **Historical Phase 4 Disposition**: `PHASE_4_MODEL_CONFIGURATION_QUALIFICATION: PROVEN` (Affirmed).

---

## 2. Distinction of Inference Evidence Tiers

To ensure complete transparency, the Phase 4 results are categorized by the physical nature of their execution:

1. **Physical Live Inference**:
   - Executed against `engineering/b0` (`Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`) hosted on the physical Intel Arc Pro B65 dual-card topology (TP=2 across `0000:51:00.0` and `0000:93:00.0`) via `http://127.0.0.1:18010/v1`.
   - Verified token-authenticated requests, completion generation, tool calling, and live artifact generation.
2. **Deterministic Sandboxed Validation**:
   - The 12 evaluation fixtures (8 Phase 3 cohort fixtures + 4 novel held-out fixtures) were executed within Bubblewrap containment with independent test runner execution (`pytest`), content-addressed artifact hashing, and supervisor-authoritative admission/acceptance.
3. **Simulated / Replayed Specialist Qualification**:
   - Candidate role qualification for `cand-phi4-fp8`, `cand-deepseek-lite-fp8`, and `cand-qwen25-32b-awq` was conducted using deterministic capability evaluation against synthetic review items and calibrated defect detection matrices.
   - **Crucial Distinction**: Phi-4 FP8 was qualified in Phase 4 as an *algorithmic specialist configuration*, NOT as a live concurrent serving daemon on physical B65 hardware alongside Qwen3-Coder.

---

## 3. Preserved Rollback Target

- **Rollback Target Commit**: `eab3b9f` (Phase 3 operational service) and `45b736f` (Phase 4 qualification baseline).
- Any runtime degradation or failure during Phase 5 live heterogeneous experimentation will immediately trigger restoration to this verified baseline.
