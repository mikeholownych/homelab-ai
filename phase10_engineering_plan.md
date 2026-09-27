# Autonomous Engineering System: Phase 10 Engineering Plan
## Repository-Scale Engineering Intelligence and Project Execution

**Status**: FROZEN / PREREGISTERED  
**Date**: 2026-09-27  
**Author**: Principal Engineering Agent  
**Branch**: `phase10-project-execution`  
**Base Commit**: `fe09e6cd6134cd461d63a12dff2909c42bfbca61`  
**Worktree**: `/home/mike/Projects/aihost/.worktrees/phase10-project-execution`

---

## 1. Current Architecture and Module Dependency Map

The Phase 9 control plane established adaptive specialized-agent orchestration, versioned profiles, multidimensional workload classification, 5-tuple model qualification, capability-aware scheduling, adaptive reasoning allocation, typed inter-agent handoffs, and context provenance.

Phase 10 elevates these capabilities to **repository-scale engineering intelligence and multi-stage project execution**:

```
[Phase 10 Repository-Scale Project Architecture]
┌────────────────────────────────────────────────────────────────────────┐
│                   Human Engineering Objective / CLI                    │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│               RepositoryKnowledgeManager (Workstream A)                │
│   Source-Grounded AST Graph ──► Symbol Inventory ──► Dependency Matrix │
│   (Observed Facts vs Inferred Relationships, Commit Invalidation)      │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│            Repository Investigator Extension (Workstream B)            │
│   Multi-Module Tracing ──► Impact Analysis ──► Architectural Boundaries│
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│             EngineeringProjectPlanner (Workstream C)                   │
│   Objective Decomposition ──► Bounded Work Orders ──► Dependency DAG   │
│   (Cycle Detection, Incompatible Scope Check, Self-Auth Prohibition)   │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│               ProjectContextManager (Workstream D)                     │
│   Durable Cross-Session WAL ──► Checkpoint Recovery ──► Isolation Guard│
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│               ProjectExecutionEngine (Workstream E)                    │
│   (Extends MultiRepoEngineeringService & TaskDependencyManager)        │
│   Capability Scheduler ──► Specialized Agents ──► Intermediate CAS     │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│              ProjectIntegrationManager (Workstream F)                  │
│   Isolated Integration Workspace ──► Conflict Detection ──► Tree Hash  │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│              ProjectAcceptanceManager (Workstream G)                   │
│   (Extends IndependentAcceptanceManager)                               │
│   Integrated Repository Build ──► Full Test Suite ──► Security Scan    │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│               PullRequestDeliveryManager (Human Barrier)               │
│   Content-Addressed Project Bundle ──► Delivery Auth ──► Remote Push   │
│   (Autonomous merge & production deployment strictly PROHIBITED)       │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Existing Authority and Validation Boundaries

The foundational authority boundaries established in Phases 0–9 remain inviolate:

1. **Human Objective Authority**: Engineering objectives originate exclusively from authorized human operators.
2. **No Authority Expansion Through Decomposition**: A project planner cannot expand the authority granted by the original objective. Sub-task mutation paths must strictly be subsets of authorized project paths:
   $$\bigcup_{i=1}^N \text{WorkOrderScope}_i \subseteq \text{AuthorizedProjectScope}$$
3. **Planning Self-Authorization Prohibition**: A planning agent cannot authorize its own plan. Plan execution requires admission and authority tokens issued by the authoritative control plane.
4. **Knowledge Summaries Are Untrusted Data**: Knowledge graph records and architectural summaries are treated as advisory context, not authoritative source code. Consequential engineering decisions must bind directly to exact source files and line ranges.
5. **Integrated Independent Acceptance Supremacy**: Project acceptance requires independent validation of the exact integrated repository tree. Passing individual work orders is necessary but never sufficient for project acceptance.
6. **Delivery Authorization & Merge Barrier**: Pull request creation requires explicit human signatures. Direct autonomous merging into default/production branches is strictly prohibited (`ProtectedMergeProhibitedError`).

---

## 3. Repository Knowledge Architecture (Workstream A)

### 3.1 Source-Grounded Knowledge Graph
The knowledge representation is strictly grounded in deterministic static analysis and AST parsing:
- **Repository Metadata**: Repository identity, baseline commit hash, file tree index.
- **Symbol Records**: Classes, functions, interfaces, methods, constants, docstrings, byte offsets, and line ranges.
- **Dependency Records**: Imports, intra-repository module relationships, external package dependencies.
- **Call Relationships**: Statically determinable caller/callee call-graph edges.
- **Configuration & Test Mappings**: Association between implementation modules and their corresponding unit/integration test suites.

### 3.2 Fact vs Inference Separation
To eliminate model hallucinations:
- `OBSERVED_SOURCE_FACT`: Extracted directly via deterministic AST parser (file exists, class defined, function exported, import declared).
- `INFERRED_ARCHITECTURAL_RELATION`: Inferred by model analysis (design pattern observed, intended interface decoupling, conceptual component boundary). Inferred relations are explicitly flagged with confidence ratings and supporting source citations.

---

## 4. Knowledge Provenance and Invalidation Rules

1. **Immutable Revision Binding**: Every knowledge record binds to an exact git commit hash.
2. **Incremental Invalidation**: When the repository HEAD changes:
   - Files with modified SHA-256 hashes have their symbol and dependency records invalidated immediately.
   - Downstream dependents (modules importing modified files) are marked `DIRTY_REQUIRES_REVALIDATION`.
3. **Stale Knowledge Prohibition**: Stale knowledge records are never served as current facts. If an agent queries a dirty or mismatched record, the knowledge manager refreshes the record from source before returning.
4. **Bounded Capacity**: Retention is capped at 50,000 symbols and 100,000 edges per repository to guarantee bounded host memory consumption (< 200 MB RAM).

---

## 5. Project Planning and Decomposition Contracts (Workstream C)

### 5.1 ProjectPlan Contract
```python
class EngineeringProjectPlan:
    project_id: str
    plan_version: int
    objective: str
    repository_id: str
    baseline_commit: str
    authorized_project_scope: list[str]
    work_orders: list[ProjectWorkOrder]
    dependency_edges: list[tuple[str, str]] # (upstream_wo_id, downstream_wo_id)
    plan_digest: str
    created_at_utc: str
