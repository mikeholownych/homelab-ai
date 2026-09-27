# Phase 4 Preregistration and Acceptance Criteria Specification

---

## 1. Experimental Objective and Guiding Principles

Phase 4 evaluates and qualifies model configurations on two physical Intel Arc Pro B65 GPUs (`worker-b65-0`, `worker-b65-1`), using the Phase 3 operational work-order service as the immutable control and harness.

### Guiding Principles:
1. **Engineering Outcomes Over Speed**: The primary objective is correct, complete, and maintainable engineering deliverables independently accepted by `IndependentValidator`. Latency, throughput, and parameter efficiency are secondary constraints.
2. **Fixed Authority Boundary**: Models are untrusted workers. The control plane owns authority, workflow DAGs, fences, and factual completion reporting. Models cannot declare their own work accepted or expand authorized scopes.
3. **No Inference from Reputation**: Suitability is determined strictly by measured empirical performance on local hardware, never by model cards, active MoE parameter counts, or generic leaderboards.
4. **Strict Isolation**: The running T5820 autonomous-readiness campaign (Gateway PID 986, OpenCode PID 3130937, Tunnel PID 2093382) must not be contended with or disrupted.

---

## 2. Candidate Eligibility and Exclusion Criteria

To be admitted for qualification, a candidate must satisfy all prerequisite criteria:

| Criterion | Requirement | Failure Action |
| :--- | :--- | :--- |
| **Interface Compatibility** | OpenAI-compatible HTTP endpoint supporting chat completions and structured tool calling (`tools`, `tool_choice`). | Immediate Disqualification |
| **Tool Call Fidelity ($T_F$)** | Zero malformed JSON tool calls; strict adherence to `read_file`, `write_file`, `replace_content`, `list_directory`, `run_tests` schemas. | Immediate Disqualification |
| **Context Window** | Support $\ge 16,384$ tokens with linear or RoPE-scaled attention without OOM. | Immediate Disqualification |
| **Memory Residency** | Total resident model weights + KV cache must fit within 31.89 GiB physical VRAM per B65 (or TP=2 across 63.78 GiB total), maintaining $\ge 8.0$ GiB host RAM reserve. | Disqualification / Rejection |
| **Intel XPU Support** | Validated execution under Intel Linux Xe KMD (`xe-24.1`) and Level Zero runtime (`libze-intel-gpu1`). | Disqualification |

---

## 3. Evaluation Cohort and Task Classes

Evaluation is conducted across four representative engineering task classes using both the frozen Phase 3 regression cohort (8 fixtures) and an extended held-out evaluation population (4 novel fixtures) to prevent task memorization / evaluation contamination:

### Task Classes:
1. **Defect Repair**: Localize bug from failing test, modify code without expanding scope, pass regression suite.
2. **Multi-File Implementation**: Coordinate changes across multiple interconnected modules (models, services, routes).
3. **Test Development**: Author rigorous regression tests for existing code with boundary and invariant checking.
4. **Maintainability / Refactoring**: Structural code improvements and decoupling preserving all existing behavior and public APIs.

### Cohort Partitioning:
- **Phase 3 Baseline Cohort (8 fixtures)**:
  - Defect Repair: `defect_repair_repo`, `defect_repair_series_repo`
  - Multi-File Implementation: `multi_file_repo`, `multi_file_tax_repo`
  - Test Development: `test_dev_repo`, `test_dev_auth_repo`
  - Maintainability: `maintainability_repo`, `maintainability_config_repo`
- **Extended Held-Out Evaluation Cohort (4 fixtures)**:
  - Held-out Defect: `heldout_defect_01_off_by_one_paging` (pagination fence-post bug)
  - Held-out Multi-File: `heldout_multifile_01_rate_limiter` (token-bucket rate limiting with storage backend)
  - Held-out Test Dev: `heldout_testdev_01_fencing_invariant` (fencing token sequence and replay verification)
  - Held-out Maintainability: `heldout_maintain_01_decouple_notifier` (decouple notification dispatch without breaking subscribers)

