# Phase 13 Expanded Heterogeneous Campaign Report

## 1. Executive Summary
- **Evaluation Campaign**: Preregistered 6-Project Heterogeneous Sustained Campaign (`HETERO-01` to `HETERO-06`).
- **Cluster Topology**:
  - **Worker 1 (Lead)**: `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` on GPU 0 (PCI `0000:51:00.0`, Port 8000). Handles Architecture (Items 01-03), Security Review (Item 06), Integration (Item 07), and Project Acceptance (Item 08).
  - **Worker 2 (Specialist)**: `Qwen/Qwen2.5-7B-Instruct-AWQ` on GPU 1 (PCI `0000:93:00.0`, Port 8001). Handles Unit Test Generation (Item 04) and OpenAPI 3.1 Schemas (Item 05).
- **Execution Timestamp**: `2026-09-28T02:13:37Z` to `2026-09-28T02:32:35Z`.
- **Campaign Outcome**: **100% ACCEPTANCE (6/6 Projects Independently Accepted)**.
- **Primary Metric**: **18.98 independently accepted engineering projects per hour** (1,137.87s elapsed).

## 2. Project-by-Project Execution Breakdown

| Project ID | Project Archetype | Total Duration | Stage 2 (Concurrent) | Items Accepted | 4-Gate Decision |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **HETERO-01** | Distributed Consensus & State Machine Engine | 189.86s | 35.05s | 8 / 8 | **ACCEPTED** |
| **HETERO-02** | Durable Event Journal & Compactor | 189.19s | 34.73s | 8 / 8 | **ACCEPTED** |
| **HETERO-03** | REST / OpenAPI Microservices & Async Worker | 189.90s | 34.90s | 8 / 8 | **ACCEPTED** |
| **HETERO-04** | Zero-Downtime Database Migration Engine | 189.17s | 34.94s | 8 / 8 | **ACCEPTED** |
| **HETERO-05** | High-Throughput In-Memory LRU Cache & Eviction | 190.33s | 34.93s | 8 / 8 | **ACCEPTED** |
| **HETERO-06** | Security-Critical Auth Gateway & Permission Fencing | 189.42s | 34.76s | 8 / 8 | **ACCEPTED** |

## 3. Key Observations and Performance Dynamics

1. **Specialist Concurrency and Throughput**:
   - The 7B specialist on Worker 2 executed Unit Test Suite (`-04`) and Schema Contract (`-05`) concurrently in ~18.9s - 19.6s at **26.0 - 27.1 decode tokens/second**.
   - Because `max-num-seqs: 4` is configured on Worker 2, both specialist tasks ran concurrently without serial queueing.
2. **Lead Security Fencing Invariant**:
   - Per the remediation policy established in the Phase 13 Addendum, Item `-06` (SAST & Security Invariant Review) was strictly routed to Lead 30B on Worker 1.
   - Lead security evaluation completed in ~34.7s - 35.0s, determining the overall Stage 2 critical path.
3. **Stage 2 Acceleration**:
   - Mean Stage 2 elapsed time decreased from **57.05s** (in dual-30B control) to **34.88s**, representing a **38.86% reduction in concurrent execution latency**.
4. **Independent Acceptance Rigor**:
   - All 6 projects passed all 4 independent acceptance gates:
     - Gate 1 (Syntax / Code Validity): 100%
     - Gate 2 (Test Coverage & Passing): 100%
     - Gate 3 (Lead Security Review): 100%
     - Gate 4 (Lead Multi-Stage Integration): 100%
