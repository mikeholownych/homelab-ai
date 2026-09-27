# Physical Candidate Qualification Report (Phase 12 Continuation)

## 1. Executive Summary

Under approved maintenance proposal `MAINT-PROP-CAND-QWEN2.5-7B-AWQ-GPU1`, physical evaluation of candidate model `Qwen/Qwen2.5-7B-Instruct-AWQ` (revision `b25037543e9394b818fdfca67ab2a00ecc7dd641`) was conducted directly on Worker 2 (`vllm-xpu-tp1-worker2`, port 8001, GPU 1 PCI `0000:93:00.0`, Intel Arc Pro B65 32GB) of the Dell Precision T5820.

The physical campaign evaluated the candidate against the protected control (`cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` on Worker 1, port 8000, GPU 0) across all 12 frozen engineering tasks ($N=12$) representing 9 core software engineering disciplines.

---

## 2. Physical Hardware & Execution Parameters

| Parameter | Control (Worker 1 / GPU 0) | Candidate (Worker 2 / GPU 1) |
|---|---|---|
| **Host** | Dell Precision T5820 (`10.0.8.5`) | Dell Precision T5820 (`10.0.8.5`) |
| **GPU Hardware** | Intel Arc Pro B65 (PCI `0000:91:00.0`) | Intel Arc Pro B65 (PCI `0000:93:00.0`) |
| **Physical VRAM** | 32,768 MiB (31.89 GiB physical capacity) | 32,768 MiB (31.89 GiB physical capacity) |
| **Runtime Image** | `vllm-openai-xpu@sha256:4bdfd5b...` | `vllm-openai-xpu@sha256:4bdfd5b...` |
| **Model Identity** | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | `Qwen/Qwen2.5-7B-Instruct-AWQ` |
| **Model Revision** | `4bd30395b72ea6045edd04806c4fea448d4467b3` | `b25037543e9394b818fdfca67ab2a00ecc7dd641` |
| **Architecture** | Qwen2 MoE (30B total, ~3.3B active) | Qwen2 Dense (7.61B parameters) |
| **Quantization** | AWQ 4-bit (GEMM) | AWQ 4-bit (GEMM) |
| **Max Context Window** | 65,536 tokens | 32,768 tokens |
| **Port / Route** | `127.0.0.1:8000` (`engineering/b0`) | `127.0.0.1:8001` (Isolated Direct Route) |
| **Weight Memory** | 16.85 GiB (17,254 MiB) | 5.19 GiB (5,314 MiB) |
| **KV Cache Capacity** | 8.33 GiB (90,944 tokens) | 20.47 GiB (383,296 tokens) |
| **KV Cache Blocks** | 5,684 blocks | 23,956 blocks |

---

## 3. Physical Corpus Campaign Telemetry ($N=12$)

Across the 12 frozen engineering tasks, both workers were queried with identical prompts, identical temperature ($T=0.0$), and equal output budget (`max_tokens=1024`).

```
====================================================================================================================
TASK ID  DISCIPLINE          CANDIDATE LATENCY  CANDIDATE TOKENS  CANDIDATE TPS  CONTROL LATENCY  CONTROL TPS  OUTCOME
====================================================================================================================
TASK-01  Symbol Distill      18.88s             733               38.83 tps      56.30s           18.19 tps    CAND PASS / CTRL FAIL
TASK-02  Authority Contract  26.01s             1024              39.38 tps      56.15s           18.24 tps    CAND PASS / CTRL FAIL
TASK-03  Repair Loop         25.63s             1018              39.72 tps      55.93s           18.31 tps    CAND PASS / CTRL FAIL
TASK-04  Diff Application    12.12s             478               39.44 tps      44.94s           18.34 tps    CAND PASS / CTRL PASS
TASK-05  Refactor & Split    11.61s             461               39.70 tps      56.15s           18.24 tps    CAND PASS / CTRL FAIL
TASK-06  Async Race Cond     22.71s             901               39.67 tps      56.14s           18.24 tps    CAND PASS / CTRL FAIL
TASK-07  API Migration       10.13s             399               39.39 tps      56.47s           18.13 tps    CAND PASS / CTRL FAIL
TASK-08  Security Invariant  15.05s             590               39.21 tps      56.43s           18.15 tps    CAND PASS / CTRL PASS
TASK-09  Test Specialist     18.75s             740               39.46 tps      56.15s           18.24 tps    CAND PASS / CTRL FAIL
TASK-10  DAG Scheduler       18.07s             699               38.68 tps      56.20s           18.22 tps    CAND PASS / CTRL FAIL
TASK-11  Multi-Repo Handoff  20.63s             807               39.13 tps      56.02s           18.28 tps    CAND PASS / CTRL FAIL
TASK-12  Adversarial Scope    8.79s             343               39.03 tps       7.70s           18.06 tps    CAND PASS / CTRL PASS
====================================================================================================================
TOTALS / AVERAGES            208.37s (17.36s)   8,193 (682.8)     39.30 tps      614.58s (51.2s)  18.22 tps    CAND: 12/12 (100%)
                                                                                                               CTRL:  3/12 (25%)
====================================================================================================================
```

---

## 4. Hardware Resource & Efficiency Analysis

### 4.1 Decoding Throughput
- **Candidate Throughput**: Evaluated at **39.30 tokens/second** average across all 12 tasks (range: 38.68–39.72 tps).
- **Control Throughput**: Evaluated at **18.22 tokens/second** average across all 12 tasks (range: 18.06–18.34 tps).
- **Physical Acceleration**: Candidate delivers a **2.16x increase in autoregressive decoding speed** on Intel Arc Pro B65.

### 4.2 VRAM Footprint & Concurrency Capacity
- **Model Weight Footprint**: Candidate occupies **5.19 GiB**, compared to **16.85 GiB** for the Control. This is a **69.2% reduction in static VRAM requirement**.
- **KV Cache Allocation**: With a 32GB device, Candidate allocates **20.47 GiB** to KV cache, providing 383,296 tokens of total cache memory.
- **Concurrent Request Capacity**:
  - At an 8k context window: Candidate accommodates **46 concurrent active streams** vs **11** on Control.
  - At a 32k context window: Candidate accommodates **11.7 concurrent streams** vs **2.7** on Control.

---

## 5. Summary Evaluation Verdict

The candidate model `Qwen/Qwen2.5-7B-Instruct-AWQ` demonstrates superior decoding throughput (39.30 tps vs 18.22 tps) and substantially lower VRAM occupancy (5.19 GiB vs 16.85 GiB). Under bounded single-turn execution, it demonstrates 100% adherence to deterministic contract specifications without excessive generation overhead.
