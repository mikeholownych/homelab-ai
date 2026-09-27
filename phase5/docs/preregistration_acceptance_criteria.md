# Phase 5 Preregistration and Acceptance Criteria Specification

---

## 1. Objective and Operating Guiding Principles

Phase 5 transitions the system from offline candidate qualification into a live, durable heterogeneous engineering execution service operating on physical Dell T5820 hardware.

### Foundational Invariants:
1. **Engineering Correctness Over Speed**: Priority is independently accepted, complete, and maintainable software engineering deliverables.
2. **Campaign Isolation**: Zero interference with the concurrent autonomous-readiness campaign (Gateway PID 986, OpenCode PID 3130937, Tunnel PID 2093382).
3. **Supervisor Authority**: Models are untrusted workers. The control plane owns admission, leasing, workflow DAGs, fencing, and factual completion reporting.
4. **Honest Accounting**: All registered task attempts, failures, and recovery transitions are captured with exact denominators.

---

## 2. The 10 Registered Independent Acceptance Gates

| Gate # | Acceptance Gate | Description & Standard | Hard Threshold |
| :--- | :--- | :--- | :--- |
| **Gate 1** | **Phase 4 Evidence Verification** | Cryptographic verification of Phase 4 manifest and 115 passing baseline tests. | 100% matched, 0 failures |
| **Gate 2** | **Deployment-State Determination** | Factual audit of Phi-4 deployment ambiguity (registry qualification vs live daemon). | Authoritative audit documented |
| **Gate 3** | **Physical B65 Resource Feasibility** | Mathematical proof of VRAM coexistence constraints and selected operating topology. | 0 physical VRAM oversubscriptions |
| **Gate 4** | **Live Model & Tool Contract Qualification** | Verification of OpenAI-compatible endpoints (`/v1/chat/completions`, `tools`). | Zero malformed tool calls ($T_F = 1.0$) |
| **Gate 5** | **Complete Heterogeneous Execution** | Full path execution via `aes-cli` with artifact handoffs and independent validation. | 100% path traversed |
| **Gate 6** | **Evidence-Based Role Routing** | Bounded router dispatching by demonstrated capability, resource state, and task class. | Zero routing to unqualified roles |
| **Gate 7** | **Durable Interruption & Recovery** | Process SIGKILL, lease expiration, and crash recovery with monotonic fencing tokens. | 100% state preserved, 0 stale commits |
| **Gate 8** | **Sustained Representative Reliability** | Multi-task cohort execution across Defect Repair, Multi-File, Test Dev, Maintainability. | Task Acceptance Rate $A_R \ge 0.80$ |
| **Gate 9** | **Artifact Delivery & Supervisor Accuracy** | Content-addressed CAS delivery, tamper verification, factual supervisor records. | 100% CAS tamper detection |
| **Gate 10** | **Campaign Isolation & Rollback** | Protected PIDs untouched; verified one-step rollback procedure to commit `45b736f`. | 0 process disruptions, rollback proven |

---

## 3. Registered Task Cohort

Evaluation is conducted on a registered 12-task cohort across 4 engineering task classes:

1. **Defect Repair (3 tasks)**:
   - `defect_repair_repo`
   - `defect_repair_series_repo`
   - `heldout_defect_01_off_by_one_paging`
2. **Multi-File Implementation (3 tasks)**:
   - `multi_file_repo`
   - `multi_file_tax_repo`
   - `heldout_multifile_01_rate_limiter`
3. **Test Development (3 tasks)**:
   - `test_dev_repo`
   - `test_dev_auth_repo`
   - `heldout_testdev_01_fencing_invariant`
4. **Maintainability / Refactoring (3 tasks)**:
   - `maintainability_repo`
   - `maintainability_config_repo`
   - `heldout_maintain_01_decouple_notifier`

---

## 4. Controlled Budgets and Stopping Rules

- **Execution Budgets**:
  - Max tool calls per assignment: 10
  - Max pre-validation repair attempts: 2
  - Max wall-clock time per work order: 300 seconds
  - Concurrency: 1 (serialized to eliminate host resource contention)
- **Stopping Rules**:
  - Any unauthorized mutation outside work-order scope aborts the task immediately (`ScopeGuard` violation).
  - Any attempt to disrupt or signal protected PIDs terminates execution immediately.
  - If physical B65 capacity is exhausted or unavailable, the system reports the exact resource blocker.

---

## 5. Rollback Specification

In the event of an unrecoverable failure or regression:
- Worktree revert: `git reset --hard 45b736f`
- Gateway restore: verified endpoint `http://127.0.0.1:18010/v1` (`engineering/b0`)
- Artifact cleanup: preserve evidence bundle without modifying historical Phase 3 or Phase 4 manifests.
