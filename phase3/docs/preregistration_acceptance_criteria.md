# Phase 3 Pre-Registration Acceptance Criteria
## Sustained Reliability, Human Work-Order Interface and Empirical Capability Characterization

**Date of Pre-Registration**: 2026-09-27  
**Workspace**: `/home/mike/Projects/aihost/.worktrees/phase3-operational-service`  
**Base Commit**: `be4958cb04017d79e3686979376935c09f899094` (`be4958c`)  
**Frozen Evaluation Gates**: 11 Gates  

---

## 1. Non-Negotiable Invariants

1. **Human Interface Separation**: The human-facing interface (CLI/OpenCode adapter) submits instructions, views status, provides clarifications, and receives deliverables. It is strictly outside the execution control plane and cannot issue execution capabilities directly, bypass admission evaluation, or mark tasks accepted.
2. **Session Independence**: Submitted work orders must execute to terminal state asynchronously and durably regardless of whether the interface session remains connected, disconnects, or terminates.
3. **Immutable Lineage & Invalidation**: Work-order revisions produce new canonical versions with explicit parent hashes. Any material revision invalidates affected in-flight worker assignments, revokes capability tokens, and enforces monotonic fencing token rejection for stale commits.
4. **Untrusted Workers & Supervisor Authority**: Models, execution adapters, and reviewers are untrusted workers. The control plane supervisor derives completion and terminal disposition exclusively from observed, verifiable artifacts, tool logs, and validator exit codes.
5. **Campaign Isolation**: The active T5820 autonomous-readiness campaign, OpenCode runner (`PID 3130937`), gateway (`PID 986`), SSH tunnel (`PID 2093382`), and the primary repository checkout (`/home/mike/Projects/aihost`) are strictly protected. No competing instances, worker restarts, or model/quantization changes are permitted.

---

## 2. Pre-Registered Acceptance Gates

### Gate 1: Phase 2 Baseline Verification & Audit
- **Criteria**: Complete SHA-256 verification of 63 files against `phase2/evidence/manifest.sha256`. 100% passing of the 72 baseline tests. Explicit categorization of live vs. simulated evidence and identification of sample-size limits on prior cooperative claims.
- **Pass Condition**: `phase3/docs/phase2_independent_verification.md` completed; all 72 inherited tests pass with 0 regressions.

### Gate 2: Minimum Usable Human Work-Order Interface (CLI & Adapter)
- **Criteria**: Persistent CLI supporting:
  1. `submit`: Submits work order with raw text, repo path, base commit, mutation paths, and acceptance criteria.
  2. `inspect`: Displays compiled work order, contract hash, authorization scope, and any material ambiguities.
  3. `clarify`: Submits explicit clarification resolving ambiguities or approving scope.
  4. `status`: Queries authoritative workflow state, active assignments, budgets, and audit events.
  5. `pause` / `resume` / `cancel`: Controls workflow execution state via control plane transitions.
  6. `revise`: Submits bounded revision to an active work order.
  7. `deliver`: Exports final accepted artifact, unified diff, validation report, and local application instructions.
- **Pass Condition**: Full programmatic and CLI integration tests validating all 7 operations under detached session conditions.

### Gate 3: Bounded Work-Order Revision & Authority Invalidation
- **Criteria**: Structured revision taxonomy:
  - `CLARIFICATION`: Refines prompt without expanding scope or criteria. Re-runs admission.
  - `SCOPE_EXPANSION`: Adds authorized mutation paths. Invalidates all active assignments/capabilities. Requires new authorization.
  - `SCOPE_RESTRICTION`: Removes mutation paths. Invalidates affected assignments.
  - `CRITERIA_MUTATION`: Modifies acceptance criteria. Invalidates downstream review and validation results.
  - `CANCELLATION`: Revokes all active leases and terminates work order cleanly.
- **Pass Condition**: Stale workers attempting to commit against a superseded work-order version or fencing token are atomically rejected by SQLite CAS transactions.

### Gate 4: Usable External Artifact Delivery & Local Inspection
- **Criteria**: Deliverable bundle exposing:
  - Exact baseline repository commit and repository ID.
  - Formatted unified diff patch and changed file inventory.
  - Independent validator test execution logs and exit codes.
  - Review report findings and advisory recommendations.
  - Supervisor terminal disposition.
  - Reproducible local commands (`git apply --check <patch_file>`, `git apply <patch_file>`).
  - Tamper detection: modifying artifact contents post-validation immediately invalidates acceptance.
- **Pass Condition**: Delivery subsystem tests prove patch applicability to clean checkouts and cryptographic tamper rejection.

