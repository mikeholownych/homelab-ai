# Phase 2 Canonical Architecture Contracts: Multi-Worker Handoffs and DAG Scheduling

## 1. Bounded Assignment DAG Contract

Each step in an engineering workflow plan represents a typed node in a directed acyclic graph.
Downstream nodes are dispatch-blocked until all parent dependency nodes reach terminal `COMPLETED` state in the durable workflow engine.

```python
class TaskRole(StrEnum):
    INVESTIGATION = "investigation"
    TEST_DEVELOPMENT = "test_development"
    IMPLEMENTATION = "implementation"
    INDEPENDENT_REVIEW = "independent_review"
    BOUNDED_REPAIR = "bounded_repair"
    INDEPENDENT_VALIDATION = "independent_validation"
```

### Assignment State Machine
```text
  [PENDING]
     | (all dependencies COMPLETED && authority verified)
     v
  [READY]
     | (acquire_lease with monotonic fencing_token)
     v
  [LEASED]
     |---> (complete_assignment with CAS output_artifact) ---> [COMPLETED]
     |---> (lease timeout / SIGKILL) ------------------------> [EXPIRED / READY]
     |---> (ScopeViolationError / security abort) -----------> [FAILED_SECURITY]
     |---> (budget exhausted / unrecoverable defect) ---------> [FAILED]
```

---

## 2. Artifact-Centered Handoff Contracts

Handoffs between workers must never rely on unstructured conversational chat or self-authored narrative summaries. Every handoff is mediated by an immutable artifact in the CAS `ArtifactStore`.

### 2.1 Implementer Handoff Contract
**Inputs**:
- Canonical `WorkOrder` (immutable contract hash).
- `baseline_commit`: Git commit SHA or tree digest.
- `authorized_mutation_paths`: Whitelist of allowable paths.
- `input_artifacts`: Prior reproduction scripts, test suites, or investigation findings.
**Output**:
- `ArtifactType.PATCH`: Unified diff modifying only authorized paths.

### 2.2 Reviewer Handoff Contract
**Inputs**:
- `candidate_patch_artifact_hash`: Exact CAS digest of author's patch.
- `target_repo_context`: Read-only snapshot of baseline repository.
- `acceptance_criteria`: Pre-registered requirements from the WorkOrder.
**Output**:
- `ArtifactType.REVIEW_REPORT`:
  - `target_artifact_hash`: Hash of patch reviewed.
  - `disposition`: `RECOMMEND_ACCEPT` | `RECOMMEND_REVISE` | `BLOCK`
  - `findings`: List of `ReviewFindingRecord` entries with concrete line numbers and descriptions.
  - `advisory_flag`: Findings are advisory until verified by tests or independent validator.

### 2.3 Repair Worker Handoff Contract
**Inputs**:
- `failed_artifact_hash`: Exact CAS digest of candidate patch that failed.
- `validation_verdict_hash`: CAS digest of validator's failure log.
- `reviewer_findings_hash`: Optional CAS digest of review report.
- `remaining_retries`: Monotonically decremented retry counter from work order budget.
- `authorized_mutation_paths`: Same bounded scope.
**Output**:
- `ArtifactType.PATCH`: Repaired unified diff artifact.

---

## 3. Empirical Worker Capability Profile Contract

Replaces synthetic fixture assumptions with empirical deployed measurements bound to the complete hardware and runtime stack:

```python
@dataclass(frozen=True)
class DeployedStackIdentity:
    device_type: str        # e.g., "intel_arc_pro_b65"
    pci_slot: str           # e.g., "0000:03:00.0"
    vram_bytes: int         # e.g., 34359738368
    driver_version: str     # e.g., "xe-24.1"
    runtime_engine: str     # e.g., "vllm_xpu"
    model_name: str         # e.g., "engineering/b0"
    quantization: str       # e.g., "int4"
    context_window: int     # e.g., 16384
    chat_template: str      # e.g., "qwen2"
    tool_parser: str        # e.g., "hermes"

@dataclass(frozen=True)
class EmpiricalCapabilityRecord:
    role: TaskRole
    measured_pass_rate: float
    evaluated_sample_size: int
    last_evaluated: str
    evidence_source: EvidenceSource  # EMPIRICAL_DEPLOYED_MEASUREMENT
    evidence_artifact_hash: str
```