---

## 4. Experimental Designs: 3-Way Matched Comparison

Every candidate configuration that passes deployment qualification is evaluated in a 3-way matched comparison under identical budgets:

1. **Homogeneous Pair (Control Baseline)**:
   - Worker 1: Author (`cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`)
   - Worker 2: Reviewer (`cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`)
2. **Heterogeneous Pair (Specialist Collaboration)**:
   - Worker 1: Author (`cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` or qualified alternative)
   - Worker 2: Reviewer (Qualified specialist, e.g. `microsoft/phi-4` FP8 or `DeepSeek-Coder-V2-Lite` FP8)
3. **Single-Worker Control**:
   - Single worker performing authoring directly handed to `IndependentValidator` without peer review.

### Controlled Budgets (Matched Across All Conditions):
- Max tool interactions per stage: 10
- Max pre-validation repair attempts: 2
- Max total wall-clock time per task: 300 seconds
- Max output tokens per generation: 4,096 tokens
- Temperature: 0.0 (deterministic decoding)

---

## 5. Quantitative Acceptance Metrics & Stopping Gates

### 5.1 Primary Reliability Metrics
1. **Independent Task Acceptance Rate ($A_R$)**:
   $$A_R = \frac{N_{\text{accepted}}}{N_{\text{registered}}}$$
   Hard Gate: Candidate must achieve $A_R \ge 0.75$ on the qualification cohort.
2. **First-Pass Acceptance Rate ($F_R$)**:
   Fraction of accepted tasks that passed validation without triggering repair.
3. **Scope Guard Compliance ($S_C$)**:
   $$S_C = 1.0 \quad (\text{Zero unauthorized path modifications allowed})$$
   Hard Gate: Any scope violation results in immediate task rejection and candidate failure.
4. **Tool-Contract Fidelity ($T_F$)**:
   $$\text{Malformed Tool Calls} = 0$$
   Hard Gate: Zero unparseable tool invocations.
5. **Effective Pre-Validation Repair Rate ($R_E$)**:
   Percentage of review-flagged defects successfully resolved before validation.

### 5.2 Specialist Reviewer Qualification Metrics
- **Concrete Defect Detection Rate ($D_R$)**: Percentage of introduced synthetic/real defects correctly identified.
- **False Discovery Rate ($FDR$)**:
  $$FDR = \frac{\text{False Findings}}{\text{Total Findings}} \le 0.15$$
- **Actionable Linkage**: 100% of reported issues must include valid file paths and line ranges.

### 5.3 Stopping & Disqualification Rules
- If a candidate causes GPU out-of-memory or driver hang, qualification stops immediately.
- If a candidate generates malformed tool calls exceeding 10% of calls, qualification stops.
- If live deployment conflicts with the protected autonomous campaign, live candidate evaluation is stopped and reported as authority-blocked; qualification completes via verified offline execution harnesses.

---

## 6. Promotion and Rollback Protocol

1. **Role-Specific Promotion**:
   - A model may only be promoted to roles for which it has passed empirical qualification (e.g. `Reviewer` only, `Author` only, or `Full Engineer`).
2. **Staged Promotion Rule**:
   - Dual-worker replacement is prohibited in a single step. The control reviewer may be replaced with a heterogeneous specialist while retaining the control author.
3. **Rollback Criterion**:
   - Immediate automatic rollback to control configuration (`cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` at commit `eab3b9f`) if acceptance rate drops below baseline or if resource consumption violates memory reserves.

---

## 7. Training Data Preservation Invariants (Section 13)

- All execution traces (inputs, tool calls, model responses, reviewer findings, validator verdicts) must be captured with content-addressed SHA-256 hashes.
- Traces are strictly partitioned into `TRAINING_ELIGIBLE` and `HELD_OUT_EVALUATION` sets.
- No held-out benchmark traces may ever be admitted into training datasets.
- No model fine-tuning or self-distillation will occur during Phase 4.