### Gate 5: Representative Engineering Reliability Cohort (4 Classes, Multiple Fixtures)
- **Criteria**: Evaluation of at least 2 distinct repository fixtures per engineering class (minimum 8 registered tasks total):
  1. **Class 1 (Defect Repair)**: Boundary/logic bugs in mathematical/statistical utilities (`stats_utils.py`, `math_series.py`).
  2. **Class 2 (Multi-File Implementation)**: Coupled business logic spanning multiple modules (`processor.py` + `discounts.py`, `order_service.py` + `tax_calculator.py`).
  3. **Class 3 (Meaningful Test Development)**: Unit test suite generation with rigorous boundary and security assertions (`test_token_utils.py`, `test_auth_jwt.py`).
  4. **Class 4 (Maintainability & Deduplication)**: Refactoring duplicate logic without functional alteration (`currency_formatters.py`, `config_loader.py`).
- **Pass Condition**: Every registered task attempt is recorded with numerator/denominator (accepted / registered) and evaluated in clean Bubblewrap sandboxes.

### Gate 6: Empirical Capability Characterization of Physical Dual B65 Workers
- **Criteria**: Record the exact deployed hardware, runtime, and model configuration for both Intel Arc Pro B65 cards (`worker-b65-0` and `worker-b65-1`):
  - PCIe slots, VRAM capacity, driver (`xe`), Level Zero runtime, vLLM version, PyTorch XPU version.
  - Model ID (`cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`), quantization (`AWQ-4bit`), TP topology, context window (64K max / 16K active), tool parser (`qwen3_coder`).
  - Empirical skill records distinguishing synthetic benchmark claims from local measured pass rates.
- **Pass Condition**: Capability registry enforces empirical evidence provenance (`EvidenceSource.EMPIRICAL_DEPLOYED_MEASUREMENT`) and independence (`author != reviewer`).

### Gate 7: Matched Single-Worker vs. Cooperative Execution Comparison
- **Criteria**: Matched evaluation across multiple runs comparing:
  - Single-worker implementation with independent validation.
  - Cooperative implementation, independent review, and bounded repair.
  - Metrics: pre-validation defect detection rate, validation retry cycles, review finding validity, total resource budget.
- **Pass Condition**: Empirical comparison dataset demonstrating when cooperative review is advantageous vs. where single-worker execution is optimal.

### Gate 8: Real-Task Interruption, Revocation & Durable Recovery
- **Criteria**: Inject bounded interruptions during real registered tasks:
  1. Worker crash during implementation step.
  2. Worker crash during review step.
  3. Orchestrator process restart mid-DAG execution.
  4. Worker lease timeout & atomic reassignment to replacement worker.
  5. Delayed commit by zombie worker rejected by monotonic fencing token.
  6. In-flight work-order revision superseding active worker leases.
  7. Work-order pause and resume across persistent storage.
- **Pass Condition**: 100% clean recovery without SQLite database corruption, state inconsistency, or unauthorized writes.

### Gate 9: Supervisor-Authoritative Completion & Audit Verification
- **Criteria**: Supervisor derives all completion records from immutable evidence:
  - Tool invocations and exit codes verified from containment logs.
  - Test outcomes derived directly from independent validator process results.
  - Incomplete worker handoffs cannot conceal valid execution traces.
  - Passing worker claims cannot override failed validation tests.
- **Pass Condition**: Audit bundle verification tests confirm strict derivation and tamper-evidence.

### Gate 10: Phase 4 Model-Evaluation Boundary Specification
- **Criteria**: Complete written design for candidate model and quantization evaluation on dual B65 hardware:
  - Candidate models (e.g. Qwen2.5-Coder 32B, DeepSeek-Coder-V2-Lite, Phi-4).
  - Quantization formats (AWQ-4bit, FP8, Q4_K_M).
  - Evaluation protocol under matched aggregate compute budgets.
  - Primary metrics: independent acceptance rate, scope compliance, tool fidelity.
- **Pass Condition**: Documented in `phase3/docs/phase4_model_evaluation_boundary.md`.

### Gate 11: Non-Contention, Tamper-Evident Manifest & Final Verification
- **Criteria**: Undisturbed campaign infrastructure (PID 986, 3130937, 2093382); unmodified `/home/mike/Projects/aihost`; full SHA-256 manifest; standalone demo returning `PHASE_3_OPERATIONAL_ENGINEERING_BASELINE: PROVEN`.
- **Pass Condition**: `phase3/evidence/manifest.sha256` verified; `run_demo.py` exits 0 with authoritative disposition.

---

## 3. Evaluation Schedule and Stopping Rules

- **Stopping Condition**: Execution halts immediately if a hard gate fails, if SQLite integrity check fails, or if contention with the active T5820 campaign is detected.
- **Registration Integrity**: Every registered work order must be accounted for in final reporting. No failed attempts may be discarded or omitted from denominators.
