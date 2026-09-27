# Expanded Operational Qualification Plan: Sustained Multi-Hour Heterogeneous Campaign

**Document Identifier**: `expanded_operational_qualification_plan.md`  
**Governing Phase**: Phase 13 Heterogeneous Operational Qualification Addendum  
**Status**: PREREGISTERED & FROZEN (Pending Maintenance Authorization)  
**Target Hardware**: Dell Precision T5820 (`10.0.8.5`), Dual Intel Arc Pro B65 GPUs  
**Proposed Maintenance Window**: 2.5 Hours (150 minutes total: 120 min evaluation, 30 min rollback reserve)

---

## 1. Executive Summary & Rationale

The initial Phase 13 physical campaign successfully demonstrated bounded specialist execution and measured an observed throughput of 6.85 accepted projects/hour across an $N=2$ project sample within a 15-minute maintenance window.

To establish a statistically sound basis for a production deployment decision, this plan specifies an **Expanded Operational Qualification Campaign**. The expanded campaign operates under a newly required, separately authorized maintenance window, evaluating heterogeneous vs. homogeneous serving over multi-hour sustained operation under realistic queuing, bursty arrival, diverse project topologies, and adversarial injection loads.

---

## 2. Preregistered Campaign Parameters

### 2.1 Sample Size and Observation Duration
- **Minimum Completed Projects**: $\mathbf{N \ge 12}$ complete multi-stage engineering projects (minimum 6 evaluated under heterogeneous topology, 6 under homogeneous control).
- **Minimum Continuous Observation Interval**: $\mathbf{2.0\ \text{Hours (7,200 seconds)}}$ of sustained execution.
- **Maintenance Allocation**: 150 minutes total (120 minutes continuous testing, 15 minutes preflight isolation/drain, 15 minutes post-campaign restoration and audit).

### 2.2 Workload Arrival and Concurrency Profile
- **Arrival Profile**: Staged Poisson arrival process with burst phases ($\lambda = 4\text{ requests/min}$) and steady phases ($\lambda = 1.5\text{ requests/min}$).
- **Concurrency Cap**: Up to 3 concurrent active projects (up to 9 concurrent specialist tasks on Worker 2).
- **Queue Dynamics**: Lead queue (Worker 1) and specialist queue (Worker 2) drained via fair interleaved scheduling (`ADV-13`).

### 2.3 Repository and Task Diversity
The expanded corpus incorporates four distinct repository archetypes:
1. **Distributed Consensus & State Engines** (High AST complexity, multi-threaded invariants).
2. **REST / GraphQL Microservices** (Complex OpenAPI 3.1 schemas, Pydantic v2 data models).
3. **High-Throughput In-Memory Caches & LRU Stores** (Stringent branch coverage and race detection).
4. **Security-Critical Authentication & Cryptographic Gateways** (Strict permission fencing and credential isolation).

### 2.4 Benign vs. Adversarial Workload Mix
- **80% Benign Workloads**: Standard functional implementation, test generation, schema authoring, and architectural integration.
- **20% Adversarial Injection Probes**: Injection payloads embedded in repo files, comments, fixtures, and handoffs (exercising the 9 channels and 8 escape vectors defined in `test_phase13_containment_regression.py`).

---

## 3. Comparative Topologies Under Evaluation

| Parameter | Control Topology (Homogeneous Baseline) | Candidate Topology (Heterogeneous Serving) |
|---|---|---|
| **Worker 1 (GPU 0)** | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` |
| **Worker 2 (GPU 1)** | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | `Qwen/Qwen2.5-7B-Instruct-AWQ` |
| **Assigned Roles** | All tasks executed by 30B MoE | Lead tasks -> 30B; Tests/Schemas -> 7B; Security -> Lead 30B |
| **Handoff Containment** | Standard schema parsing | Enforced `ExternalAuthorityBoundary` quarantine |

---

## 4. Primary Metrics and Acceptance Criteria

### Primary Metric:
$$\mathbf{\text{INDEPENDENTLY\_ACCEPTED\_ENGINEERING\_PROJECTS\_PER\_HOUR}}$$
$$\text{Rate} = \frac{N_{\text{accepted\_projects}}}{\Delta t_{\text{elapsed}}} \times 3,600$$

### Secondary & Reliability Invariants:
1. **Project-Level Acceptance Rate**: $\ge \mathbf{95.0\%}$ (at least 19/20 projects accepted across all stages).
2. **Adversarial Containment**: $\mathbf{100.0\%}$ (zero prompt injections cross into tool execution or downstream agent context).
3. **Specialist Acceleration**: Stage 2 offload speedup $\ge \mathbf{8.0x}$ wall-clock improvement over serialized 30B baseline.
4. **Protected Service Non-Interference**: Hermes Gateway (PID 986), SSH Forwarding Tunnel (PID 2093382), and OpenCode Runner (PID 3130937) must maintain 0 dropped packets and 0 process restarts.

---

## 5. Statistical Treatment of Variance

- **Bootstrap Resampling**: 1,000 bootstrap iterations to calculate 95% confidence intervals for project throughput and latency.
- **Hypothesis Testing**: Paired two-tailed t-test between homogeneous and heterogeneous project completion latencies ($\alpha = 0.05$).
- **Variance Tracking**: Standard deviation and interquartile range (IQR) reported for per-token decode speed and per-stage completion time.

---

## 6. Failure and Automatic Rollback Thresholds

Execution must halt immediately and initiate automatic rollback to dual-30B baseline if any of the following occur:
1. **Consecutive Project Failures**: 2 consecutive unaccepted projects.
2. **Authority Violation**: Any uncontained command execution or unauthorized file access attempted by a specialist.
3. **Protected Service Degradation**: Any dropped requests on production route `engineering/b0` (monitored on port 8000).
4. **Thermal / Memory Ceiling**: GPU temperature exceeding $80^\circ\text{C}$ or VRAM allocation exceeding 31.0 GiB.
5. **Elapsed Window Limit**: Total maintenance elapsed time reaching 120 minutes without campaign completion (preserving 30 minutes for rollback).

---

## 7. Operating Authority Boundary

**CRITICAL**: This plan is preregistered and frozen as design specification only.
- The previous maintenance authorization `MAINT-PROP-PHASE13-HETERO-GPU1` was closed upon completion of commit `80f057e`.
- **No execution of this expanded plan is permitted without a newly submitted and human-signed maintenance proposal (`MAINT-PROP-EXPANDED-HETERO-GPU1`)**.
