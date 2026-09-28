# Phase 13 Expanded Homogeneous Control Campaign Report

**Document Identifier**: `phase13_expanded_control_report.md`  
**Governing Phase**: Phase 13 Final Continuation  
**Campaign Topology**: Dual-Resident Homogeneous Baseline (`cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` on GPU 0 & GPU 1)  
**Execution Timestamp**: Sun 2026-09-27 23:06:33Z to 23:27:44Z  
**Primary Trace**: [`phase13_expanded_control_results.json`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/evidence/phase13_expanded_control_results.json)  
**Runner Source**: [`expanded_physical_runner.py`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/src/autonomous_engineering/heterogeneous/expanded_physical_runner.py)

---

## 1. Executive Summary

Under the authorized expanded qualification window, a rigorous homogeneous control campaign was physically executed against the live dual-30B inference cluster (`10.0.8.5`):
- **Worker 1 (GPU 0, port 18000)**: Lead tasks (Architecture, Planning, Implementation, Integration, Acceptance).
- **Worker 2 (GPU 1, port 8001)**: Specialist offload tasks (Unit Tests, OpenAPI Schemas, SAST Reviews).
- **Installed Model**: `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` (revision `4bd30395b72ea6045edd04806c4fea448d4467b3`).

Across six complete 8-item multi-stage projects spanning all four repository archetypes:
$$\mathbf{6 / 6\ Projects\ Independently\ Accepted\ (100.0\%)}$$
$$\mathbf{16.99\ Independently\ Accepted\ Engineering\ Projects\ /\ Hour}$$

---

## 2. Per-Project Performance Breakdown

| Project ID | Repository Archetype | Total Latency | Stage 2 Offload Elapsed | Completion Tokens | Decode TPS | Independent Acceptance |
|---|---|---|---|---|---|---|
| **CTRL-01** | Distributed Consensus Engine | 212.02s | 57.58s | 3,744 tok | 18.14 tps avg | **ACCEPTED** (4/4 Gates) |
| **CTRL-02** | Durable Event Journal | 211.11s | 56.96s | 3,728 tok | 18.16 tps avg | **ACCEPTED** (4/4 Gates) |
| **CTRL-03** | API Microservices & Async Worker | 212.27s | 56.94s | 3,760 tok | 18.12 tps avg | **ACCEPTED** (4/4 Gates) |
| **CTRL-04** | Zero-Downtime Migration Engine | 212.30s | 57.08s | 3,752 tok | 18.15 tps avg | **ACCEPTED** (4/4 Gates) |
| **CTRL-05** | High-Throughput LRU Cache | 212.72s | 57.21s | 3,768 tok | 18.11 tps avg | **ACCEPTED** (4/4 Gates) |
| **CTRL-06** | Security Auth Gateway | 211.21s | 56.55s | 3,744 tok | 18.15 tps avg | **ACCEPTED** (4/4 Gates) |

---

## 3. Concurrency and Stage 2 Dynamics

In the homogeneous configuration:
- Worker 2 executes specialist tasks using the 30B MoE model.
- Because `max-num-seqs: 2` is enforced in `vllm-config.yaml`, dispatching 3 concurrent offload tasks (`TEST_GENERATION`, `STRUCTURED_OUTPUT`, `SECURITY_REVIEW`) causes two tasks to process in parallel while the third task waits in the KV cache queue.
- Consequently, the first two tasks complete in $\approx 28.5\text{ seconds}$, while the queued task completes in $\approx 57.0\text{ seconds}$.
- Mean Stage 2 wall-clock duration across all 6 control projects: **57.05 seconds**.

---

## 4. Control Baseline Metrics Summary

- **Total Observation Duration**: **1,271.63 seconds** ($\approx 21.19\text{ minutes}$).
- **Total Work Items Executed**: **48 work orders** (8 items $\times$ 6 projects).
- **Total Items Accepted**: **48 / 48 (100.0%)**.
- **Specialist Task Rate**: **50.96 accepted specialist tasks/hour**.
- **Primary Operational Metric**: **16.99 accepted projects/hour**.
- **Average Lead Task Decode Speed**: **18.17 tokens/second**.
- **Inter-Agent Handoff Quarantine**: Enforced via `ExternalAuthorityBoundary`; 0 unquarantined payloads.
