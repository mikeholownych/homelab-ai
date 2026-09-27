# Autonomous Engineering System: Phase 9 Engineering Plan
## Adaptive Specialized Agent Orchestration

**Status**: FROZEN / PREREGISTERED  
**Date**: 2026-09-27  
**Author**: Principal Engineering Agent  
**Branch**: `phase9-adaptive-orchestration`  
**Base Commit**: `3970753bad019db22854c9deb24c66c177eff9dc`  
**Worktree**: `/home/mike/Projects/aihost/.worktrees/phase9-adaptive-orchestration`

---

## 1. Current Orchestrator Architecture and Module Dependency Map

The Phase 8 control plane established multi-repository governance, admission filtering, DAG task dependencies, independent validation, and human-authorized pull request delivery:

```
[Phase 8 Control Plane Architecture]
┌────────────────────────────────────────────────────────────────────────┐
│                        Human Work Order / CLI                          │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│  RepositoryOnboardingManager ───► WorkOrderAdmissionManager            │
│  (Policy, Protected Paths)       (Scope, Baseline Pinning, Expiration) │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      MultiRepoEngineeringService                       │
│  ┌───────────────────────────────┐  ┌────────────────────────────────┐ │
│  │     TaskDependencyManager     │  │   MultiRepoConcurrencyManager  │ │
│  │ (Tarjan Cycle Detection,      │  │ (Per-Repo Limits, Namespaced   │ │
│  │  Cascading Failure Containment│  │  Path Locks)                   │ │
│  └───────────────────────────────┘  └────────────────────────────────┘ │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                        HardenedRealRepoPipeline                        │
│   Investigation ──► Planning ──► Implementation ──► Review ──► Repair  │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      IndependentAcceptanceManager                      │
│   (AST Syntax, Static Security Prohibitions, Isolated Test Runner)     │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                       PullRequestDeliveryManager                       │
│   (Staged Lifecycle, Explicit Human Delivery Auth Gate, No Auto-Merge) │
└────────────────────────────────────────────────────────────────────────┘
```

### Module Dependencies in Phase 8
- `autonomous_engineering.repository.onboarding` defines `RepositoryContract` and `RepositoryOnboardingManager`.
- `autonomous_engineering.authority.admission` enforces authority tokens and work-order scope validation.
- `autonomous_engineering.service.multi_repo_service` orchestrates concurrent DAG execution across repositories.
- `autonomous_engineering.validator.acceptance` enforces tamper-proof AST, security, and sandboxed test validation.
- `autonomous_engineering.delivery.pr_manager` gates branch publication behind human authorization.

### Extension Points for Phase 9
Phase 9 does not duplicate or bypass these controls. Instead, it injects an **Adaptive Specialized Agent Orchestration Layer** between task admission and pipeline execution:
1. When a task is dequeued by `MultiRepoEngineeringService`, its workload requirements are determined by `WorkloadRequirementsClassifier`.
2. The orchestrator queries `VersionedAgentProfileRegistry` to match qualified profiles for the required specialized roles (Investigator, Architect, Engineer, Reviewer, etc.).
3. `ModelCapabilityRegistry` evaluates physical and calibrated model configurations against the required profile capabilities.
4. `CapabilityAwareModelScheduler` optimizes model and worker selection subject to hard constraints (context, tools, memory, worker health).
5. `ReasoningBudgetManager` allocates bounded token, depth, and escalation budgets.
6. `InterAgentHandoffManager` binds immutable evidence packages between sequential stages.
7. `ContextConstructionManager` isolates context assembly, tracking provenance and preventing injection.

---

## 2. Existing Authority and Validation Boundaries

The existing authority and validation boundaries established in Phases 0–8 remain inviolate:

1. **Human Work-Order Authority**: Work orders originate from human-authorized specifications. No agent profile or model output may expand its declared `authorized_mutation_paths` or add undeclared capabilities.
2. **Point-of-Use Scope Guard**: Diff mutations outside authorized paths trigger immediate rejection with `REJECTED_SCOPE_VIOLATION`.
3. **Immutable Baseline Pinning**: Tasks bind an immutable baseline commit hash. TOCTOU checks abort if the target repository changes externally before export.
4. **Independent Acceptance Supremacy**: Acceptance criteria are immutable and stored in CAS. The model cannot alter test files or accept its own work.
5. **Human Delivery Gate**: Branch creation and PR publication require an explicit `DeliveryAuthorizationRecord`.
6. **Hard Autonomous Merge Prohibition**: Calling `attempt_merge()` raises `ProtectedMergeProhibitedError`. Autonomous merging into production is strictly prohibited by code contract.

