# Phase 0 Architecture and Prototype: Preregistered Acceptance Criteria

**Document ID**: PREREG-PHASE0-2026-09-26  
**Status**: REGISTERED (PRE-IMPLEMENTATION)  
**Author**: Antigravity Autonomous Engineering Agent  
**Base Repository Commit**: `1aa374a`  
**Isolated Branch**: `phase0-offline-prototype`  
**Isolated Worktree**: `.worktrees/phase0-offline-prototype`  
**Execution Environment**: Linux x86_64, Python 3.12.3, SQLite 3.45.1, Pydantic 2.13.2, SQLAlchemy 2.0.49, Pytest 9.0.3  

---

## 1. Baseline Isolation Invariants

1. **Campaign Isolation**: The active T5820 v1.7 autonomous-readiness campaign (and running processes PID 986 hermes gateway, PID 3130937 opencode) must not be disturbed, signaled, or modified.
2. **Checkout Integrity**: The main repository working directory and its pre-existing unstaged modifications (`docs/README.md`, `orchestrator_gateway/*`, `orchestrator_runtime/*`, `tests/*`) must remain untouched. All Phase 0 code, tests, and artifacts reside strictly inside `.worktrees/phase0-offline-prototype`.
3. **Deterministic Offline Execution**: The prototype must run entirely offline without network access, live GPU allocation, production credentials, or external API endpoints.

---

## 2. Functional Acceptance Criteria (F-xx)

- **F-01 (Disconnected Interface & Session Independence)**: The human interface submits a canonical work order and disconnects. The workflow engine continues execution to terminal disposition (`ACCEPTED`, `REJECTED`, or `FAILED`) autonomously. The interface can query terminal state and audit evidence post-hoc.
- **F-02 (Canonical Work-Order Contract & Compilation)**: Work-order compilation normalizes raw human instructions, preserves original intent, identifies material ambiguities (surfacing them without silent assumption), and generates a tamper-evident work order bound to repository ID and baseline commit.
- **F-03 (Versioned Work-Order Evolution & Supersession)**: Modifying a work order creates a new incremented version. When a version supersedes an earlier version, active assignments are invalidated, active capability tokens are revoked, and completed artifacts are partitioned by version lineage.
- **F-04 (Dependency-Aware Planning)**: The planning layer decomposes work orders into a directed acyclic execution plan (e.g., reproduction -> patch generation -> independent validation) where downstream tasks depend on verifiable output artifacts of upstream tasks. Planning does NOT issue execution capabilities.
- **F-05 (Empirical Worker Capability Registry)**: Worker capability profiles are bound to the complete deployed configuration (model revision, quantization, tokenizer, context limits, empirical task success rates). Advertised benchmark scores are advisory; observed execution passes are authoritative.
- **F-06 (Capability-Aware Routing with Independence Constraints)**: The router dynamically selects workers based on task requirements, empirical capability profiles, and independence constraints (e.g., the worker that produced an artifact cannot serve as the independent validator for that artifact). A deterministic fallback is taken if no worker qualifies.
- **F-07 (Artifact-Centered Execution & Provenance)**: All inter-stage exchanges occur via immutable, content-addressed (SHA-256) artifacts. Each artifact records its producing worker ID, capability token ID, work-order version, input artifact hashes, and execution evidence.
- **F-08 (Independent Validation & Acceptance)**: Acceptance is determined solely by an independent validator executing in an isolated evaluation harness with pre-registered checks. Passing self-authored tests or model agreement is insufficient for acceptance.
- **F-09 (Bounded Repair Loop)**: When a worker-produced artifact fails independent validation, the bounded repair controller classifies the failure (e.g., assertion failure vs syntax error vs scope violation), generates a scoped repair work order carrying the failed artifact and diff, and re-submits within remaining retry budgets.

---

## 3. Authority and Security Acceptance Criteria (A-xx)

- **A-01 (Instruction != Authorization)**: A raw human instruction or planning step cannot authorize mutations. The execution control plane is the sole issuer of capability tokens.
- **A-02 (Narrowly Scoped Capability Tokens)**: Every worker execution requires an unforgeable, scoped capability token specifying:
  - Authorized Work-Order ID & Version
  - Permitted Mutation Paths (exact path whitelist)
  - Permitted Commands/Tools
  - Resource Budgets (retries, timeouts)
  - Monotonic Fencing Token & Expiration Timestamp
