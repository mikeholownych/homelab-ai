# Phase 2 Independent Baseline Verification Report

**Date of Verification**: 2026-09-27  
**Workspace**: `/home/mike/Projects/aihost/.worktrees/phase3-operational-service`  
**Verified Revision**: `be4958cb04017d79e3686979376935c09f899094` (`be4958c`)  
**Base Commit**: `db1172a` (Phase 1 controlled live execution)  
**Historical Terminal Disposition**: `PHASE_2_DURABLE_MULTI_WORKER_ENGINEERING: PROVEN`  

---

## 1. Baseline Integrity and Checksum Verification

The Phase 2 implementation, tests, fixtures, documentation, and evidence were verified against the cryptographic manifest at `phase2/evidence/manifest.sha256`:

- **Manifest Hash Check**: Executed `sha256sum -c phase2/evidence/manifest.sha256` across all 63 registered Phase 2 files.
- **Result**: 100% OK (63 / 63 matched).
- **Git Commit Alignment**: The working tree at revision `be4958c` corresponds exactly to the final verified state with zero untracked modifications in `phase2/`.

---

## 2. Test Suite Execution and Independent Verification

The full test regression suite was executed independently:
```bash
$ PYTHONPATH=phase2/src python3 -m pytest phase0/tests phase1/tests phase2/tests
======================== 72 passed in 66.22s (0:01:06) =========================
```
- **Phase 0 Offline Prototype**: 39 / 39 tests passing.
- **Phase 1 Hardened Live Execution**: 16 / 16 tests passing.
- **Phase 2 Durable Multi-Worker Execution**: 17 / 17 tests passing (12 real-process POSIX signal recovery tests + 5 representative cohort and matched comparison tests).
- **Regressions**: 0 failures, 0 errors, 0 flaky tests.

---

## 3. Dissection of Evidence Categories: Live vs. Simulated vs. Infrastructure

To maintain scientific integrity, Phase 2 evidence categories are categorized explicitly:

| Category | Implementation Mechanism | Evidence Scope | Limitations & Boundaries |
| :--- | :--- | :--- | :--- |
| **Controlled Live Execution** | `LiveModelWorker` -> `http://127.0.0.1:18010/v1` (`engineering/b0`) via SSH tunnel | Verified OpenAI wire protocol, token auth, tool calling, and patch generation at concurrency 1 | Tested against single disposable repo; strictly bounded to avoid contending with active campaign. |
| **Simulated Multi-Worker Roles** | `FastCoderWorker`, `ReviewerWorker`, `RepairWorker`, `MultiFileWorker`, `TestDevWorker`, `RefactorWorker` | Validated multi-step DAG scheduling, artifact-addressed CAS handoffs, review advisory reports, and bounded repair logic | Generates deterministic candidate artifacts; does not measure stochastic model drift or real-world prompt misunderstandings. |
| **Real OS Process Durability** | `subprocess.Popen` child processes, POSIX signal injection, SQLite WAL transactions | Evaluated lease timeout, atomic reassignment, monotonic fencing, and process crash recovery across 12 POSIX signals | Proves operating-system level fencing and transaction durability; does not represent remote network RPC partition semantics. |
| **Representative Cohort Acceptance** | `IndependentValidator` running `pytest` inside Bubblewrap (`bwrap`) containment | Proved independent artifact extraction, application, and test-driven acceptance across 4 software engineering classes | Evaluated 1 primary fixture per class (4 fixtures total); does not represent diverse repository sizes or multi-language contexts. |

**Rule**: Simulated results are never presented as evidence for live inference reliability, and infrastructure durability tests are never presented as evidence for model capability.

---

## 4. Evaluation of Matched Single-Worker vs. Multi-Worker Comparison

In Phase 2 Gate 8, a matched experimental comparison was conducted using an intentionally defective candidate patch:
- **Observed Result**: The cooperative multi-worker pipeline (`Author` -> `Reviewer` -> `Repair` -> `Validator`) successfully caught the defect at the review stage, generated a line-level finding, triggered pre-validation repair, and achieved final acceptance (`ACCEPTED`). The single-worker control (`Author` -> `Validator`) submitted the flawed patch directly to the sandbox and failed (`REJECTED`).
- **Sample Size and Limitation**: Sample size is **N=1** matched pair. While this proves that the architectural mechanism functions as designed, an N=1 comparison **does not establish a general performance advantage** or prove that cooperative review is cost-effective across all task classes.
- **Phase 3 Mandate**: Phase 3 must evaluate repeated matched runs across diverse engineering fixtures to characterize where cooperative review is beneficial versus where single-worker execution is optimal.

---

## 5. Protected Shared Infrastructure Status

Prior to any Phase 3 activities, the host environment was audited:
1. **Gateway PID 986**: Active (`/home/mike/Projects/hermes-agent/.venv/bin/python ...`).
2. **OpenCode PID 3130937**: Active (`opencode --auto`).
3. **Tunnel PID 2093382**: Active (`/usr/bin/ssh ... -L 127.0.0.1:18010:127.0.0.1:8010 mike@10.0.8.5`).
4. **Primary Checkout**: `/home/mike/Projects/aihost` remains untouched with pre-existing dirty working paths intact.

**Conclusion**: The Phase 2 baseline is verified, fully reproducible, and preserved as an immutable historical record.