---

## 3. Agent Profile Registry Design (Workstream A)

### 3.1 Immutable Agent Profile Contract
An agent profile is a declarative execution contract defining exact capabilities, toolsets, constraints, and schemas:

```python
class AgentProfile:
    profile_id: str                      # e.g., "implementation-engineer"
    semantic_version: str                # e.g., "1.0.0"
    content_digest: str                  # SHA-256 of canonical JSON serialization
    specialization: str                  # Domain role description
    supported_workload_classes: list[str]# ["defect_repair", "multi_file", "refactor"]
    required_model_capabilities: list[str]# ["code_generation", "tool_calling", "structured_output"]
    permitted_tool_capabilities: list[str]# ["read_file", "write_file", "run_sandbox_command"]
    prohibited_operations: list[str]     # ["git_push", "modify_ci", "network_outbound"]
    context_requirements: dict[str, Any] # {"min_context_window": 16384, "syntax_tree": True}
    input_schema_version: str            # Schema version for incoming handoffs
    output_schema_version: str           # Schema version for outgoing handoffs
    max_reasoning_budget: int            # Ceiling on reasoning tokens
    max_execution_steps: int             # Ceiling on tool turns
    max_repair_attempts: int             # Bound on retry loops
    evidence_requirements: list[str]     # ["ast_clean", "diff_patch", "execution_trace"]
    validation_requirements: list[str]   # ["unit_tests", "lint_pass"]
    permitted_terminal_dispositions: list[str] # ["ACCEPTED", "REPAIRABLE", "REJECTED"]
```

### 3.2 Effective Permission Resolution
Effective permissions are computed strictly as the intersection:
$$\text{Effective Permissions} = \text{Profile Capabilities} \cap \text{Work Order Authority} \cap \text{Execution Environment}$$

A profile declaring write access cannot write to a repository path that is not in the work order's `authorized_mutation_paths`.

### 3.3 Initial Qualified Profiles
1. **Repository Investigator** (`repo-investigator` v1.0.0): Read-only AST, symbols, call graphs, context harvesting.
2. **Systems Architect** (`systems-architect` v1.0.0): Dependency analysis, interface decomposition, planning.
3. **Implementation Engineer** (`implementation-engineer` v1.0.0): Code mutation within authorized paths, bounded repair.
4. **Test Engineer** (`test-engineer` v1.0.0): Test development, fixture generation, regression assertion authoring.
5. **Security Reviewer** (`security-reviewer` v1.0.0): Taint analysis, forbidden AST node detection, credential leak scanning.
6. **Performance Analyst** (`performance-analyst` v1.0.0): Algorithmic complexity analysis, latency/memory footprint audit.
7. **Integration Reviewer** (`integration-reviewer` v1.0.0): Interface concordance, API compatibility verification.
8. **Incident Investigator** (`incident-investigator` v1.0.0): Failure root-cause analysis, crash log triage.

---

## 4. Workload Classification Contract (Workstream B)

### 4.1 WorkloadRequirements Contract
```python
class WorkloadRequirements:
    workload_id: str
    task_class: str                      # "defect_repair", "multi_file", "security_analysis", etc.
    required_specializations: list[str]  # Ordered required profile identities
    reasoning_complexity: str            # "LOW", "MEDIUM", "HIGH", "CRITICAL"
    context_demand_tokens: int           # Estimated minimum context window
    required_tools: list[str]            # Tools necessary to execute task
    expected_execution_cost: float       # Normalized expected cost units
    failure_consequence: str             # "LOW", "MEDIUM", "HIGH", "IRREVERSIBLE"
    mandatory_validation_suites: list[str]# ["syntax_ast", "security_ast", "sandbox_tests"]
    uncertainty_level: str               # "LOW", "MEDIUM", "HIGH"
    resource_constraints: dict[str, Any] # Timeout, memory cap, GPU affinity
    classification_evidence: dict[str, Any] # Extracted facts supporting classification
```

### 4.2 Decoupling Difficulty from Consequence
Computational difficulty (reasoning complexity) and failure consequence are tracked independently. A single-line change to an authentication guard has `LOW` computational difficulty but `HIGH` failure consequence, triggering mandatory security review profiles regardless of model confidence.

---

## 5. Model Capability and Qualification Registry (Workstream C)

### 5.1 Authoritative Qualification Key
$$\text{Qualification Key} = \text{Profile Digest} \times \text{Model Revision} \times \text{Inference Config} \times \text{Workload Class} \times \text{Suite Version}$$

