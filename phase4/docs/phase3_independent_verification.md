# Phase 3 Independent Baseline Verification and Rollback Specification

---

## 1. Executive Summary of Verification

Prior to conducting model qualification, specialist routing, and heterogeneous worker evaluation in Phase 4, the Phase 3 operational baseline was independently audited, verified against its cryptographic checksum manifest, and retested in the isolated Phase 4 workspace.

### Audit Findings
- **Baseline Git Revision**: `eab3b9f` (`git rev-parse HEAD`)
- **Base Branch**: `phase3-operational-service`
- **Worktree**: `/home/mike/Projects/aihost/.worktrees/phase4-model-eval`
- **Checksum Manifest Verification**: All 81 tracked files in `phase3/evidence/manifest.sha256` verified intact via `sha256sum -c` (0 mismatches, 0 missing files).
- **Automated Regression Suite**: 96 tests passing across Phase 0, Phase 1, Phase 2, and Phase 3:
  - Phase 0 (Offline Vertical Slice): 39 tests passing
  - Phase 1 (Controlled Live Boundary): 16 tests passing
  - Phase 2 (Durable Multi-Worker Execution): 17 tests passing
  - Phase 3 (Operational Work-Order Service & Cohort): 24 tests passing
  - Total: 96 passing, 0 failing, 0 skipped.
- **Terminal Phase 3 Disposition**: `PHASE_3_OPERATIONAL_ENGINEERING_BASELINE: PROVEN` (Affirmed).

---

## 2. Categorization of Prior Evidence

To prevent conflation of experimental conditions, Phase 3 evidence and test results are categorized strictly into three distinct tiers:

1. **Live Model Execution Evidence**:
   - Live interaction with `engineering/b0` (`Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`) hosted on Intel Arc Pro B65 hardware via Level Zero and vLLM XPU at `http://127.0.0.1:18010/v1`.
   - Verified token-authenticated requests, completion generation, tool calling, and live artifact repair during single-worker and two-worker runs.
2. **Deterministic Sandboxed Fixture Execution**:
   - The 8-fixture representative cohort spanning 4 task classes:
     - Defect Repair (`defect_repair_repo`, `defect_repair_series_repo`)
     - Multi-File Implementation (`multi_file_repo`, `multi_file_tax_repo`)
     - Test Development (`test_dev_repo`, `test_dev_auth_repo`)
     - Maintainability / Refactoring (`maintainability_repo`, `maintainability_config_repo`)
   - Executed within Bubblewrap OS containment with independent test runner execution (`pytest`), content-addressed artifact hashing, and supervisor-authoritative admission/acceptance.
3. **Simulated Worker & Control-Plane Invariant Tests**:
   - Workflow engine fencing tokens, monotonic revision sequences, DAG task scheduling, crash-recovery transactions, and timeout handling.
   - Tested using mock/simulated worker adapters to exercise boundary and failure states deterministically without non-deterministic LLM variance.

---

## 3. Preserved Control Serving Configuration and Identity

The exact operating configuration of the Phase 3 control system is frozen as follows:

| Component | Verified Specification |
| :--- | :--- |
| **Model Repository** | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` |
| **Model Gateway Alias** | `engineering/b0` |
| **Architecture** | Mixture-of-Experts Coder (30B Total / ~3.3B Active per token) |
| **Weight Format / Quantization** | AWQ-4bit (INT4 weights, FP16/BF16 activations) |
| **Accelerator Target** | 2x Intel Arc Pro B65 (PCIe `0000:51:00.0`, `0000:93:00.0`, 32GB VRAM each) |
| **Serving Runtime** | vLLM XPU (`vllm-openai-xpu` / Level Zero `libze-intel-gpu1=26.22.38646.7`) |
| **Driver Stack** | Intel Linux Xe KMD (`xe-24.1` / Compute Runtime `24.52.32224.5`) |
| **Serving Topology** | TP=2 across dual B65 GPUs |
| **Context Length (`max_model_len`)** | 16,384 tokens |
| **Tool Call Parser** | `qwen3_coder` (OpenAI-compatible tool calling schema) |
| **Gateway Endpoint** | `http://127.0.0.1:18010/v1` |
| **Authentication Credential** | Bearer token at `/home/mike/.config/opencode/t5820-client-token` |
| **Sampling Defaults** | Temperature 0.0, Top-P 1.0, Max Output Tokens 4096 |

---

## 4. Protected Campaign Safeguards & Rollback Identity

1. **Active Campaign Protection**:
   - Host T5820 is running a concurrent autonomous-readiness evaluation campaign:
     - Gateway Daemon: PID 986
     - OpenCode Session: PID 3130937
     - SSH Forwarding Tunnel: PID 2093382 (`127.0.0.1:18010 -> 10.0.8.5:8010`)
   - **Constraint**: Phase 4 will never kill, signal, or reconfigure these processes, nor alter their gateway bindings or GPU allocations.
2. **Rollback Commit**:
   - `eab3b9f` (tag/commit representing Phase 3 completion).
   - In the event of any qualification harness regression or failure, all working states can be reverted cleanly to `eab3b9f` without data loss or repository corruption.
