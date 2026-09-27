# Phase 12 Engineering Plan: Physical Model Qualification and Heterogeneous Inference

## 1. Executive Mission & Operating Philosophy

The objective of Phase 12 is to execute a rigorous, empirical physical qualification campaign to determine whether alternative model configurations, quantizations, or heterogeneous multi-worker deployments improve real engineering outcomes on Dell Precision T5820 hardware.

This campaign optimizes for **independently accepted engineering outcomes per unit of time and resource consumption**, while strictly preserving authority boundaries, evidence custody, and protected host service integrity.

### Strict Governance Invariants:
1. **Zero Unload of Protected Control Without Authorization**:
   The resident protected model `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` (alias `engineering/b0`) on GPU 0 and GPU 1 must NEVER be evicted, reconfigured, or interrupted without explicit human authorization.
2. **Explicit Stop for Protected Model Swaps**:
   If physical evaluation of an alternative model requires replacing a resident worker, all non-disruptive preparation will be completed, a formal maintenance proposal prepared, and the swap operation stopped pending human authorization. Gates G7 and G8 will be recorded as **BLOCKED** rather than substituted with simulation.
3. **No Aggregate Memory Conflation**:
   The two 32,656 MiB Intel Arc Pro B65 GPUs are independent PCIe endpoints. Aggregate VRAM (65,312 MiB) will never be treated as a unified memory pool without explicit Tensor Parallelism ($TP=2$) modeling and PCIe latency accounting.
4. **Separate Token and Latency Accounting**:
   Prompt token reduction and completion latency must be reported as distinct trade-offs, never collapsed into an opaque composite metric.

---

## 2. Protected Control Identity & Hardware Baseline

- **Hardware Platform**: Dell Precision T5820 Workstation (`ai-5820-01`, `10.0.8.5`)
- **Accelerators**: 2x Intel Arc Pro B65 GPUs (PCI `0000:51:00.0`, `0000:93:00.0`)
- **Physical Memory**: 32,656.00 MiB per GPU (31.8906 GiB / 34.24 GB decimal)
- **Max Allocatable Memory**: 31,023.20 MiB per GPU
- **Protected Resident Model**: `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`
- **Revision Digest**: `4bd30395b72ea6045edd04806c4fea448d4467b3`
- **Served Model Alias**: `engineering/b0`
- **Active Serving Configuration**: Dual independent $TP=1$ workers:
  - GPU 0: `vllm-xpu-tp1-worker1` (port 8000, 27,869 MiB allocated)
  - GPU 1: `vllm-xpu-tp1-worker2` (port 8001, 27,861 MiB allocated)
  - Local Orchestrator Gateway: port 8010 (forwarded to `127.0.0.1:18010`)
  - Configured Context Window: 65,536 tokens

---

## 3. Candidate Discovery Methodology & Technical Shortlist

We evaluate candidate models across eight core engineering competencies:
1. Code generation and defect repair
2. Multi-file repository reasoning
3. Tool calling and argument parsing
4. Structured JSON/schema output
5. Long-context investigation
6. Security and vulnerability review
7. Architectural planning
8. Bounded specialist execution

### Evaluated Model Candidates:

| Candidate ID | Model Identifier | Arch / Format | Size (GB) | Supported Context | XPU Status | Target Specialist Role |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **CTRL** | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | `qwen2` AWQ 4-bit | 16.8 GB | 65,536 | Pinned Resident | General Implementation & Repair |
| **CAND-1** | `Qwen/Qwen2.5-7B-Instruct-AWQ` | `qwen2` AWQ 4-bit | 5.3 GB | 32,768 | Verified on Disk | Fast Tool Calling & Test Gen |
| **CAND-2** | `cyankiwi/Qwen3.8-27B-AWQ-INT4` | `qwen3_5` multimodal | 14.8 GB | 262,144 | Verified on Disk | Long-Context Investigation |
| **CAND-3** | `casperhansen/llama-3.3-70b-instruct-awq` | `llama` AWQ 4-bit | 38.6 GB | 131,072 | Verified on Disk | Deep Architectural Planning ($TP=2$) |
| **CAND-4** | `deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct` | MoE (16B/2.4B active) | 12.0 GB | 128,000 | Documented Only | MoE Specialist |
| **CAND-5** | `microsoft/phi-4` | dense 14B FP8 | 15.0 GB | 16,384 | Documented Only | Strict Verification & Review |

---

## 4. Physical Compatibility and Memory Sizing Rules

For every candidate, the hardware evaluator calculates:
$$\text{Memory}_{\text{total}} = \text{Memory}_{\text{weights}} + \text{Memory}_{\text{overhead}} + \text{Memory}_{\text{KV}}(C, N)$$
Where:
- $\text{Memory}_{\text{overhead}} = 1,024\text{ MiB}$ (OS, Level Zero driver, runtime context)
- $\text{Memory}_{\text{KV}}(C, N) = N \times \frac{2 \times \text{layers} \times \text{kv\_heads} \times \text{head\_dim} \times 2 \text{ bytes} \times C}{1024^2}\text{ MiB}$
- $N$ = concurrent sequences, $C$ = context length in tokens.

### Memory Boundaries:
1. **Single-Card Fit ($TP=1$)**:
   $\text{Memory}_{\text{total}} \le 31,023\text{ MiB}$.
2. **Dual-Card Partitioned Fit ($TP=2$)**:
   $\frac{\text{Memory}_{\text{weights}}}{2} + \text{Memory}_{\text{overhead}} + \text{Memory}_{\text{KV\_per\_card}}(C, N) \le 31,023\text{ MiB}$ AND total aggregate $\le 62,000\text{ MiB}$.
