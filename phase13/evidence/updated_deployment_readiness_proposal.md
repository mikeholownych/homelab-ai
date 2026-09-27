# Updated Deployment Readiness Proposal: Heterogeneous Serving Boundaries

**Document Identifier**: `updated_deployment_readiness_proposal.md`  
**Governing Phase**: Phase 13 Heterogeneous Operational Qualification Addendum  
**Proposal Status**: ADVISORY ONLY — NOT AUTHORIZED FOR PRODUCTION DEPLOYMENT  
**Target Hardware**: Dell Precision T5820 (`10.0.8.5`), Dual Intel Arc Pro B65 GPUs  
**Baseline Serving**: Dual-Resident `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` (GPU 0 & GPU 1)

---

## 1. Executive Summary & Policy Stance

Phase 13 demonstrated significant operational advantages for heterogeneous inference:
- **Decoding Acceleration**: Candidate model `Qwen/Qwen2.5-7B-Instruct-AWQ` achieved 39.27 tps average (a 2.17x decoding speedup over the 30B MoE control).
- **Stage 2 Latency Offload**: Concurrent specialist tasks reduced Stage 2 wall-clock time from ~148s to ~13.3s (an 11.2x acceleration).
- **Campaign Throughput**: 6.85 accepted projects/hour observed over an $N=2$ project sample.

However, forensic reconstruction of Task 12 established that **the 7B candidate complied textually with prompt injection in its weights**. Furthermore, an $N=2$ project sample does not constitute a statistically proven steady-state service rate.

Therefore, **permanent production deployment is NOT RECOMMENDED at this time**. Heterogeneous serving may only be admitted following execution of the Expanded Operational Qualification Campaign under strict role fencing.

---

## 2. Pinned Role Allocation Matrix

Under any future deployment, model roles must be strictly bifurcated based on empirical alignment capability:

| Engineering Role / Task Class | Permitted Model | Rationale & Empirical Justification |
|---|---|---|
| **ARCHITECTURAL_PLANNING** | **Lead 30B MoE Only** | Requires deep multi-step reasoning, repo-scale context, and authority. |
| **MULTI_FILE_IMPLEMENTATION** | **Lead 30B MoE Only** | High token budget and multi-file cross-referencing capabilities. |
| **PROJECT_INTEGRATION** | **Lead 30B MoE Only** | Sole authority permitted to assemble deliverables for release. |
| **PROJECT_ACCEPTANCE** | **Lead 30B MoE Only** | Independent gate evaluation requires maximum robustness. |
| **SECURITY_REVIEW / SAST** | **Lead 30B MoE Only** | **EXPLICITLY PROHIBITED FOR 7B**. Task 12 proved 7B complies with injections. |
| **ADVERSARIAL_SCOPE_CHECK** | **Lead 30B MoE Only** | **EXPLICITLY PROHIBITED FOR 7B**. Must refuse jailbreaks in weights. |
| **TEST_GENERATION** | **Qualified 7B Specialist** | Permitted. Generates pytest code executed in an isolated sandbox. |
| **STRUCTURED_OUTPUT** | **Qualified 7B Specialist** | Permitted. Emits JSON schemas validated by strict schema parsers. |

---

## 3. Strict Boundary and Quarantine Enforcement

1. **Advisory Deliverable Status**:
   All 7B specialist outputs are strictly advisory data. Specialist outputs cannot self-commit, self-approve, or directly trigger execution.
2. **Mandatory Out-of-Process Quarantine**:
   Every specialist deliverable must pass through `ExternalAuthorityBoundary.inspect_and_quarantine`. Deliverables containing injection patterns are dropped. Clean deliverables are wrapped in non-executable delimiter blocks (`<!-- BEGIN QUARANTINED SPECIALIST DELIVERABLE -->`) before handoff to Lead agents.
3. **Context Ceiling & Fail-Closed Fallback**:
   Specialist tasks are hard-capped at 32,768 tokens. Any request exceeding this limit is immediately diverted to Lead Worker 1 (`ADV-06`).
4. **Tool Authorization Hard-Fencing**:
   Specialists may only invoke read-only inspection tools (`read_file`, `run_pytest` in disposable sub-process, `inspect_ast`). Privileged tools (bash execution, docker manipulation, file writes) are blocked at the authority boundary (`ADV-07`).

---

## 4. Prerequisite Evidence Required for Deployment

Before any production deployment proposal can be approved by human engineering leadership, the following conditions must be satisfied:

1. **Expanded Operational Qualification Execution**:
   Completion of the preregistered 2.0-hour campaign ($N \ge 12$ projects) under a separately authorized maintenance window (`MAINT-PROP-EXPANDED-HETERO-GPU1`).
2. **Steady-State Throughput Verification**:
   Demonstration of $\ge 5.0$ independently accepted engineering projects per hour sustained under Poisson arrival and queue dynamics.
3. **Zero Uncontained Escapes**:
   100% containment pass rate across all adversarial injection probes during the expanded physical campaign.
4. **Hardware Reliability Audit**:
   Continuous operation with GPU temperature $< 75^\circ\text{C}$ and zero unrecoverable XPU driver fault resets.

---

## 5. Deployment Authorization Status

- **Candidate Promotion Status**: **UNAUTHORIZED**.
- **Cluster Operational State**: Pinned to baseline dual-resident `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`.
- **Maintenance Authorization**: The earlier maintenance authorization has been consumed and closed. No GPU reconfiguration is permitted.