### 5.2 Model Capability Record
Tracks:
- Physical model identifier (e.g. `engineering/b0` / `Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`).
- Backend (vLLM XPU TP=1) and revision.
- Maximum addressable context (65,536 tokens).
- Structured output and tool-calling support.
- Measured throughput (tokens/sec) and TTFT (time-to-first-token).
- Memory footprint (24.5 GiB VRAM per worker).
- Qualification status: `QUALIFIED`, `EXPERIMENTAL`, `DISQUALIFIED`, `REVOKED`.

---

## 6. Logical and Physical Scheduling Design (Workstream D & E)

### 6.1 Two-Stage Scheduling Pipeline
1. **Hard Constraint Filtering**: Eliminates candidates failing work-order authorization, missing tool compatibility, insufficient context window, memory overflow, or unqualified status.
2. **Cost Optimization Objective Function**:
$$C_{\text{expected}} = T_{\text{infer}} \cdot w_{\text{lat}} + T_{\text{queue}} \cdot w_{\text{wait}} + C_{\text{reload}} + C_{\text{context}} + P_{\text{repair}} \cdot C_{\text{repair}} + C_{\text{val}}$$

Where:
- $T_{\text{infer}}$ is estimated generation latency.
- $T_{\text{queue}}$ is current worker queue delay.
- $C_{\text{reload}}$ is model swap cost (0 for currently resident models, $\infty$ if unauthorized).
- $P_{\text{repair}}$ is historical repair probability for this profile/model on this workload class.
- $C_{\text{val}}$ is independent validation cost.

### 6.2 Physical Resource Management
- GPU 0 (`vllm-xpu-tp1-worker1`): Port 8000.
- GPU 1 (`vllm-xpu-tp1-worker2`): Port 8001.
- Both workers reside behind `orchestrator_gateway` (PID 742882 on port 8010 forwarded to 18010).
- Model swapping on the physical host is **prohibited** without explicit host authority; resident model `engineering/b0` is used for all physical inference operations. Alternative configurations are evaluated using calibrated fixtures without disrupting host state.

---

## 7. Adaptive Reasoning Budget and Escalation (Workstream F)

### 7.1 Reasoning Allocation Levels
- `TIER_1_STANDARD`: Nominal token budget (1,024 max tokens), 1 repair attempt, standard context retrieval.
- `TIER_2_DEEP`: Expanded token budget (2,048 tokens), 2 repair attempts, AST symbol call-graph expansion.
- `TIER_3_SPECIALIST`: Maximum token budget, dual independent reviewer dispatch, targeted AST repair.

### 7.2 Bounded Escalation Protocol
Escalation occurs only when concrete failure evidence is observed:
1. `SCHEMA_VIOLATION`: Re-prompt with strict schema validation template (max 1 escalation).
2. `LINT_OR_SYNTAX_ERROR`: Dispatch AST repair sub-task with exact traceback.
3. `VALIDATION_TEST_FAILURE`: Escalate reasoning budget to `TIER_2` with test failure assertion output.
4. `TIMEOUT_OR_EXHAUSTION`: Fail closed; mark task `UNRESOLVABLE_EXHAUSTED` and notify operator.

**Hard Rule**: Escalation depth is capped at 2. Escalation can never expand file mutation scope or bypass validators.

---

## 8. Typed Inter-Agent Cooperation (Workstream G)

### 8.1 Typed Handoff Package
Data passed between agents is an immutable, content-addressed `EvidencePackage`:
```python
class EvidencePackage:
    package_id: str
    producer_instance_id: str
    consumer_profile_id: str
    work_order_id: str
    baseline_commit: str
    payload_type: str                   # "INVESTIGATION_REPORT", "PLAN", "CODE_DIFF", "REVIEW_VERDICT"
    payload_content: dict[str, Any]
    payload_digest: str                 # SHA-256 of payload_content
    schema_version: str
    permitted_downstream_use: list[str] # ["PLANNING", "IMPLEMENTATION", "VALIDATION"]
    created_at_utc: str
```

### 8.2 Invariant Guarantees
- Reviewers cannot alter implementation code.
- Implementers cannot modify or hide review verdicts.
- Planners cannot grant file mutation permissions.
- Recursive delegation chains are strictly prohibited; handoff sequences are controlled strictly by `MultiRepoEngineeringService`.

---

## 9. Context Provenance and Isolation Controls (Workstream H)

### 9.1 Context Assembly Contract
- Every context segment is tracked in a `ContextProvenanceRecord`:
  - Source URI and file hash.
  - Extraction mechanism (`EXACT_FILE`, `AST_SYMBOL`, `GIT_LOG`).
  - Byte offset and line range.
  - Sanitization status (stripped of prompt injection markers).
