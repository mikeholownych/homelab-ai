# Phase 12 Qualification and Promotion Governance Report

## 1. Executive Summary

In accordance with Workstream J and Gate G15, this report formalizes the operational boundaries separating **technical qualification** from **production promotion authorization**.

Under the governance rules of the Autonomous Engineering System, an autonomous agent possesses the authority to evaluate, qualify, and propose candidate configurations. However, **the agent has zero authority to promote a candidate into production serving or alter production model aliases without explicit human approval**.

---

## 2. Decoupled Governance Tiers

```
+---------------------------------------------------------------------------------------------------+
| TIER 1: INFRASTRUCTURE QUALIFICATION                                                              |
|   Scope: Hardware evaluator, artifact registry, qualification corpus, and scheduling model.       |
|   Status: FULLY QUALIFIED (Proven in Phase 11 & Phase 12; 56/56 Phase 12 tests pass).              |
+---------------------------------------------------------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
| TIER 2: PHYSICAL MODEL COMPATIBILITY                                                              |
|   Scope: Evaluating memory envelopes, KV cache growth, and kernel support on Intel Arc Pro B65.   |
|   Candidate: Qwen/Qwen2.5-7B-Instruct-AWQ (5.3 GB weights, 7.2 GB runtime VRAM).                  |
|   Status: PHYSICALLY COMPATIBLE (Fits single GPU with >23.8 GiB headroom).                        |
+---------------------------------------------------------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
| TIER 3: WORKLOAD-SPECIFIC SPECIALIST QUALIFICATION                                               |
|   Scope: Assessing model capability against immutable specialized-agent profiles.                 |
|   Candidate: Qwen/Qwen2.5-7B-Instruct-AWQ.                                                        |
|   Status: QUALIFIED AS TEST & TOOL SPECIALIST (Disqualified as General Implementation Lead).      |
+---------------------------------------------------------------------------------------------------+
                                                  |
                                                  v
+---------------------------------------------------------------------------------------------------+
| TIER 4: HETEROGENEOUS TOPOLOGY QUALIFICATION                                                      |
|   Scope: Multi-worker simulation comparing Topology A (Dual 30B) vs Topology B (30B + 7B).        |
|   Status: QUALIFIED AS TARGET TOPOLOGY (+27.7% throughput, -56.2% wait time).                     |
+---------------------------------------------------------------------------------------------------+
                                                  |
                                                  v
+===================================================================================================+
| TIER 5: PRODUCTION PROMOTION & DEPLOYMENT AUTHORIZATION                                           |
|   Scope: Altering physical container mounts, executing worker restarts, modifying model routing.   |
|   Status: HELD AT GATE — REQUIRES EXPLICIT HUMAN AUTHORIZATION                                    |
|   Current State: STOPPED PENDING HUMAN AUTHORIZATION                                              |
+===================================================================================================+
```

---

## 3. Candidate Promotion Evaluation

### 3.1 Candidate 1: `Qwen/Qwen2.5-7B-Instruct-AWQ`
- **Infrastructure Status**: Qualified.
- **Physical Sizing Status**: Qualified (Single-card fit).
- **Specialist Role Status**: Qualified for `Test Engineer` and `Tool Calling`.
- **General Engineering Role Status**: Disqualified (Context capacity 32K vs 65K; limited multi-file refactoring reasoning).
- **Promotion Recommendation**: Propose for secondary worker deployment (Topology B) under controlled maintenance plan [`MAINT-PROP-CAND-QWEN2.5-7B-AWQ-GPU1`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase12/evidence/maintenance_and_rollback_plan.md).
- **Promotion Action**: **HELD AT GATE**. Awaiting explicit operator signoff.

### 3.2 Candidate 2: `cyankiwi/Qwen3.8-27B-AWQ-INT4`
- **Promotion Status**: **REJECTED FOR PROMOTION**. Unsupported hybrid linear attention kernels in base runtime.

### 3.3 Candidate 3: `casperhansen/llama-3.3-70b-instruct-awq`
- **Promotion Status**: **REJECTED FOR PROMOTION**. Incurs ~38.5% PCIe bus latency penalty under $TP=2$ and evicts both resident workers, violating service redundancy.

---

## 4. Promotion Authority Boundary Invariant

- **Zero Autonomous Promotion**: The system will NEVER self-promote a candidate model or automatically swap container configuration without explicit written human consent.
- **Reversibility Guarantee**: Any approved deployment remains governed by the 15-minute maintenance window and immediate automated rollback triggers.
