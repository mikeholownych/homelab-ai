# Phase 13 Three-Configuration Experimental Protocol: Causal Disentanglement and Invariant Controls

## 1. Governing Purpose & Architecture

This protocol freezes the experimental specifications for the Phase 13 Scheduling-Matched Causal Qualification Campaign.

The objective is to strictly isolate:
1. **The Pure Scheduling Effect (A vs. B)**: The throughput and latency gain achievable solely by optimizing task placement across dual-30B workers.
2. **The Pure Model Effect (B vs. C)**: The incremental benefit of replacing Worker 2 with the specialized 7B AWQ dense model while holding scheduling, task placement, and dependency graphs strictly identical.
3. **The Combined System Effect (A vs. C)**: The cumulative architectural change from the historical baseline to the heterogeneous architecture.

---

## 2. Experimental Configurations Specification

```
+----------------------------------------------------------------------------------------------------+
| CONFIGURATION SPECIFICATION MATRIX                                                                 |
+-------------------+----------------------------+-----------------------------------+---------------+
| Parameter         | Configuration A (Control)  | Configuration B (Matched Control) | Configuration C (Candidate)   |
+-------------------+----------------------------+-----------------------------------+---------------+
| Worker 1 (GPU 0)  | 30B MoE (4-bit AWQ)        | 30B MoE (4-bit AWQ)               | 30B MoE (4-bit AWQ)           |
| Worker 2 (GPU 1)  | 30B MoE (4-bit AWQ)        | 30B MoE (4-bit AWQ)               | 7B Dense (4-bit AWQ)          |
| Stage 1 Items     | Worker 1 (Lead 30B)        | Worker 1 (Lead 30B)               | Worker 1 (Lead 30B)           |
| Stage 2 Item 04   | Worker 2 (30B)             | Worker 2 (30B)                    | Worker 2 (7B)                 |
| Stage 2 Item 05   | Worker 2 (30B)             | Worker 2 (30B)                    | Worker 2 (7B)                 |
| Stage 2 Item 06   | Worker 2 (30B - Serial)    | Worker 1 (30B - Parallel)         | Worker 1 (30B - Parallel)     |
| Stage 3 Items     | Worker 1 (Lead 30B)        | Worker 1 (Lead 30B)               | Worker 1 (Lead 30B)           |
| Worker 2 Conc.    | 2 active seqs (1 queued)   | 2 active seqs (0 queued)          | 2 active seqs (0 queued)      |
| Worker 1 Conc.    | 1 active seq               | 1 active seq                      | 1 active seq                  |
| Validation Model  | Lead 30B + AST/Schema Gate | Lead 30B + AST/Schema Gate        | External Boundary + Quarantine|
| Model Swap Req.   | None (Existing Baseline)   | None (Existing Baseline)          | Authorized Worker 2 Swap      |
+-------------------+----------------------------+-----------------------------------+---------------+
```

---

## 3. Work Breakdown Structure & Dependency DAG

Each evaluated project executes an 8-item dependency DAG across three stages:

### Stage 1: Sequential Lead Investigation & Planning (Worker 1 / 30B)
- **Item 01 (Investigation)**: Architecture investigation, component identification, isolation boundaries. Context: 512 max tokens.
- **Item 02 (Planning)**: Execution DAG definition, rollback boundary specification. Depends on Item 01. Context: 512 max tokens.
- **Item 03 (Core Engine)**: Thread-safe core logic implementation, state machine refactoring. Depends on Item 02. Context: 768 max tokens.

### Stage 2: Specialist Concurrent Offload
- **Item 04 (Unit Tests)**: Branch-complete pytest test suite covering edge cases and regression invariants. Context: 512 max tokens. Assigned to **Worker 2**.
- **Item 05 (Schema Contract)**: OpenAPI 3.1 JSON schema and endpoint contracts. Context: 512 max tokens. Assigned to **Worker 2**.
- **Item 06 (Security Review)**: Static application security testing (SAST), deserialization review, memory safety. Context: 512 max tokens.
  - **Configuration A**: Assigned to **Worker 2** (queues serially behind Items 04 & 05).
  - **Configuration B**: Assigned to **Worker 1** (executes concurrently with Worker 2).
  - **Configuration C**: Assigned to **Worker 1** (executes concurrently with Worker 2).

