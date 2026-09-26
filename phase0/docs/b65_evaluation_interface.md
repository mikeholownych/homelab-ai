# Intel Arc Pro B65 Worker Specialization and Model Evaluation Interface

**Document ID**: SPEC-B65-EVAL-PHASE0-2026-09-26  
**Status**: APPROVED / IMPLEMENTATION BASELINE  
**Author**: Antigravity Autonomous Engineering Agent  
**Context**: Heterogeneous Worker Routing (Section 9) & Model Evaluation Interface (Section 10)  

---

## 1. Heterogeneous Hardware Context

The target execution host (T5820 workstation) features two independent Intel Arc Pro B65 GPUs:
- **Card A (B65-0)**: 16 GB GDDR6, PCIe topology node 0.
- **Card B (B65-1)**: 16 GB GDDR6, PCIe topology node 1.

Rather than forcing both cards into a homogeneous tensor-parallel cluster (which suffers from inter-card PCIe bandwidth bottlenecks), the system treats each card as an independent, specialized worker node capable of running different model architectures, quantization formats, and runtime configurations.

### Asymmetry by Design
- **Worker Profile 1 (e.g., Code Implementer / Fast Patcher)**:
  - Optimized for low-latency code generation and targeted patch synthesis.
  - Model: Qwen2.5-Coder-14B-Instruct or Qwen2.5-Coder-32B-Instruct in INT4/FP8.
  - Runtime: vLLM XPU backend with continuous batching.
- **Worker Profile 2 (e.g., Deep Reasoner / Architecture Reviewer)**:
  - Optimized for long-context comprehension, dependency analysis, and multi-file code review.
  - Model: DeepSeek-Coder-V2-Lite or specialized reasoning model.
  - Runtime: IPEX-LLM / vLLM with extended context window (64k).

---

## 2. Versioned Worker Capability Profile Schema

A worker's capability profile is an empirical, cryptographic record of its deployed configuration and proven task competencies. Advertised synthetic benchmarks (e.g., HumanEval, GSM8K) are classified as purely advisory; authoritative admission to tasks requires empirical verification on local task fixtures.

```json
{
  "profile_id": "prof-b65-0-qwen-fp8-v1",
  "worker_id": "worker-b65-0",
  "hardware": {
    "device_type": "intel_arc_pro_b65",
    "pci_slot": "0000:03:00.0",
    "vram_bytes": 17179869184,
    "driver_version": "24.26.29735"
  },
  "runtime_configuration": {
    "engine": "vllm_xpu",
    "engine_version": "0.6.2",
    "model_name": "Qwen/Qwen2.5-Coder-32B-Instruct",
    "model_revision": "c8942b0",
    "quantization": "fp8",
    "context_window": 32768,
    "tokenizer_hash": "b2f4c9...",
    "chat_template": "chatml",
    "tool_parser": "hermes_function_calling",
    "serving_parameters": {
      "max_num_seqs": 4,
      "block_size": 16,
      "gpu_memory_utilization": 0.90
    }
  },
  "empirical_capabilities": {
    "investigation": {
      "verified": true,
      "measured_pass_rate": 0.92,
      "sample_size": 50,
      "last_evaluated": "2026-09-25T14:00:00Z"
    },
    "defect_patch": {
      "verified": true,
      "measured_pass_rate": 0.88,
      "sample_size": 80,
      "last_evaluated": "2026-09-25T14:00:00Z"
    },
    "independent_review": {
      "verified": true,
      "measured_pass_rate": 0.84,
      "sample_size": 35,
      "last_evaluated": "2026-09-25T14:00:00Z"
    },
    "test_development": {
      "verified": false,
      "measured_pass_rate": 0.40,
      "sample_size": 10,
      "last_evaluated": "2026-09-25T14:00:00Z"
    }
  },
  "health_status": "HEALTHY",
  "profile_signature": "fa83c..."
}
```

---

## 3. Capability-Aware Routing Rules

The router executes deterministic matching based on five strict filters:

1. **Hardware & Capability Compatibility**:
   - The candidate worker must have `verified = true` for the required task skill (e.g. `defect_patch`).
   - The task's estimated token context must fit within `context_window`.
2. **Independence Constraint (Separation of Concerns)**:
   - For review or validation tasks, the candidate worker ID must **not** match the worker ID that produced the artifact under review:
     $$\text{Worker}_{\text{review}} \neq \text{Worker}_{\text{author}}$$
3. **Health & Availability**:
   - The worker must be reporting `HEALTHY` and have an active heartbeat within 30 seconds.
   - The worker must not exceed its maximum concurrent assignment limit (1 assignment per worker in Phase 0).
4. **Empirical Quality Ranking**:
   - When multiple candidates qualify, the worker with the higher `measured_pass_rate` on the specific skill is prioritized.
5. **Deterministic Fallback**:
   - If no healthy worker meets capability requirements, the router returns `ROUTING_FALLBACK_UNAVAILABLE`. The workflow engine suspends the task or escalates for human intervention rather than dispatching an unqualified worker.

---

## 4. Model and Quantization Evaluation Interface

To evaluate new models, quantizations (FP8, INT8, AWQ, GGUF), and Intel XPU runtimes without interrupting operations:

### 4.1 Evaluation Protocol
1. **Control Baseline**: The active Qwen2.5-Coder-32B deployment serves as the control baseline.
2. **Candidate Profiling**: Any new model configuration is deployed in an isolated offline evaluation worktree.
3. **Empirical Benchmark Suite**:
   - 20 standardized offline engineering fixtures:
     - 10 bug reproduction & repair tasks.
     - 5 multi-file refactoring tasks.
     - 5 test generation tasks.
   - Each task is graded strictly by an **independent acceptance validator** running isolated pytest fixtures.
4. **Primary Evaluation Metric**:
   - **Independent Task Acceptance Rate** ($\% \text{ accepted}$ without repair).
   - **First-Pass Repair Rate** ($\% \text{ accepted}$ with $\le 1$ bounded repair).
5. **Secondary Operational Metrics**:
   - Prompt processing latency ($ms$).
   - Token generation throughput ($tokens/sec$).
   - Peak VRAM allocation ($MB$).

### 4.2 Training Trace Curation
- Execution traces (prompt, tools called, produced diffs, validator verdicts) are captured in the immutable artifact store.
- **Trace Filtering**: Only traces resulting in an authoritative `ACCEPTED` disposition are admitted to the fine-tuning candidate pool.
- **Evaluation Isolation**: Held-out benchmark tasks and evaluation repos are cryptographically excluded from candidate training datasets to prevent evaluation contamination.

---
