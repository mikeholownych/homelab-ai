# Production Deployment Readiness Proposal: Heterogeneous Dual-Worker Architecture

## Document ID: `DEPLOY-PROP-PHASE13-HETERO-PROD`
**Date**: 2026-09-27
**Target Environment**: Dell Precision T5820 (`10.0.8.5`)
**Author**: Principal Autonomous Engineering Agent
**Authority Status**: `RECOMMENDED_PENDING_SEPARATE_HUMAN_AUTHORIZATION`

---

## 1. Executive Summary & Purpose

This proposal outlines the production deployment specification for transitioning the Dell Precision T5820 inference cluster from homogeneous dual-30B serving to a **Heterogeneous Dual-Worker Architecture (Topology B)**:
- **Worker 1 (GPU 0, PCI 0000:51:00.0)**: `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` (Lead Engineering Authority).
- **Worker 2 (GPU 1, PCI 0000:93:00.0)**: `Qwen/Qwen2.5-7B-Instruct-AWQ` (High-Throughput Bounded Specialist).

In accordance with Section 14, **this document is a readiness proposal and does NOT constitute execution or promotion**. Permanent deployment is strictly deferred to administrative scheduling.

---

## 2. Production Specification Matrix

```
========================================================================================================
DEPLOYMENT DIMENSION         WORKER 1 (LEAD ENGINE)                      WORKER 2 (SPECIALIST ENGINE)
========================================================================================================
Assigned Device              GPU 0 (Intel Arc Pro B65, 32GB)             GPU 1 (Intel Arc Pro B65, 32GB)
Physical PCI BDF             0000:51:00.0 (DRM /dev/dri/card1)           0000:93:00.0 (DRM /dev/dri/card2)
Level Zero Device Selector   level_zero:0,1                              level_zero:0,1
Level Zero Affinity Mask     ZE_AFFINITY_MASK=0                          ZE_AFFINITY_MASK=1
Local Serving Port           127.0.0.1:8000                              127.0.0.1:8001
Runtime Container            docker.io/vllm/vllm-openai-xpu@sha256:4b... docker.io/vllm/vllm-openai-xpu@sha256:4b...
Deployed Model Name          cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ   Qwen/Qwen2.5-7B-Instruct-AWQ
Model Pinned Revision        4bd30395b72ea6045edd04806c4fea448d4467b3   b25037543e9394b818fdfca67ab2a00ecc7dd641
Max Model Context            65,536 tokens                               32,768 tokens
Permitted Roles              Lead Architect, Coding, Integration         Test Specialist, Schema, SAST
Admission Policy             All work orders                             Task class & context <= 32K only
Fallback Target              Human Supervisor                            Worker 1 (Automated Failover)
========================================================================================================
```

---

## 3. Expected Operational Benefits & Empirical Gains

1. **Pipeline Latency Reduction**: Physical benchmarks demonstrate a **35.5% reduction in simultaneous multi-agent project execution time** (from 53.86s to 34.74s) under concurrent saturation.
2. **Specialist Decoding Speedup**: Specialist operations execute at **39.30 tokens/sec** (a **2.16x increase** over the 30B model's 18.22 tokens/sec).
3. **KV Cache Expansion**: Expands Worker 2 KV cache by **145.7%** (to 383,296 tokens), supporting up to 46 simultaneous 8K context streams.
4. **Thermal & Energy Efficiency**: Lowers GPU 1 active power draw by ~45W, reducing peak card temperature to 54°C.

---

## 4. Known Limitations & Containment Boundaries

1. **Context Boundary**: The 7B candidate cannot handle contexts $> 32,768$ tokens. Multi-file repository investigation must strictly route to Worker 1.
2. **Architectural Authority**: The 7B specialist lacks deep multi-repository reasoning capability and is disqualified from architectural decomposition or project acceptance.
3. **Advisory Deliverable Status**: Specialist outputs are advisory and must be accepted by out-of-process independent validators (`pytest`, AST analyzers, schema checkers) before integration.

---

## 5. Rollback Triggers & Automated Health Monitors

The cluster must automatically trigger failover or prompt administrative rollback if:
1. Worker 2 first-pass validator rejection rate exceeds **20%** over any 10-task window.
2. Worker 2 encounters $> 2$ consecutive unhandled level zero runtime faults or container restarts.
3. Production route `engineering/b0` latency increases by $> 15\%$ due to unexpected scheduling contention.
4. Independent validator catches an unauthorized tool execution or scope escalation attempt.

---

## 6. Administrative Sign-Off Requirements

To promote this proposal to live execution, the systems administrator must:
1. Review the operational runbook and proposal [`maint_prop_phase13_hetero_gpu1.md`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/proposals/maint_prop_phase13_hetero_gpu1.md).
2. Schedule a 15-minute maintenance window when active engineering campaigns are idle.
3. Issue explicit administrative execution command.
