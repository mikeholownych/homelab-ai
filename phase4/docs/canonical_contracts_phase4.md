# Phase 4 Canonical Architecture Contracts and Interfaces

---

## 1. Candidate Model Configuration Schema

Every evaluated model configuration is uniquely identified by an immutable configuration record with cryptographic content addressing.

```python
@dataclass(frozen=True)
class CandidateManifest:
    candidate_id: str             # e.g., "cand-deepseek-lite-fp8"
    model_repository: str         # e.g., "deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct"
    model_revision: str           # Git commit SHA of the weights
    architecture_type: str        # "dense" or "moe"
    parameter_count_total: float  # e.g., 16.0 (billion)
    parameter_count_active: float # e.g., 2.4 (billion)
    quantization_format: str      # "awq-4bit", "fp8", "bf16"
    serving_runtime: str          # "vllm-xpu" or "ipex-llm"
    topology: str                 # "tp1_single_card" or "tp2_dual_card"
    context_window_limit: int     # e.g., 16384
    tool_call_parser: str         # e.g., "qwen3_coder", "hermes", "deepseek"
    vram_budget_gb: float         # Max allowed resident VRAM per GPU (31.89 GB max)
    host_ram_reserve_gb: float    # Min required host RAM reserve (8.0 GB min)
    is_control_baseline: bool = False
```

---

## 2. Model Roles and Specialist Capabilities

The system defines three distinct, specialized execution roles:

1. **Author (`Role.AUTHOR`)**:
   - Authorized to explore the target repository using `read_file` and `list_dir`.
   - Authorized to propose code modifications via `replace_file_content` and `write_file` strictly within the Work Order's allowed path scope.
   - May execute local unit tests via `run_tests` to verify progress.
   - Must output a structured completion handoff containing the list of modified artifacts.

2. **Reviewer (`Role.REVIEWER`)**:
   - Authorized to inspect git diffs, modified files, and requirements.
   - Strictly read-only authority (no write or execute permissions).
   - Generates structured `ReviewFinding` records containing:
     - `file_path`: Exact modified file.
     - `line_number`: Specific line or range.
     - `severity`: `ERROR`, `WARNING`, `SUGGESTION`.
     - `defect_category`: `LOGIC_BUG`, `EDGE_CASE`, `STYLE`, `SCOPE_VIOLATION`.
     - `description`: Actionable defect explanation.
     - `is_defect`: Boolean flag indicating if this is an actual blocking defect.

3. **Repairer (`Role.REPAIRER`)**:
   - Dispatched only when reviewer flags blocking defects (`severity=ERROR`).
   - Receives original work order + review findings + modified artifacts.
   - Bound to repairing reported defects without modifying unrelated files.
   - Maximum 2 repair rounds before supervisor declares escalation or terminal outcome.

---

## 3. Cooperative Handoff Protocol

Communication between workers occurs strictly through content-addressed artifacts in the `ArtifactStore`. Direct conversational ping-pong between models is prohibited:

```
[WorkOrder]
     │
     ▼
[Worker 1: Author] ──(Generates Diff/Code)──► [ArtifactStore: HASH_A]
                                                     │
     ┌───────────────────────────────────────────────┘
     ▼
[Worker 2: Reviewer] ──(Inspects Diff)──► [ArtifactStore: HASH_REVIEW]
                                                     │
     ┌───────────────────────────────────────────────┘
     ▼ (If defects flagged)
[Worker 1/3: Repairer] ──(Generates Fix)──► [ArtifactStore: HASH_REPAIR]
                                                     │
     ┌───────────────────────────────────────────────┘
     ▼
[IndependentValidator] ──(Executes Sandbox Tests)──► [Verdict: ACCEPTED / REJECTED]
```

---

## 4. Evaluation and Telemetry Contracts

During candidate qualification, the execution harness captures:

```python
@dataclass(frozen=True)
class TaskEvaluationRecord:
    task_id: str
    task_class: str
    candidate_id: str
    role_assignment: str       # "author", "reviewer", "repairer", or "single"
    started_at: str
    completed_at: str
    duration_seconds: float
    tool_calls_total: int
    malformed_tool_calls: int
    scope_violations: int
    review_findings_count: int
    true_defects_found: int
    false_positives_count: int
    repair_attempts: int
    final_verdict: str         # "ACCEPTED" or "REJECTED"
    first_pass_accepted: bool
    vram_allocated_gb: float
    host_ram_available_gb: float
    output_artifact_hashes: list[str]
```
