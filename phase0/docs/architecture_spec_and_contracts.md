# Architecture Specification and Specialized Layer Contracts

**Document ID**: ARCH-SPEC-PHASE0-2026-09-26  
**Status**: APPROVED / IMPLEMENTATION BASELINE  
**Author**: Antigravity Autonomous Engineering Agent  
**Context**: Offline Architecture and Prototype, Phase 0  

---

## 1. System Mission and Core Philosophy

The Autonomous Engineering System is a specialized, work-order-driven execution engine designed to perform correct, verifiable, and maintainable software engineering tasks. It is fundamentally **not a chatbot**. The durable engineering work order is the central abstraction through which human direction, constraints, and policies enter the system. The execution control plane operates independently of any active user interface session.

### 1.1 Non-Negotiable Invariants

1. **Instruction != Authorization**: A raw human instruction is an intent proposal, not an authorization to mutate state.
2. **Intent Preservation**: Compilation must faithfully capture the intended outcome and surface material ambiguities rather than silently choosing arbitrary interpretations.
3. **Execution Control Plane as Sole Authority**: Admission, capability token issuance, task state transitions, and terminal dispositions belong exclusively to the control plane.
4. **Untrusted Worker Principle**: LLMs, execution adapters, and tools are untrusted workers. Worker agreement, model confidence, or self-authored passing tests never constitute task acceptance.
5. **Fail-Closed Authority**: Missing, expired, ambiguous, or contradictory authority fails closed.
6. **Artifact-Centered Provenance**: All work products are content-addressed, immutable artifacts cryptographically bound to exact inputs, work-order versions, and producing worker configurations.
7. **Lineage Invalidation on Revision**: Superseding a work order revokes all active capabilities, cancels in-flight assignments, and prevents stale submissions from committing.
8. **Independent Acceptance Gate**: Final acceptance is decided solely by an independent validation component using pre-registered verification criteria in an isolated execution harness.
9. **Logical vs Physical Separation**: Clear separation between logical architecture layers and deployment boundaries. In Phase 0, components run as cohesive in-process modules with explicit API boundaries; no spurious network hops or distributed infrastructure are introduced.

---

## 2. Logical Architecture and Layer Contracts

```
[ Human Interface ]
       │ (Raw Intent / Direction)
       ▼
[ Intent Normalizer & Compiler ] ────► [ Work Order Contract (v1, v2...) ]
                                                     │
       ┌─────────────────────────────────────────────┘
       ▼
[ Authority & Admission Gate ] ────► [ Scoped Capability Tokens ]
       │
       ▼
[ Planning & Decomposition ] ─────► [ Directed Task Execution Graph ]
       │
       ▼
[ Capability-Aware Router ] ◄────► [ Worker Capability Registry ]
       │
       ▼
[ Durable Workflow Scheduler ] ───► [ Worker Lease & Fencing Token ]
       │                                     │
       ▼                                     ▼
[ Simulated Worker Adapter ] ──────► [ Tool Scope Guard / Execution ]
       │
       ▼
[ Content-Addressed Artifact Store ] ──► [ Patch / Build / Test Logs ]
       │
       ▼
[ Independent Acceptance Validator ] ──► [ Tamper-Evident Verdict ]
       │
       ▼
[ Bounded Repair Controller ] (on validation failure -> re-plan with bounded scope)
       │
       ▼
[ Terminal Disposition: ACCEPTED / REJECTED / FAILED_BUDGET_EXHAUSTED ]
```

---

### Layer 1: Human Interface Adapters
- **Responsibilities**: Ingest instructions from humans (via CLI, detached session files, or RPC), poll or subscribe to asynchronous execution updates, and render durable work-order disposition and audit traces. Disconnection must not affect execution.
- **Inputs**: Raw prompt string, target repository path/URI, baseline commit, budget preferences.
- **Outputs**: `RawInstructionEnvelope`.
- **Authority**: None. Cannot authorize mutations or bypass compilation.
- **Failure Behavior**: Rejects unparseable inputs; surfaces disconnects as benign client-side events.
- **Contract Schema**:
  - `instruction_id` (Authoritative, UUIDv4)
  - `raw_text` (Authoritative, string)
  - `submitted_at` (Authoritative, ISO8601 UTC)
  - `source_channel` (Authoritative, string: "cli", "file", "harness")

---