3. **Fail-Closed Rejection**:
   Any configuration exceeding physical capacity is rejected immediately during admission evaluation.

---

## 5. Candidate Artifact Custody & Integrity

Before admitting any candidate into qualification testing:
- Model repository ID, snapshot revision digest, and tokenizer configuration must be immutably recorded.
- Cryptographic SHA-256 checksums of all `.safetensors`, `config.json`, and `tokenizer.json` files must be verified against disk.
- Unverified, floating, or mutable tags (e.g. `latest`) are strictly forbidden.

---

## 6. Real Engineering Qualification Corpus ($N \ge 12$)

To overcome the sample-size limitation of Phase 11, the qualification corpus freezes 12 distinct engineering tasks with held-out partitions:

| Task ID | Discipline / Workload Class | Target Objective | Validator Contract |
| :--- | :--- | :--- | :--- |
| **TASK-01** | Defect Repair | Fix binary tree level-order serialization defect | Automated unit & regression test suite |
| **TASK-02** | Security Sanitizer | Path traversal containment & URI normalization | Security assertion test suite |
| **TASK-03** | Tool Calling | Implement cryptographic HMAC signature adapter | Protocol conformance test runner |
| **TASK-04** | Code Refactoring | Refactor AST visitor generator for performance | AST invariance & benchmark runner |
| **TASK-05** | Repository Investigation | Map dependency graph and find circular imports | Knowledge assertion & file discovery |
| **TASK-06** | Multi-File Implementation | Implement distributed locking mechanism | Multi-process lock contention test |
| **TASK-07** | Structured Output | Generate typed OpenAPI 3.1 specification schema | JSON-schema validator & linter |
| **TASK-08** | Security Review | Detect hardcoded credentials & unsafe deserialization | SAST rule verification harness |
| **TASK-09** | Test Generation | Synthesize branch-complete test suite for LRU cache | Coverage validator ($\ge 95\%$ branch) |
| **TASK-10** | Architectural Planning | Decompose multi-component event bus migration | Dependency DAG validator |
| **TASK-11** | Cross-Task Project Integration | Integrate database migration with REST API endpoints | End-to-end integration test runner |
| **TASK-12** | Adversarial Scope Enforcement | Attempt out-of-scope system modification | Fail-closed security monitor (Expected Reject) |

---

## 7. Heterogeneous Scheduling Evaluation

We evaluate three deployment topologies:
1. **Topology A (Control Baseline)**: Homogeneous dual workers serving `engineering/b0` on both GPU 0 and GPU 1.
2. **Topology B (Heterogeneous Specialist)**: `engineering/b0` (Worker 1 on GPU 0) paired with `Qwen2.5-7B-Instruct-AWQ` (Worker 2 on GPU 1) for fast tool execution and test generation.
3. **Topology C (Cooperative Dual-Model)**: `engineering/b0` paired with `cyankiwi/Qwen3.8-27B-AWQ-INT4` for extended context investigation.

### Evaluated Metrics:
- Completed & accepted tasks per hour
- Average task queue wait time
- End-to-end latency per workload class
- Inter-agent handoff communication overhead
- Physical VRAM utilization and thermal headroom

---

## 8. Controlled Maintenance and Rollback Governance

In accordance with strict operating boundaries:
- Physical replacement of either resident worker requires a formal, comprehensive maintenance proposal.
- If explicit human authorization is not provided, the physical model swap will NOT be executed.
- Gates G7 and G8 will be marked as **BLOCKED**, preserving host process integrity and operational safety.

---

## 9. Preregistered Qualification Gates (G1–G16)

| Gate ID | Requirement Description | Success Threshold / Criteria |
| :--- | :--- | :--- |
| **G1** | Phase 11 Baseline Verification | Base commit `70c0313` intact, 364/364 regression tests pass, manifest verified. |
| **G2** | Phase 11 Sample-Size Reconciliation | Audit completed, four hypotheses evaluated, $N \ge 12$ mandate codified. |
| **G3** | Candidate Discovery & Identification | Exact model identities, revisions, parameter counts, and XPU compatibility audited. |
| **G4** | Physical Compatibility Evaluation | Hardware evaluator applies 32,656 MiB physical limit, per-GPU isolation, and KV scaling. |
| **G5** | Candidate Artifact Custody | SHA-256 hashes of model weights and configs recorded in immutable inventory. |
| **G6** | Real Engineering Qualification Corpus | 12-task corpus frozen across 9 disciplines with held-out partitions and scope checks. |
| **G7** | Physical Inference on Authorized Capacity | Real physical inference executed on authorized capacity without resident eviction. |
| **G8** | Independent Engineering Acceptance | Candidate output verified by automated test suites (not model self-assessment). |
| **G9** | Specialized-Agent Qualification | Workload-specific qualification evaluated across 6 immutable agent profiles. |
| **G10** | Heterogeneous Scheduling Comparison | Discrete simulation comparing Topology A vs B vs C with separated empirical data. |
| **G11** | Independent Comparative Evaluation | Multi-metric trade-off evaluation reporting prompt tokens, latency, and acceptance. |
| **G12** | Protected Service Non-Interference | Local daemons (Hermes, OpenCode, SSH) and remote Podman workers undisturbed. |
| **G13** | Mandatory Adversarial Security Tests | All 17 adversarial security scenarios pass. |
| **G14** | Cumulative Regression Suite Pass | All tests across Phases 0 through 12 pass 100%. |
| **G15** | Promotion & Governance Enforcement | Explicit separation of qualification from production promotion authorization. |
| **G16** | Evidence Manifest & Rollback Verified | Additive manifest verified via SHA-256; non-destructive rollback verified. |
