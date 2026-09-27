# Sustained Engineering Workload & Multi-Agent Project Design

## 1. Executive Summary & Design Principles

In conformance with Phase 13 Workstream E and Gate G7, this report presents the architecture of the sustained engineering qualification workload codified in [`sustained_workload.py`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/src/autonomous_engineering/heterogeneous/sustained_workload.py).

Single-pair synthetic benchmarks or isolated prompts cannot adequately capture real autonomous engineering dynamics. A sustained workload must reflect the full lifecycle of complex software development:
1. **Dependency-Aware Project DAGs**: Engineering operations are not isolated; downstream tests and security audits strictly depend on completed implementation modules.
2. **Specialist Concurrency**: Once core code is synthesized by the lead model, multiple specialist operations (unit test generation, OpenAPI schema generation, SAST review) can execute concurrently.
3. **Multi-Stage Integration & Independent Sign-Off**: Deliverables from both lead and specialist agents must be synthesized into a coherent patch and validated against project-level integration contracts before promotion.

---

## 2. Project Lifecycle DAG & Stage Breakdown

Each representative engineering project consists of 8 distinct work items across 4 macro-stages:

```
[ Stage 1: Investigation & Architecture ] (Lead Model: 30B, GPU 0)
    │
    ▼
[ Stage 2: Core Multi-File Implementation ] (Lead Model: 30B, GPU 0)
    │
    ├───► [ Test Specialist: Unit Test Generation ] (Specialist: 7B, GPU 1)
    │
    ├───► [ Schema Specialist: OpenAPI Contract ] (Specialist: 7B, GPU 1)
    │
    └───► [ Security Specialist: SAST Audit ] (Specialist: 7B, GPU 1)
    │        │         │         │
    ▼        ▼         ▼         ▼
[ Stage 4: Multi-Stage Integration & Acceptance ] (Lead Model: 30B, GPU 0)
```

### Stage Details:
- **Work Item 01 (Investigation)**: Deep AST and call-graph traversal across repository modules (18.5K tokens context). Assigned to Lead Model.
- **Work Item 02 (Planning)**: Architectural dependency DAG synthesis and rollback boundary definition (12.0K tokens). Assigned to Lead Model.
- **Work Item 03 (Implementation)**: Core code synthesis and multi-file refactoring (15.4K tokens). Assigned to Lead Model.
- **Work Item 04 (Test Generation)**: Branch-complete unit test synthesis covering normal, edge, and timeout cases (4.2K tokens). Offloaded to Specialist Model (or Lead in baseline).
- **Work Item 05 (Structured Output)**: Strict OpenAPI 3.1 specification and JSON delivery manifest (3.1K tokens). Offloaded to Specialist Model.
- **Work Item 06 (Security Review)**: SAST AST rule verification and credential/deserialization audits (3.8K tokens). Offloaded to Specialist Model.
- **Work Item 07 (Project Integration)**: End-to-end integration patch generation combining code, tests, and schemas (22.0K tokens). Assigned to Lead Model.
- **Work Item 08 (Project Acceptance)**: Independent validation of entire changeset under external test runner and human-supervisor mock.

---

## 3. Workload Concurrency & Topology Comparison

### Homogeneous Baseline Serving (Topology A: Dual 30B)
- Stage 3 specialist tasks (Items 04, 05, 06) must queue behind heavy implementation tasks or compete for 30B inference slots.
- Average decode throughput: ~18 tokens/sec.
- Serialized specialist execution or dual-worker queue contention.

### Heterogeneous Serving (Topology B: Lead 30B + Specialist 7B)
- Stage 3 specialist tasks immediately route to Worker 2 running `Qwen2.5-7B-AWQ`.
- Specialist decode throughput: ~39 tokens/sec (2.16x faster).
- Worker 1 remains free to proceed with subsequent project investigation and planning tasks.
- Eliminates queue bottlenecks on high-frequency testing and schema validation tasks.

---

## 4. Verification Standards

All project work items are governed by the independent validation infrastructure established in Phase 8–10. Project-level acceptance requires:
1. 100% test pass on all unit and integration test fixtures.
2. Zero syntax or AST parsing defects.
3. Zero schema validation errors on OpenAPI payloads.
4. Zero security or scope containment violations.