### Layer 2: Intent Normalization and Work-Order Compilation
- **Responsibilities**: Parse raw instructions against repository context, identify material ambiguities, extract bounded mutation scopes, specify prohibited operations, and compile a canonical `WorkOrder`.
- **Inputs**: `RawInstructionEnvelope`, Repository Manifest, Policy Version.
- **Outputs**: `WorkOrder` (Draft or Admissible), `AmbiguityReport`.
- **Authority**: Proposes scopes, acceptance criteria, and plan structures. Does **NOT** issue execution capabilities or grant permissions.
- **Failure Behavior**: If material ambiguity is detected (e.g., unspecified target module, conflicting constraints), compilation halts with status `AMBIGUOUS_REQUIRES_CLARIFICATION`.
- **Contract Fields**:
  - `work_order_id` (Authoritative, UUIDv4)
  - `version` (Authoritative, integer >= 1)
  - `intended_outcome` (Authoritative, string)
  - `ambiguities_identified` (Authoritative, list of strings)
  - `target_repository` (Authoritative, repository identity and commit)
  - `proposed_mutation_scope` (Advisory, file path patterns)
  - `acceptance_criteria` (Authoritative, list of validation rules)

---

### Layer 3: Authority and Admission Gate
- **Responsibilities**: Evaluate admissible work orders against system security policies, human approval tokens, and repository constraints. Issue narrowly scoped, cryptographic, time-bounded `CapabilityToken`s.
- **Inputs**: `WorkOrder`, `HumanApprovalEnvelope` (optional/required per policy), `SecurityPolicy`.
- **Outputs**: `AdmissionDecision` (`ADMITTED` | `DENIED`), `CapabilityToken`.
- **Authority**: Sole entity authorized to mint `CapabilityToken`s and permit task dispatch.
- **Failure Behavior**: Fails closed. If approvals are expired, signatures invalid, or scope violates policy, status is `DENIED` with explicit security rejection reason.
- **Contract Fields**:
  - `token_id` (Authoritative, UUIDv4)
  - `work_order_id` (Authoritative, UUIDv4)
  - `work_order_version` (Authoritative, integer)
  - `authorized_paths` (Authoritative, list of glob patterns)
  - `authorized_tools` (Authoritative, list of tool names)
  - `max_budget_retries` (Authoritative, integer)
  - `issued_at` (Authoritative, ISO8601 UTC)
  - `expires_at` (Authoritative, ISO8601 UTC)
  - `revoked` (Authoritative, boolean)
  - `signature_hash` (Authoritative, SHA-256 HMAC of above fields)

---

### Layer 4: Planning and Dependency Decomposition
- **Responsibilities**: Decompose admitted work orders into a directed acyclic execution plan (`ExecutionPlan`) comprising discrete task steps (e.g., Investigation, Test Reproduction, Patch Generation, Pre-Validation Review).
- **Inputs**: Admitted `WorkOrder`, Repository Schema.
- **Outputs**: `ExecutionPlan` containing ordered `TaskStep` nodes with explicit input/output artifact bindings.
- **Authority**: Advisory planning only. Cannot grant capability tokens or execute tasks directly.
- **Failure Behavior**: Plan validation fails if cycles are detected or required dependencies are unsatisfiable.
- **Contract Fields**:
  - `plan_id` (Authoritative, UUIDv4)
  - `work_order_id` (Authoritative, UUIDv4)
  - `work_order_version` (Authoritative, integer)
  - `steps` (Authoritative, list of `TaskStepDefinition`)
  - `dependencies` (Authoritative, map of step_id -> list of prerequisite step_ids)

---

### Layer 5: Empirical Worker Capability Registry
- **Responsibilities**: Maintain immutable records of deployed worker hardware, model configurations, quantization formats, and empirical benchmark evidence.
- **Inputs**: Worker deployment registration manifests, empirical benchmark records.
- **Outputs**: `WorkerCapabilityProfile`.
- **Authority**: Authoritative source of worker hardware and empirical competency data.
- **Failure Behavior**: Workers lacking verified empirical benchmarks are marked unverified and barred from critical role assignments.
- **Contract Fields**:
  - `worker_id` (Authoritative, string)
  - `hardware_target` (Authoritative, e.g. "Intel-Arc-Pro-B65")
  - `model_name` (Authoritative, string, e.g. "Qwen/Qwen2.5-Coder-32B-Instruct")
  - `quantization` (Authoritative, string, e.g. "FP8", "INT4", "BF16")
  - `context_window` (Authoritative, integer)
  - `verified_skills` (Authoritative, set of strings: "investigation", "code_patch", "unit_test", "review")
  - `empirical_pass_rate` (Derived, float 0.0 - 1.0)
  - `status` (Authoritative: "HEALTHY", "DEGRADED", "OFFLINE")