### Stage 3: Sequential Lead Integration & Project Acceptance (Worker 1 / 30B)
- **Item 07 (Integration)**: End-to-end integration of core engine, tests, schemas, and security patches. Depends on Items 04, 05, 06. Context: 512 max tokens. Assigned to **Worker 1**.
- **Item 08 (Acceptance)**: Independent 4-gate verification and supervisor sign-off. Depends on Item 07. Context: 512 max tokens. Assigned to **Worker 1**.

---

## 4. Evaluation Corpus & Archetypes

To ensure representative evaluation, the 6 standard engineering archetypes from Phase 13 are maintained across all three configurations:
1. `proj-exp-01`: **FastAPI Webhook Dispatcher** (Async event pipeline, HMAC signature verification).
2. `proj-exp-02`: **Distributed Token Bucket Rate Limiter** (Redis backend, atomic Lua scripts).
3. `proj-exp-03`: **Streaming Data Normalization Pipeline** (Chunked generator, backpressure control).
4. `proj-exp-04`: **Multi-Tenant Role-Based Access Control** (JWT validation, tenant isolation).
5. `proj-exp-05`: **Finite State Machine Workflow Engine** (Atomic state transitions, rollback hooks).
6. `proj-exp-06`: **Time-Series Sliding Window Aggregator** (Thread-safe circular buffer, LRU eviction).

---

## 5. Model Invariants & Configuration Hashes

| Node | Model Name | Pinned Snapshot Revision | Serving Port | Target Hardware |
| :--- | :--- | :--- | :--- | :--- |
| **Worker 1 (All)** | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | `4bd30395b72ea6045edd04806c4fea448d4467b3` | `8000` (Tunnel `18000`) | GPU 0 (PCI `0000:51:00.0`) |
| **Worker 2 (A & B)**| `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | `4bd30395b72ea6045edd04806c4fea448d4467b3` | `8001` | GPU 1 (PCI `0000:93:00.0`) |
| **Worker 2 (C)** | `Qwen/Qwen2.5-7B-Instruct-AWQ` | `b25037543e9394b818fdfca67ab2a00ecc7dd641` | `8001` | GPU 1 (PCI `0000:93:00.0`) |
| **Gateway (All)** | Production Orchestrator (`engineering/b0`) | Pinned Commit `d735ef9` | `8010` (Tunnel `18010`) | Host Loopback |

- **Decoding Invariant**: `temperature = 0.0`, greedy search, identical system prompts.
- **Worker 2 Baseline Config Hash**: `641c9402ebbc56f5d599512894f72a02304fd6615edbb7a2875ab48f93f4e08b`.

---

## 6. Execution Sequencing & Safety Protocol

1. **Preflight Health Verification**: Confirm GPU health, VRAM utilization, gateway status, and protected daemons (PIDs 986, 2093382, 3130937).
2. **Execute Configuration A**: Run on live dual-30B baseline. Collect telemetry to `phase13_configuration_a_results.json`.
3. **Execute Configuration B**: Run on live dual-30B baseline with revised scheduling. Collect telemetry to `phase13_configuration_b_results.json`.
4. **Maintenance Switch (Worker 2)**:
   - Stop `aihost-vllm-worker2.service`.
   - Update `vllm-config.yaml` to candidate 7B snapshot.
   - Start Worker 2 and await readiness probe on port 8001.
5. **Execute Configuration C**: Run on 30B (Worker 1) + 7B (Worker 2). Collect telemetry to `phase13_configuration_c_results.json`.
6. **Physical Containment Revalidation**: Replay Task 12 attack and 9 input channel probes against Worker 2 (7B).
7. **Mandatory Baseline Restoration**:
   - Stop Worker 2.
   - Restore `vllm-config.yaml.baseline-backup`.
   - Start Worker 2 and restart orchestrator gateway.
   - Verify SHA-256 (`641c9402`), readiness, and round-robin gateway health.
