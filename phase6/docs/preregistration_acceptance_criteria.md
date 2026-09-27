# Autonomous Engineering System: Phase 6 Preregistration & Acceptance Contract

## 1. Executive Summary & Purpose

This document freezes the Phase 6 acceptance contract, evaluation gates, and real-repository task population prior to executing autonomous engineering work on real repositories.

In strict compliance with Phase 6 instructions:
- Ten explicit acceptance gates are registered.
- Four real-repository engineering tasks across distinct complexity classes are preregistered.
- Exact stopping rules, repair limits, and independent validation oracles are defined.
- Every registered attempt (including blocked, failed, and rejected runs) will be preserved in the final ledger.

---

## 2. The Ten Independent Acceptance Gates

| Gate ID | Gate Name | Evaluation Objective | Success Criteria |
| :---: | :--- | :--- | :--- |
| **Gate 1** | **Phase 5 Baseline & Topology Verification** | Verify baseline commit `b337bc0`, 128 regression tests passing, and empirical serving topology. | 128/128 tests pass; topology audit accurately distinguishes live physical serving from adapter inference. |
| **Gate 2** | **Persistent Service Startup & Recovery** | Launch persistent engineering daemon (`aes-service`), detach client, verify WAL state and resume after simulated restart. | Service maintains durable SQLite WAL state; recovers active tasks without data loss. |
| **Gate 3** | **Real-Repository Work-Order Admission** | Submit real work orders via `aes-cli`; compile into canonical work orders; evaluate scope authorization. | Work orders compile deterministically; invalid scopes rejected; receipts issued. |
| **Gate 4** | **Repository Investigation & Bounded Planning** | Inspect target repository AST, files, and dependencies; generate execution plan strictly within authorized paths. | Plan targets only authorized paths; includes investigation evidence. |
| **Gate 5** | **Correct Implementation & Meaningful Tests** | Live worker authoring patch against real repository code; author meaningful tests that catch defects. | Patch cleanly applies; tests verify target behavior and fail against unpatched defect. |
| **Gate 6** | **Independent Review & Bounded Repair** | Reviewer inspects exact patch artifact; reports findings with source lines; repairer addresses findings within budget. | Review identifies actionable findings; repairer resolves findings without scope creep (max 3 cycles). |
| **Gate 7** | **Exact-Artifact Validation & CAS Delivery** | Independent sandbox executes acceptance tests against exact patched worktree; export deliverable bundle. | Independent validator confirms 100% checks pass; CAS bundle with SHA-256 manifest produced. |
| **Gate 8** | **Revision, Cancellation & Fencing** | Test human work-order amendment, scope restriction, cancellation, and monotonic fencing rejection. | Stale tokens rejected; cancelled tasks revoked; partial artifacts preserved. |
| **Gate 9** | **Sustained Operation & Resource Isolation** | Run batch of real-repo work orders; measure memory, tokens, latency, and campaign process isolation. | PIDs 986, 3130937, 2093382 undisturbed; zero GPU OOM; 100% task accounting. |
| **Gate 10** | **Human Integration Authority** | Accepted deliverables presented with patch application instructions; no auto-merge without human sign-off. | Explicit human integration instructions generated; supervisor marks disposition. |

---

## 3. Real-Repository Task Population

The evaluation cohort targets production modules within the real `aihost` repository infrastructure (`orchestrator_gateway`, `orchestrator_contract`, `tools`), executed in dedicated disposable worktrees:

```
Target Repository: aihost (Production Infrastructure)
Baseline Revision: b337bc0
Execution Environment: Isolated disposable git worktree / sandbox
```

### 3.1 Task Specifications

#### Task 1: Defect Repair (`real-repo-dr-01`)
- **Intent**: Harden `orchestrator_gateway/server.py` request validation: reject invalid client payloads (missing model name or negative `max_tokens`) with structured HTTP 400 JSON errors instead of unhandled internal server exceptions.
- **Authorized Mutation Paths**: `orchestrator_gateway/server.py`, `tests/test_orchestrator_gateway.py`
- **Prohibited Operations**: Modifying routes outside gateway validation; modifying client token file.
- **Acceptance Criteria**:
  1. `pytest tests/test_orchestrator_gateway.py` passes 100%.
  2. Sending `{"model": "", "messages": []}` returns HTTP 400 with `error` JSON object.
  3. Existing valid requests continue to pass.
- **Resource Budget**: Max 2 repair attempts, max 60s live model latency.

#### Task 2: Multi-File Feature & Integration (`real-repo-mf-02`)
- **Intent**: Implement request correlation and latency tracking across `orchestrator_contract` and `orchestrator_gateway`.
- **Authorized Mutation Paths**:
  - `orchestrator_contract/core.py`
  - `orchestrator_gateway/server.py`
  - `tests/test_orchestrator_gateway.py`
- **Acceptance Criteria**:
  1. `orchestrator_contract/core.py` defines `RequestTelemetryMetadata` with correlation ID and timestamp.
  2. `orchestrator_gateway/server.py` injects `X-Request-Correlation-ID` and `X-Gateway-Latency-MS` into HTTP responses.
  3. `pytest tests/test_orchestrator_gateway.py` passes and asserts header presence.
- **Nontrivial Review & Repair Requirement**: The initial review must flag missing header sanitization, prompting a bounded repair pass that successfully resolves the finding.
- **Resource Budget**: Max 3 repair attempts, max 120s wallclock.

#### Task 3: Meaningful Test Quality Improvement (`real-repo-td-03`)
- **Intent**: Expand `tests/test_orchestrator_gateway.py` with parameterized regression coverage for edge-case HTTP requests (truncated bodies, special characters in model names, empty prompts).
- **Authorized Mutation Paths**: `tests/test_orchestrator_gateway.py`
- **Acceptance Criteria**:
  1. Test suite additions cover at least 3 new edge cases.
  2. Tests are meaningful: each test must fail if the corresponding validation in `orchestrator_gateway/server.py` is removed or inverted.
  3. 100% test pass rate on target repository.
- **Resource Budget**: Max 2 repair attempts, max 60s wallclock.

#### Task 4: Maintainability with Behavioral Preservation (`real-repo-mt-04`)
- **Intent**: Refactor monolith validation logic in `orchestrator_contract/core.py` into dedicated, modular validator helpers while strictly preserving existing API and runtime behavior.
- **Authorized Mutation Paths**: `orchestrator_contract/core.py`
- **Acceptance Criteria**:
  1. All 18 existing contract tests in `tests/test_contract_validation.py` pass without modification.
  2. Validation logic extracted into clean, reusable functions (`validate_endpoint_spec`, `validate_resource_limits`).
  3. Cyclomatic complexity of main class methods reduced without breaking caller contracts.
- **Resource Budget**: Max 2 repair attempts, max 60s wallclock.

---

## 4. Operational Boundaries, Stopping Rules & Error Policy

1. **Repair Limits**:
   - Maximum 3 repair cycles per task step.
   - Any repair modifying files outside the authorized mutation scope triggers immediate `SCOPE_VIOLATION` termination.
2. **Stopping Rules**:
   - Immediate stop if host RAM falls below 8.0 GiB or protected processes (PID 986, 3130937, 2093382) exit or degrade.
   - Immediate stop if an uncontained process attempts unauthorized network egress or destructive operations.
3. **No Laundering Policy**:
   - If a model generates malformed code or fails validation, the failed attempt is recorded in the task ledger with its full trace.
   - Retries increment the attempt counter ($Attempt_1, Attempt_2, \dots$) and all denominators are reported honestly.