```

### 5.2 ProjectWorkOrder Contract
```python
class ProjectWorkOrder:
    work_order_id: str
    title: str
    task_class: str
    target_files: list[str]
    authorized_mutation_paths: list[str]
    required_specialization: str
    prerequisite_task_ids: list[str]
    acceptance_criteria: list[str]
    resource_budget_tokens: int
    failure_policy: str # "ABORT_PROJECT", "ISOLATE_AND_CONTINUE", "RETRY"
```

### 5.3 Deterministic Graph Validation
Prior to execution dispatch:
- **Cycle Detection**: Evaluated using Tarjan's strongly connected components algorithm. Cyclic dependencies abort plan admission immediately.
- **Scope Non-Expansion Check**: Every work order's mutation paths must be verified as a strict subset of the project's authorized mutation paths.
- **Concurrency Collision Detection**: Tasks with overlapping mutation paths are automatically sequenced into a dependency order.

---

## 6. Durable Cross-Session Engineering Context (Workstream D)

### 6.1 State Persistence Contract
State is persisted in an ACID-compliant SQLite WAL database (`project_state.db`):
- Project metadata and plan revisions.
- Investigation findings and symbol references.
- Task execution history, leases, and fencing tokens.
- Content-addressed hashes of intermediate deliverables.
- Failure records and recovery checkpoints.

### 6.2 Session Resumption & Crash Invariance
When an execution session restarts after an interruption or crash:
1. `ProjectContextManager` recovers active leases and scans for abandoned tasks.
2. Monotonic fencing tokens increment, rejecting zombie commits from prior sessions.
3. The execution engine reconstructs context solely from verified durable records, discarding transient uncommitted state.
4. Cross-project data leakage is structurally impossible: queries are scoped strictly by `project_id`.

---

## 7. Cross-Task Integration Strategy (Workstream F)

### 7.1 Integration Pipeline
1. **Isolated Integration Workspace**: Cloned from the project's baseline commit into an ephemeral sandbox directory.
2. **Sequential Deliverable Application**:
   - Patches are applied in dependency-topological order: $P_1, P_2, \dots, P_N$.
   - Any patch application failure or merge conflict triggers `IntegrationConflictError`.
3. **Interface Concordance Verification**:
   - Validates that caller/callee signatures remain consistent across all integrated modules.
4. **Integrated Tree Hash**:
   - Computes canonical SHA-256 tree hash over the resulting workspace.
   - Any modification to intermediate deliverables invalidates the integrated tree hash.

---

## 8. Independent Project-Level Acceptance (Workstream G)

The project validator evaluates the **entire integrated repository state**, not individual task outputs:
1. **Build & Syntax Verification**: Full AST syntax pass across all modified and dependent files.
2. **Static Security Armor**: Comprehensive AST scan blocking prohibited modules (`subprocess`, `eval`, `exec`, `os.system`) and credentials.
3. **Comprehensive Test Suite**: Execution of all affected unit tests and project integration suites in an isolated sandbox.
4. **CAS Custody**: Stores the final `ProjectAcceptanceVerdict` in Content-Addressed Storage with cryptographic signature.

---

## 9. Failure Recovery and Change Management (Workstream H)

The system gracefully handles:
- **Worker Crashes**: Monotonic leases expire; task re-allocated with incremented fencing token.
- **Repository Baseline Drifts**: If target repository moves externally, integrated state is flagged dirty and re-validation is triggered.
- **Plan Revisions**: Modifying a plan invalidates downstream unexecuted tasks while preserving completed independent deliverables.
- **Cascading Failure Containment**: Upstream work order failures automatically abort dependent tasks (`CASCADING_ABORTED`) without executing them.

---

## 10. Resource Budgets and Concurrency Limits

- **Worker Limits**: Maximum 2 concurrent worker tasks per project, matching physical Dual-TP=1 B65 GPUs.
- **Memory Footprint**: Transient test processes and knowledge caches capped at 500 MB host RAM.
- **Protected Service Non-Interference**: Strict non-interference with PIDs 986, 3130937, 2093382, and serving ports 18010, 8010, 8000, 8001.

---

## 11. Independent Qualification Methodology (Workstream I)

### 11.1 Real-Repository Evaluation Cohort
A 3-stage, multi-module engineering project executed against the real `aihost` codebase:
- **Task 1 (Investigation & Planning)**: Multi-module static dependency investigation and plan synthesis.
- **Task 2 (Core Service Implementation)**: Refactoring and implementation in core service module (Upstream).
- **Task 3 (Interface Integration & Testing)**: Downstream consumer refactoring and test suite authoring (Downstream dependent).
- **Task 4 (Adversarial Scope Violation)**: Injected sub-task attempting to mutate unauthorized directory (`.github/`), verifying fail-closed containment.

---

## 12. Preregistered Qualification Gates (G1–G14)

| Gate | Title | Acceptance Requirement |
|---|---|---|
| **G1** | Baseline & Evidence Verification | Phase 9 baseline verified (253 tests pass, checksums match, protected services healthy). |
| **G2** | Versioned Repository Knowledge | Grounded knowledge graph extracted; fact vs inference separated; commit invalidation proven. |
| **G3** | Repository-Scale Investigation | Multi-module tracing and impact analysis produce source-grounded findings with exact citations. |
| **G4** | Project Planning & Decomposition | Plan decomposes into bounded work orders; cycle detection & scope non-expansion enforced. |
| **G5** | Durable Cross-Session Context | Resumption reconstructs verified state from SQLite WAL; cross-project leakage blocked. |
| **G6** | Dependency-Aware Project Execution | Multi-stage project executes according to DAG; worker scheduling & monotonic fencing verified. |
| **G7** | Cross-Task Integration | Assembles accepted patches in isolated workspace; detects conflicts and computes tree hash. |
| **G8** | Independent Project Acceptance | Evaluates integrated repository tree; AST syntax, static security, and tests pass 100%. |
| **G9** | Failure Recovery & Change Management | Worker crash and upstream failure recovery preserve consistency and reject stale authority. |
| **G10**| Real-Repository Project Qualification | Multi-stage project on real repository completes with 100% concordance with preregistration. |
| **G11**| Mandatory Adversarial Security | 16+ attack vectors evaluated and 100% intercepted. |
| **G12**| Cumulative Multi-Phase Regression | All 253 baseline tests + all new Phase 10 tests pass 100%. |
| **G13**| Protected Service Non-Interference | PIDs 986, 3130937, 2093382 active, healthy, and undisturbed throughout execution. |
| **G14**| Cryptographic Deliverable Custody | Final project bundle exported with CAS manifest, patch, metadata, and rollback guide. |