---

### Layer 6: Capability-Aware Routing
- **Responsibilities**: Match planned task requirements against active worker capability profiles, current system load, and strict independence constraints (e.g., the worker reviewing an artifact must not be the worker that authored it).
- **Inputs**: `TaskStepDefinition`, `CapabilityToken`, Active Registry Profiles, Task History.
- **Outputs**: `RoutingDecision` (`worker_id`, `assigned_role`, `lease_duration`).
- **Authority**: Recommends assignments; does not grant capabilities or bypass admission.
- **Failure Behavior**: If no healthy worker meets capability or independence constraints, returns `ROUTING_UNAVAILABLE` triggering deterministic fallback or queuing.
- **Contract Fields**:
  - `assignment_id` (Authoritative, UUIDv4)
  - `task_id` (Authoritative, string)
  - `selected_worker_id` (Authoritative, string)
  - `fencing_token` (Authoritative, monotonic integer)
  - `lease_expires_at` (Authoritative, ISO8601 UTC)

---

### Layer 7: Durable Workflow Scheduling and Recovery
- **Responsibilities**: Manage the transactional state machine of work orders and task steps. Issue leases with monotonic fencing tokens, detect timeouts, handle worker crashes, recover from process termination, and ensure exactly-once terminal commitment per work order version.
- **Inputs**: `ExecutionPlan`, `RoutingDecision`, Worker Execution Submissions.
- **Outputs**: Durable DB State, Monotonic Leases, Task State Transitions.
- **Authority**: Sole authority governing durable lifecycle transitions (`PENDING`, `DISPATCHED`, `COMPLETED`, `FAILED`, `TERMINAL`).
- **Failure Behavior**: Leased tasks not completed within lease duration expire automatically; fencing token increments on re-dispatch. Stale submissions are rejected.
- **Contract Fields**:
  - `work_order_id` (Authoritative)
  - `state` (Authoritative: `DRAFT`, `ADMITTED`, `PLANNING`, `EXECUTING`, `VALIDATING`, `ACCEPTED`, `REJECTED`, `FAILED`)
  - `current_fencing_token` (Authoritative, integer)
  - `active_lease_worker` (Authoritative, nullable string)
  - `lease_deadline` (Authoritative, nullable ISO8601 UTC)
  - `retry_count` (Authoritative, integer)

---

### Layer 8: Model and Tool Execution Adapters
- **Responsibilities**: Untrusted execution sandbox. Receive task assignments, invoke models or deterministic fixtures within strict capability boundaries, apply file mutations through scope guards, and collect raw output streams.
- **Inputs**: Task Assignment, `CapabilityToken`, Input Artifact Hashes.
- **Outputs**: `WorkerSubmission` (Output Artifacts, Execution Logs, Exit Codes).
- **Authority**: None. Untrusted worker. All mutations are intercepted by the local scope guard.
- **Failure Behavior**: Any attempt to write outside `authorized_paths` terminates the worker execution immediately with `SCOPE_VIOLATION`.
- **Contract Fields**:
  - `submission_id` (Authoritative, UUIDv4)
  - `assignment_id` (Authoritative, UUIDv4)
  - `fencing_token` (Authoritative, integer)
  - `produced_artifact_hashes` (Authoritative, list of SHA-256 strings)
  - `execution_log_hash` (Authoritative, SHA-256 string)
  - `exit_code` (Authoritative, integer)

---

### Layer 9: Immutable Artifacts and Evidence
- **Responsibilities**: Content-addressed storage (SHA-256) of all patches, source trees, test outputs, review notes, and execution logs. Ensure strict provenance linking artifact -> producing worker -> capability token -> parent artifacts.
- **Inputs**: Raw file bytes, metadata envelopes.
- **Outputs**: `ArtifactRecord`, SHA-256 Content Digest.
- **Authority**: Storage and cryptographic digest calculation. Immutable once written.
- **Failure Behavior**: Any hash mismatch or detected payload tampering raises `ARTIFACT_INTEGRITY_VIOLATION`.
- **Contract Fields**:
  - `artifact_hash` (Authoritative, SHA-256 hex string)
  - `artifact_type` (Authoritative: "patch", "test_report", "review", "log", "reproduction_script")
  - `work_order_id` (Authoritative, UUIDv4)
  - `work_order_version` (Authoritative, integer)
  - `producing_worker_id` (Authoritative, string)
  - `capability_token_id` (Authoritative, UUIDv4)
  - `parent_artifact_hashes` (Authoritative, list of SHA-256 hex strings)
  - `created_at` (Authoritative, ISO8601 UTC)

