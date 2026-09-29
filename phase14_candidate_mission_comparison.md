# Phase 14 Candidate Mission Comparison: Architectural Trade-Off Analysis

- **Date:** 2026-09-29
- **Author:** Autonomous Engineering System
- **Status:** Complete / Evaluated
- **Evaluation Criteria:** Expected Benefit, Evidence Quality, Implementation Scope, Operational Risk, Qualification Cost, Rollback Complexity

---

## 1. Candidate Mission Evaluation Matrix

| Mission Candidate | Focus Area | Expected Benefit | Evidence Quality | Implementation Scope | Operational Risk | Qualification Cost | Rollback Complexity |
|---|---|---|---|---|---|---|---|
| **Option A: Worker 1 Critical-Path Reduction** | Offload Item 01 (Investigation) to Worker 2 | **+17.5% throughput capacity** (18.97 $\rightarrow$ 22.3 proj/hr); -14.9% W1 occupancy | **VERY HIGH** (Empirically measured in Phase 13 DAG traces) | **BOUNDED** (Scheduler dispatch & contract updates) | **LOW** (Homogeneous dual-30B retained; zero container churn) | **LOW** (Deterministic DAG benchmark) | **TRIVIAL** (< 2s software mode toggle) |
| **Option B: Scheduling & Admission Optimization** | Multi-project pipeline interleaving & queue discipline | **+12% to +20% burst throughput**; reduces queue backlog accumulation | **HIGH** (Supported by Poisson queueing model) | **MODERATE** (Pipeline overlapping in orchestrator) | **MODERATE** (VRAM / KV-cache thrashing under concurrency) | **MODERATE** (Burst arrival qualification) | **LOW** (Disable pipeline interleaving) |
| **Option C: Engineering Quality & Repair Efficiency** | Structured validator feedback & compile error slicing | **Eliminates 28s retry penalty** on complex non-synthetic tasks | **MODERATE** (Empirical in real repos, low in synthetic tests) | **MODERATE** (Prompt augmentation & AST diff parser) | **LOW** (Non-interfering prompt engineering) | **LOW** (Contract tests on repair cases) | **TRIVIAL** (Revert prompt template) |
| **Option D: Model & Inference Optimization** | vLLM chunked prefill, FP8 quantization, or model swap | **+10% to +15% decode speedup** on Worker 1 | **LOW-MODERATE** (Intel XPU vLLM limits unclear) | **HIGH** (Container rebuilds, weights download, host maintenance) | **HIGH** (Thermal, VRAM OOM, Intel driver instability) | **HIGH** (Full maintenance drain & multi-hour burn-in) | **HIGH** (> 15 min container restore) |
| **Option E: Operational Reliability & Observability** | Prometheus exporter for real-time queue & DAG telemetry | **Eliminates observability blind spots**; automated bottleneck detection | **HIGH** (Phase 13 required post-hoc JSON parsing) | **LOW-MODERATE** (HTTP metrics endpoint in orchestrator) | **VERY LOW** (Passive read-only metrics collection) | **LOW** (Prometheus scraper validation) | **TRIVIAL** (Disable metrics scrape) |

---

## 2. In-Depth Comparative Assessment

### Option A: Worker 1 Critical-Path Reduction (Recommended Focus)
- **Rationale**: The Phase 13 bottleneck analysis established beyond doubt that Worker 1 is occupied 100% of project time ($189.7\text{ s}$ active), while Worker 2 is $79.2\%$ idle ($155.4\text{ s}$ idle). In production Configuration B, Worker 2 runs the **exact same 30B MoE model** as Worker 1. Offloading Item 01 (Investigation — codebase reconnaissance and symbol discovery) to Worker 2 utilizes Worker 2 during Stage 1 when it currently sits completely idle.
- **Authority Integrity**: Item 01 is non-authoritative read-only research; it produces an advisory investigation brief that Worker 1 consumes and verifies during Item 02 (Planning). The lead authority boundary remains strictly on Worker 1.
- **Outcome**: Directly raises the single-server project capacity ceiling from $18.97$ to $22.30$ projects/hour without requiring hardware maintenance, container restarts, or model swaps.

### Option B: Scheduling and Admission Optimization
- **Rationale**: Under burst arrivals ($\lambda = 4.0\text{ req/min}$), Worker 1 queue builds up because incoming projects wait for the previous project's Stage 3 to finish. Interleaving project stages could smooth the queue.
- **Drawback**: Running concurrent project stages on the Intel Arc Pro B65 GPUs risks KV-cache fragmentation and GPU memory exhaustion. Must be addressed after or in tandem with single-project DAG rebalancing.

### Option C: Engineering Quality and Repair Efficiency
- **Rationale**: Repair cycles add $\approx 28.2\text{ s}$ per turn. Providing structured error slices directly reduces iteration cost.
- **Drawback**: In the current benchmark projects, repair iterations were already 0 (first-pass acceptance was 100%). This optimization provides high value for complex real-world migrations, but produces marginal measured delta on the standard benchmark suite.

### Option D: Model and Inference Optimization
- **Rationale**: Accelerating Worker 1 decode directly shortens the critical path.
- **Drawback**: High operational risk. Replacing the 30B MoE model or changing vLLM runtime settings on Intel Arc Pro B65 requires container stops, model weight re-flashing, and host maintenance drains. Previous phases demonstrated that non-Qwen or smaller models fail complex architecture and security review. Any model swap carries high risk of regression for uncertain gain.

### Option E: Operational Reliability and Observability
- **Rationale**: High engineering value for operational maturity, but does not itself alter the critical path or increase accepted project throughput. Ideal as a supporting workstream alongside Option A.

---

## 3. Comparative Recommendation

**Option A (Worker 1 Critical-Path Reduction via Item 01 Offload)** is the most causally isolated, highest-leverage, lowest-risk candidate for Phase 14:
1. It directly attacks the proven dominant constraint ($189.7\text{ s}$ on Worker 1).
2. It requires zero physical hardware maintenance or container restarts.
3. It preserves the homogeneous dual-30B model inventory and the external authority boundary.
4. It can be paired with **Option E** (lightweight telemetry) for real-time validation.
