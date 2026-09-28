# Phase 13 Expanded Campaign Execution Plan: Authoritative 12-Project Protocol

**Document Identifier**: `phase13_expanded_campaign_execution_plan.md`  
**Maintenance Reference**: `MAINT-PROP-EXPANDED-HETERO-GPU1`  
**Governing Phase**: Phase 13 Final Continuation  
**Execution Cluster**: Dell Precision T5820 (`10.0.8.5`), Dual Intel Arc Pro B65 GPUs  
**Status**: ACTIVE & AUTHORIZED

---

## 1. Executive Summary & Objective

In accordance with Section 1 and Section 3 of the Phase 13 Final Continuation instruction, this execution plan freezes the protocol for the Expanded Physical Qualification Campaign. The objective is to establish an authoritative, empirical comparison between:
1. **Homogeneous Baseline Control**: Dual-worker resident `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` (Worker 1 on GPU 0, Worker 2 on GPU 1).
2. **Heterogeneous Serving Candidate**: Bounded specialist `Qwen/Qwen2.5-7B-Instruct-AWQ` on Worker 2 (GPU 1) with Lead `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` on Worker 1 (GPU 0).

The primary metric governing qualification is:
$$\mathbf{\text{INDEPENDENTLY\_ACCEPTED\_ENGINEERING\_PROJECTS\_PER\_HOUR}}$$

---

## 2. Experimental Corpus & Workload Design

The expanded campaign executes **twelve complete multi-stage engineering projects** ($N=12$), with 6 projects evaluated under the homogeneous control baseline and 6 projects evaluated under the heterogeneous candidate configuration.

### 2.1 Repository Archetypes (4 Domains)
1. **Archetype 1: Distributed Consensus & State Machine Engine** (`PROJ-01`, `PROJ-02`)
   - Complex state transitions, election timeouts, race conditions, Raft log compaction.
2. **Archetype 2: REST / OpenAPI Microservices & Schema Contract** (`PROJ-03`, `PROJ-04`)
   - OpenAPI 3.1 specifications, Pydantic v2 validation models, zero-downtime database migrations.
3. **Archetype 3: High-Throughput In-Memory LRU Cache & Store** (`PROJ-05`)
   - High concurrency, lock-free memory eviction, branch-complete pytest suites.
4. **Archetype 4: Security-Critical Cryptographic Authentication Gateway** (`PROJ-06`)
   - Token rotation, HMAC signatures, permission boundaries, path-traversal fencing.

### 2.2 Eight-Item Dependency DAG per Project
Each project consists of 8 distinct work items structured into 3 execution stages:
- **Stage 1 (Lead / 30B MoE)**:
  - Item 01: Repository Architecture & Dependency Investigation
  - Item 02: Dependency DAG & Rollback Plan
  - Item 03: Core Service Refactoring & State Engine Implementation
- **Stage 2 (Specialist Offloads)**:
  - Item 04: Branch-Complete Unit & Regression Test Suite
  - Item 05: OpenAPI 3.1 Contract & JSON Delivery Manifest
  - Item 06: Static Application Security Testing (SAST) & Invariant Review
- **Stage 3 (Lead / 30B MoE)**:
  - Item 07: End-to-End Multi-Stage Integration & Build Manifest
  - Item 08: Independent Project Acceptance & Release Sign-Off

### 2.3 Strict Role Fencing (Post-Task-12 Addendum)
- In **Homogeneous Control**: All 8 items are executed by 30B MoE workers (Items 01-03, 07-08 on Worker 1; Items 04-06 on Worker 2).
- In **Heterogeneous Serving**:
  - Items 04 (Tests) and 05 (Schemas) are offloaded to `Qwen/Qwen2.5-7B-Instruct-AWQ` on Worker 2.
  - **Item 06 (Security Review)** is assigned to `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` on Worker 1, strictly enforcing the role prohibition established in `updated_deployment_readiness_proposal.md`.

---

## 3. Physical Containment & Boundary Verification Protocol

Before initiating multi-project sustained execution, the physical candidate on Worker 2 is subjected to direct adversarial injection probes:
1. **Task 12 Physical Replay**: Dispatched directly to candidate Worker 2 (`http://10.0.8.5:8001/v1/chat/completions`).
2. **Nine-Channel Adversarial Corpus**: Probing repository source files, code comments, test fixtures, tool responses, documentation, structured output schemas, handoff envelopes, generated tests, and SAST findings.
3. **External Authority Containment**: The `ExternalAuthorityBoundary` quarantine layer must intercept every compliant candidate response, flag it as `REJECTED`, and block downstream handoff.

---

## 4. Resource & Operating Constraints

- **Maintenance Scope**: Pinned strictly to Worker 2 on GPU 1 (PCI `0000:93:00.0`).
- **Worker 1 Protection**: Worker 1 on GPU 0 (PCI `0000:51:00.0`, port 8000) remains 100% active, serving production route `engineering/b0`.
- **Protected Daemons**: Hermes Gateway (PID 986), SSH tunnel (PID 2093382), OpenCode runner (PID 3130937) must maintain 100% uptime with 0 restarts.
- **Rollback Reserve**: 30 minutes reserved for post-campaign restoration of the dual-30B baseline.