- **A-03 (Scope Boundary Enforcement)**: Any worker attempt to mutate files outside authorized paths or execute unauthorized tools fails closed with a recorded security violation.
- **A-04 (Fail-Closed on Expired or Revoked Authority)**: Capabilities with expired timestamps or marked revoked in the control plane are rejected immediately upon presentation.
- **A-05 (Missing or Contradictory Authority Fails Closed)**: Work orders with missing, ambiguous, or contradictory authorizations are rejected at the admission gate before any planning or worker dispatch.
- **A-06 (Untrusted Worker Principle)**: Workers cannot alter their own capability tokens, mutation scopes, budgets, validators, or acceptance criteria.

---

## 4. Recovery and Concurrency Acceptance Criteria (R-xx)

- **R-01 (Duplicate Assignment Delivery)**: Duplicate dispatch of the same task assignment is idempotent. Re-delivery does not spawn parallel conflicting executions.
- **R-02 (Worker Crash Before Submission)**: If a worker crashes while holding a lease, the lease expires. The orchestrator reassigns the task with an incremented fencing token.
- **R-03 (Worker Crash After Artifact Submission)**: If a worker crashes after storing the artifact but before acknowledgment, replay detects the existing artifact hash and completes idempotently.
- **R-04 (Stale Fencing Token / Late Worker Submission)**: A worker submitting an artifact after its lease has expired and a new lease was issued is rejected with `STALE_FENCING_TOKEN`.
- **R-05 (Orchestrator Restart & Interruption Recovery)**: The orchestrator can be stopped and restarted at any point during workflow execution. On boot, it recovers state from SQLite, audits open leases, and resumes execution from the last proven artifact.
- **R-06 (Stale Artifact Rejection)**: A review or repair artifact referencing an obsolete work-order version or mismatched input hash is rejected by the control plane.
- **R-07 (Work-Order Invalidation During Active Execution)**: When a work order is superseded while a worker is executing, the worker's subsequent submission is rejected with `SUPERSEDED_WORK_ORDER`.
- **R-08 (Retry Budget Exhaustion)**: When repair attempts exceed the work-order retry budget, execution terminates in `FAILED_BUDGET_EXHAUSTED` and all diagnostic evidence is preserved.
- **R-09 (Single Authoritative Acceptance)**: For any work-order version, at most one artifact lineage can be marked `ACCEPTED`.

---

## 5. Technology Decision and Comparison Criteria (T-xx)

- **T-01 (Comparative Evaluation)**: Formally compare:
  1. Transactional Database-Backed Workflow (SQLite ACID state machine with monotonic leasing and lease fencing)
  2. Durable Workflow Engine (Temporal/Restate architecture)
  3. Database-plus-Broker (Redis Streams / RabbitMQ decoupled queue)
- **T-02 (Executable Proofs)**: Provide runnable contract tests demonstrating fencing, lease timeouts, and atomic state transitions under transactional persistence vs broker decoupled queue.
- **T-03 (Smallest Sufficient Architecture)**: Select the simplest architecture satisfying all invariant semantics for local multi-worker execution (dual Intel Arc Pro B65 setup) without unnecessary operational overhead.

---

## 6. Maintainability and Code Quality Criteria (M-xx)

- **M-01 (Modular Cohesion & Strict Typing)**: Clean modular boundaries with 100% typed Python (dataclasses, Pydantic models, typed enums). No circular dependencies.
- **M-02 (Zero Dead Code / No Mock Facades)**: Every module has a concrete purpose and is exercised by tests. No placeholder interfaces masquerading as implemented features.
- **M-03 (100% Test Pass Rate & Full Suite Execution)**: The complete test suite (unit, contract, failure-injection, recovery, e2e) passes cleanly.
- **M-04 (Tamper-Evident Evidence Bundle)**: A final manifest recording sha256 checksums of all implementation files, test logs, and decision records.