- Stale context detection: if the underlying repository HEAD changes, context caches are invalidated.
- Cross-task isolation: context from Task A is prohibited from leaking into Task B across work orders.

---

## 10. Persistent-State and Migration Requirements

- State is persisted to SQLite with Write-Ahead Logging (WAL).
- Schema versioning: database tables for profiles, model capabilities, qualification keys, and scheduling decisions are created with forward-compatible migrations.
- Crash recovery: in-flight scheduling transactions recover cleanly upon restart without double-dispatch.

---

## 11. Resource Budgets and Protected-Service Constraints

- **Protected PIDs**: 986 (Hermes Gateway), 3130937 (OpenCode Runner), 2093382 (SSH Tunnel) must be monitored and undisturbed.
- **Port Isolation**: Phase 9 test instances use ephemeral ports or local memory transports. Never bind 18010, 8010, 8000, 8001.
- **Memory Footprint**: Transient test processes capped at 1 GiB host RAM.

---

## 12. Independent Evaluation Methodology (Workstream I)

### 12.1 Evaluation Cohort
A frozen cohort of 6 unseen engineering tasks covering:
1. `phase9-eval-repo-investigation`: Static repository structure & dependency graph analysis.
2. `phase9-eval-defect-repair`: Off-by-one bug repair in data processor.
3. `phase9-eval-multifile-feature`: Cross-module API refactor with typed interface handoffs.
4. `phase9-eval-security-analysis`: Injection vulnerability detection and remediation.
5. `phase9-eval-test-development`: Authoring unit test suite for untested utility.
6. `phase9-eval-adversarial-scope`: Out-of-bounds mutation attempt requiring immediate rejection.

### 12.2 Comparative Metrics
Phase 9 Adaptive Orchestration will be directly compared against the frozen Phase 8 Baseline across:
- **Independent Acceptance Rate** ($\ge 80\%$).
- **Adversarial Interception Rate** ($100\%$).
- **End-to-End Completion Time** (reduction due to specialization & caching).
- **Token Efficiency** (reduction in wasted generation via specialized context).
- **Repair Frequency** (first-pass acceptance rate).

---

## 13. Rollback and Recovery Procedures

- If any Phase 9 component causes an unexpected regression:
  1. The worktree is isolated; baseline `phase8-operational-delivery` remains intact at `3970753`.
  2. Any transient test databases in `/tmp/phase9_*.sqlite` can be safely deleted.
  3. Physical model processes on `10.0.8.5` remain untouched and unaffected.

---

## 14. Preregistered Qualification Gates (G1–G14)

| Gate | Title | Acceptance Requirement |
|---|---|---|
| **G1** | Baseline & Evidence Reconciliation | Phase 8 baseline verified (194 tests pass, checksums match, remote PR limits documented). |
| **G2** | Immutable Agent Profile Registry | Declarative profiles publish with SHA-256 digest; permissions enforce 3-way intersection. |
| **G3** | Evidence-Based Workload Classification | Decouples reasoning complexity from failure consequence; valid structured requirements. |
| **G4** | Model Capability & Qualification Registry | 5-tuple qualification key enforced; unqualified models cannot be selected. |
| **G5** | Capability-Aware Model Scheduling | Hard constraints evaluated first; cost function optimizes expected end-to-end outcome. |
| **G6** | Physical Inference Resource Management | Dual-TP=1 topology preserved; memory limits enforced; no unauthorized model swaps. |
| **G7** | Bounded Adaptive Reasoning Allocation | Escalation triggered only by concrete evidence; maximum depth capped at 2; authority preserved. |
| **G8** | Typed Inter-Agent Cooperation | Immutable evidence packages; review cannot modify code; no recursive delegation. |
| **G9** | Context Provenance & Isolation | Context tracked to file hash; prompt injection sanitized; zero cross-task data leakage. |
| **G10**| Comparative Engineering Evaluation | Unseen evaluation cohort completed; metrics demonstrate equal or superior outcome vs baseline. |
| **G11**| Adversarial Security Qualification | 16+ adversarial attack vectors evaluated and 100% intercepted. |
| **G12**| Cumulative Multi-Phase Regression | All 194 baseline tests + all new Phase 9 tests pass 100%. |
| **G13**| Protected Campaign Non-Interference | PIDs 986, 3130937, 2093382 active, healthy, and undisturbed throughout execution. |
| **G14**| Physical Inference End-to-End Execution | Real physical model `engineering/b0` executes live adaptive engineering task successfully. |
