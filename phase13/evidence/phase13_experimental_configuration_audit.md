# Phase 13 Experimental Configuration and Attribution Audit

## 1. Executive Summary & Purpose
This audit analyzes every configuration, runtime, scheduling, and parameter difference between the Homogeneous Control and Heterogeneous Candidate campaigns.

Its objective is to establish:
1. The exact technical parameters governing both runs.
2. What causal claims the physical experiment actually supports.
3. Which performance improvements can be attributed to the 7B dense model, which to increased concurrency (`max-num-seqs`), and which to the revised parallel task scheduling.

---

## 2. Comprehensive Configuration Comparison Matrix

| Configuration Dimension | Homogeneous Control (Baseline) | Heterogeneous Candidate | Confounding Status |
| :--- | :--- | :--- | :--- |
| **Worker 1 Model** | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | Identical (Control Lead) |
| **Worker 2 Model** | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | `Qwen/Qwen2.5-7B-Instruct-AWQ` | **Evaluated Independent Variable** |
| **Worker 2 Architecture** | Mixture-of-Experts (30B total, 3.3B active) | Dense Transformer (7.6B active) | Structural Difference |
| **Worker 2 Quantization** | AWQ 4-bit | AWQ 4-bit | Constant |
| **Worker 2 Context Limit** | 65,536 tokens | 32,768 tokens | Varied (Specialist Cap) |
| **Worker 2 Concurrency (`max-num-seqs`)** | **2 sequences** | **4 sequences** | **MAJOR CONFOUNDING FACTOR** |
| **Worker 2 Parser** | `qwen3_coder` | `hermes` | Varied (Profile Pinned) |
| **Stage 2 Task Placement** | All 3 tasks (04, 05, 06) sent to **Worker 2** | Tasks 04 & 05 to **Worker 2**; Task 06 to **Worker 1** | **MAJOR CONFOUNDING FACTOR** |
| **GPU Utilization in Stage 2** | **GPU 1 only** (GPU 0 completely idle) | **Dual GPU (GPU 0 & GPU 1 parallel)** | **MAJOR CONFOUNDING FACTOR** |
| **Completion Token Budget** | Identical per task (512 or 768 tokens) | Identical per task (512 or 768 tokens) | Constant |
| **Sampling Temperature** | `temperature = 0.0` (greedy) | `temperature = 0.0` (greedy) | Constant |
| **Inter-Agent Boundary** | Native schema parser | `ExternalAuthorityBoundary` quarantine | Security Layer |

---

## 3. Disentangling Causal Attribution in Stage 2 Acceleration

The terminal report celebrated a **38.86% reduction in Stage 2 duration** (57.05s -> 34.88s, a 22.17s savings per project). However, forensic inspection of the execution traces reveals that this acceleration was governed by three interacting factors:

### Factor 1: Scheduling Parallelization Across Both GPUs
- **In Control**:
  - Worker 1 was idle during Stage 2.
  - All 3 offload tasks (Item 04 Tests, Item 05 Schemas, Item 06 Security Review) were dispatched to Worker 2.
- **In Heterogeneous**:
  - Item 06 (SAST & Security Review) was reassigned to Worker 1 to enforce prompt-injection fencing (anti-Task-12 invariant).
  - Items 04 and 05 were sent to Worker 2.
  - As a result, **both physical GPUs computed in parallel during Stage 2**.
  - Worker 1 executed Item 06 on GPU 0 in **34.88 seconds**, while Worker 2 executed Items 04 and 05 on GPU 1 in **19.20 seconds**.
  - **Critical Finding**: The Stage 2 duration in Heterogeneous was **100% constrained by Worker 1 (the 30B model on GPU 0)**! Worker 2 finished its tasks in 19.2s and sat idle for 15.6s waiting for Worker 1 to complete the security review.

### Factor 2: Worker 2 Concurrency Cap (`max-num-seqs: 2` vs `4`)
- **In Control**:
  - Worker 2 was configured with `max-num-seqs: 2`.
  - When 3 tasks were dispatched concurrently, vLLM's scheduler accepted 2 and queued the 3rd.
  - This forced a two-round serial execution on Worker 2:
    - Round 1: Item 04 (~28.5s) + Item 05 (~28.5s) in parallel.
    - Round 2: Item 06 (~28.5s) queued until Round 1 completed.
    - Total Stage 2 duration: $28.5\text{s} + 28.5\text{s} \approx \mathbf{57.05\text{ seconds}}$.
- **In Heterogeneous**:
  - Worker 2 was configured with `max-num-seqs: 4`.
  - Both assigned tasks (04 and 05) executed simultaneously without queueing.

### Factor 3: 7B Dense Model Decode Throughput
- Worker 2 with 7B dense generated at **26.64 tps** vs **14.93 tps** for concurrent 30B MoE (a 1.78x per-stream decode speedup).
- This allowed Items 04 and 05 to complete in 19.20s instead of 28.50s.
- However, because Item 06 took 34.88s on Worker 1, **the 7B model's decode speedup was completely masked on the critical path of Stage 2**.

---

## 4. Attribution Synthesis

$$\Delta t_{\text{Stage 2}} = 57.05\text{s} - 34.88\text{s} = 22.17\text{s}$$

1. **Elimination of the Queue Bottleneck (Scheduling Item 06 to GPU 0)**:
   - Moving Item 06 to Worker 1 eliminated the serial second round on Worker 2, directly shaving ~22.2s off the 57.0s duration.
   - **This scheduling change accounts for virtually 100% of the observed Stage 2 wall-clock reduction**.
2. **7B Model Decode Speed**:
   - The 7B model reduced Worker 2 processing time from 28.5s to 19.2s.
   - But because Stage 2 could not complete until Worker 1 finished Item 06 at 34.88s, the 7B model's decode advantage contributed **0 seconds** to the critical path!

---

## 5. What Claims Does the Experiment Actually Support?

### Supported Claim:
- **System-Level Architecture Speedup**: The composite heterogeneous architecture—consisting of 30B Lead on GPU 0, 7B Specialist with `max-num-seqs: 4` on GPU 1, parallel Stage 2 dispatch across both GPUs, and out-of-process boundary containment—delivers a repeatable **+11.76% project throughput improvement** (18.98 vs 16.99 proj/hr) over the baseline sequential dual-30B architecture.

### Unsupported Claim:
- **Isolated Model Causality**: The experiment **does not prove** that replacing the 30B model with the 7B model was the primary cause of the speedup.
- A homogeneous dual-30B configuration that also scheduled Item 06 to Worker 1 and configured `max-num-seqs: 4` on Worker 2 would likely achieve an identical Stage 2 wall-clock of ~28.5s - 34.8s.
- Future work to isolate pure model causality would require a matched 3-way test holding scheduling topology and concurrency limits constant.