---

### Layer 10: Independent Validation and Acceptance
- **Responsibilities**: Execute independent verification checks in an isolated environment using pre-registered test suites, linters, and acceptance criteria. Neither the worker nor the router may alter the validator.
- **Inputs**: Candidate Artifact (e.g. Patch), Registered Acceptance Criteria, Baseline Repository.
- **Outputs**: `ValidationVerdict` (`ACCEPTED` | `REJECTED`, Detailed Diagnostic Evidence).
- **Authority**: Sole entity authorized to certify an artifact as accepted engineering work.
- **Failure Behavior**: Any check failure results in `REJECTED`. Preserves comprehensive logs for the repair controller.
- **Contract Fields**:
  - `verdict_id` (Authoritative, UUIDv4)
  - `validator_id` (Authoritative, string)
  - `artifact_hash` (Authoritative, SHA-256 hex string)
  - `status` (Authoritative: `ACCEPTED` | `REJECTED`)
  - `checks_evaluated` (Authoritative, list of check records with pass/fail)
  - `diagnostic_evidence_hash` (Authoritative, SHA-256 hex string)

---

### Layer 11: Evaluation, Bounded Repair, and Controlled Improvement
- **Responsibilities**: When an artifact is rejected, classify the failure mode (assertion failure, compilation error, scope violation, timeout), extract minimal diagnostic context, decrement the retry budget, and synthesize a bounded repair work order.
- **Inputs**: `ValidationVerdict`, Failed Artifact, Work Order Budget State.
- **Outputs**: Bounded Repair Task or Terminal Failure.
- **Authority**: Can request repair tasks within remaining budget; cannot unilaterally declare an artifact accepted or expand capability scope.
- **Failure Behavior**: When budget is exhausted, transitions work order to `FAILED_BUDGET_EXHAUSTED`.
- **Contract Fields**:
  - `failure_classification` (Authoritative: `ASSERTION_ERROR`, `TEST_COLLECTION_ERROR`, `ENVIRONMENT_ERROR`, `SCOPE_VIOLATION`, `MALFORMED_OUTPUT`, `TIMEOUT`)
  - `remaining_budget` (Authoritative, integer)
  - `repair_diff_hash` (Authoritative, SHA-256 hex string)
  - `admissible_for_repair` (Authoritative, boolean)

---

## 3. Minimum Viable Deployment Boundaries

| Logical Layer | Phase 0 Prototype Deployment | Target Production Deployment | Justification |
| :--- | :--- | :--- | :--- |
| **1. Human Interface** | In-process Python CLI / detached runner | CLI / Web UI / Harness service | Validates detached lifecycle without network complexity. |
| **2. Intent Compiler** | In-process rule & schema compiler | Microservice or dedicated agent container | Deterministic schema validation requires no remote process. |
| **3. Authority & Admission** | Control Plane In-Memory / SQLite Gate | Hardware-backed or KMS-signed Token Gate | Fails closed locally; avoids remote cryptographic service overhead in Phase 0. |
| **4. Planning & Decomposition** | In-process DAG generator | Orchestration Planner | Preserves clear input/output contracts. |
| **5. Capability Registry** | SQLite-backed empirical catalog | Distributed CMDB / registry | Provides full empirical profile schema and querying. |
| **6. Router** | In-process capability matching module | Distributed scheduler router | Evaluates affinity and worker independence deterministically. |
| **7. Workflow Engine** | Transactional SQLite state machine with WAL | SQLite or dedicated transactional PostgreSQL | Guarantees ACID state transitions, monotonic fencing, and recovery. |
| **8. Execution Adapters** | Local simulated adapters with scope guards | Isolated Linux cgroups / container workers | Scope guards enforce file boundaries; simulated workers test contracts. |
| **9. Artifact Store** | Content-addressed local filesystem store | Content-addressed blob store (S3/CAS) | Cryptographic SHA-256 immutability is identical regardless of storage backend. |
| **10. Independent Validator** | Isolated sub-process harness | Ephemeral sandbox runner | Ensures untrusted worker cannot manipulate acceptance checks. |
| **11. Repair Controller** | In-process failure classifier & re-planner | Automated repair controller | Full failure classification and bounded iteration logic. |

---
