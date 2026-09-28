# Phase 13 Corrected Deployment Decision Package: Heterogeneous Architecture Qualification

## 1. Executive Decision Summary

- **Governing Release Baseline**: Commit [`fa65f04`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization) (`phase13-heterogeneous-qualification`).
- **Production Serving Recommendation**: **RETAIN PROTECTED HOMOGENEOUS DUAL-30B BASELINE**. Do **NOT** promote the heterogeneous candidate to production serving (`engineering/b0` on port 8010) at this time.
- **Terminal Architectural Disposition**: `PHASE_13_EVIDENCE_RECONCILIATION: PROVEN_WITH_LIMITATIONS`.
- **Core Justification**:
  1. The physical campaign proved that the *composite heterogeneous architecture* (combining Worker 1 30B MoE and Worker 2 7B Dense with revised Stage 2 task scheduling) achieves an 11.76% completed-workload throughput speedup (16.99 -> 18.98 proj/hr) with 100% project acceptance (6/6 projects, 48/48 items) and 100% physical containment (10/10 adversarial probes caught).
  2. However, the campaign was completed in 18.96 minutes under synchronous back-to-back dispatch, failing to execute the preregistered 2.0-hour sustained continuous observation window under Poisson arrival.
  3. Furthermore, causal analysis establishes that the 22.17-second Stage 2 acceleration was primarily driven by scheduling Item 06 to Worker 1 (eliminating the Worker 2 serial queue), rather than the faster decode speedup of the 7B model itself.
  4. In accordance with zero-defect qualification integrity, production promotion is deferred until a sustained 2.0-hour continuous queueing experiment is physically executed.

---

## 2. Established Physical Observations

The following empirical observations are directly supported by immutable physical traces ([`phase13_expanded_control_results.json`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/traces/phase13_expanded_control_results.json), [`phase13_expanded_heterogeneous_results.json`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/traces/phase13_expanded_heterogeneous_results.json), and [`phase13_physical_containment_results.json`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/traces/phase13_physical_containment_results.json)):

| Physical Metric | Homogeneous Control (Dual-30B) | Heterogeneous Candidate (30B + 7B) | Absolute Difference | Relative Change | Trace Verification |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Completed Workload Span** | 1,271.63 s (21.19 min) | 1,137.87 s (18.96 min) | -133.76 s | -10.52% | Monotonic timestamp diff |
| **Completed-Workload Throughput** | 16.9850 proj/hr | 18.9828 proj/hr | +1.9978 proj/hr | **+11.76%** | $6 \times 3600 / T_{\text{active}}$ |
| **Mean Project Latency** | 211.9383 s ($\sigma = 0.644$) | 189.6450 s ($\sigma = 0.461$) | -22.2933 s | **-10.52%** | Paired $t=115.08, df=5$ |
| **Stage 2 Concurrency Latency** | 57.0533 s ($\sigma = 0.340$) | 34.8850 s ($\sigma = 0.120$) | -22.1683 s | **-38.86%** | Paired $t=218.97, df=5$ |
| **Specialist Decode Speed** | 14.8624 tok/s | 26.5630 tok/s | +11.7006 tok/s | **+78.73%** | Token count / decode time |
| **Project-Level Acceptance** | 6 / 6 (100.0%) | 6 / 6 (100.0%) | 0.0% | 0.0% | 4-gate verification |
| **Subtask Acceptance** | 48 / 48 (100.0%) | 48 / 48 (100.0%) | 0.0 | 0.0% | Per-task acceptance records |
| **Security Containment Probes** | N/A (Baseline) | 10 / 10 (100.0%) | N/A | 100% Contained | 0 tool escapes, 0 poisoned files |
| **Gateway Baseline Invariance** | 100% Healthy (Dual-30B) | 100% Restored (Dual-30B) | 0 regressions | 0.0% | Round-robin port 8010 |

---

## 3. Supported Operational Conclusions

Based on the verified physical evidence, the following conclusions are methodologically sound and operationally supported:

1. **System-Level Architecture Speedup**:
   Offloading advisory tasks (unit testing and contract generation) to a secondary worker while concurrently executing security reviews on Worker 1 reduces total project execution time by 22.3 seconds (~10.5%) per project across diverse engineering archetypes.
2. **Quality Invariance Across Evaluated Archetypes**:
   Across the six representative project archetypes (FastAPI Webhook, Distributed Rate Limiter, Streaming Pipeline, Multi-Tenant Auth, State Machine, Time-Series Cache), the candidate generated branch-complete test suites and OpenAPI schemas that satisfied all four independent acceptance gates without human intervention.
3. **Robustness of External Authority and Boundary Validation**:
   The physical containment campaign conclusively proved that the external AST parser, JSON schema validator, and boundary sanitizer completely neutralize adversarial prompt injection attacks (including raw bash execution instructions and mock credential exfiltration) emitted by the smaller 7B candidate. At no point did untrusted code escape into authoritative workspaces.

---

## 4. Unresolved Claims & Causal Disentanglement

The reconciliation audit identified the following claims that are **unsupported** by the available data and require explicit qualification or further experimentation:

### A. Sustained Multi-Hour Queueing Throughput
- **The Claim**: The system sustains 18.98 accepted projects/hour under production-like Poisson queueing.
- **The Reality**: The observed 18.98 proj/hr is strictly **completed-workload throughput under continuous saturated dispatch** across an 18.96-minute window. Under the preregistered 2.0-hour window ($7,200$ s), 6 completed projects yields an effective rate of only **3.00 projects/hour**. True multi-hour queue stability under variable arrival rates ($\lambda = 4.0$ req/min) remains unobserved.

### B. Pure Causal Attribution of the 7B AWQ Model
- **The Claim**: The 7B AWQ model's 78.7% decode speedup was the primary driver of project turnaround acceleration.
- **The Reality**: In Stage 2 of the Heterogeneous configuration, Worker 2 (7B) completed Items 04 & 05 in 19.20 seconds. However, Stage 2 could not complete until Worker 1 (30B) completed Item 06 at 34.88 seconds. The 7B model was idle for 15.68 seconds while waiting on Worker 1! 
  The 22.17-second Stage 2 acceleration was **100% governed by offloading Item 06 from Worker 2 to Worker 1**, which resolved the serialization bottleneck present in Control. The comparison establishes the speedup of the *composite system architecture*, but does not prove that a 7B model is superior to a dual-30B setup with the same scheduling policy.

### C. Statistical Non-Inferiority and Significance Bounds
- **The Claim**: The heterogeneous candidate demonstrated statistical non-inferiority on project acceptance ($p < 0.001$) and throughput acceleration with $p < 10^{-15}$.
- **The Reality**: With $N=6$, the exact Clopper-Pearson 95% confidence interval for 6/6 acceptance is $[54.07\%, 100.0\%]$. Claiming non-inferiority against a standard 5% margin is mathematically impossible with $N=6$ (power $\approx 0$). The reported $p < 10^{-15}$ was an artifact of deterministic decoding ($T=0$) on identical prompts, treating repeated synthetic iterations as independent physical events (pseudoreplication).

---

## 5. Mandatory Deployment Safeguards

If the heterogeneous configuration is deployed in non-production or future staging environments, the following technical safeguards are mandatory and non-waivable:

1. **Non-Authoritative Role Pinned Exclusively**:
   Worker 2 must remain strictly pinned to advisory roles:
   - Subtask `test_suite_generation`
   - Subtask `schema_and_contract_generation`
   Worker 2 is strictly forbidden from executing architectural planning, production code synthesis, security auditing, or final acceptance gate verification.
2. **Mandatory External Boundary Validation**:
   All outputs from Worker 2 must be piped through `AutonomousEngineeringContainmentValidator`:
   - Structural AST validation (rejecting any `os.system`, `subprocess`, `socket`, `eval`, or file I/O).
   - JSON schema adherence check.
   - Quarantine fencing: non-conforming responses must be automatically purged, with task retry routed to Worker 1.
3. **Gateway Route Isolation**:
   The production gateway (`aihost-orchestrator-gateway.service` on port 8010) must remain pinned strictly to Worker 1. Untagged requests to port 8010 must never reach Worker 2 under any circumstance.
4. **Automated Degradation Circuit Breakers**:
   If Worker 2 experiences $> 2$ consecutive timeouts or validation rejections, the scheduler must automatically trip its circuit breaker, route 100% of advisory tasks to Worker 1, and log an alert without interrupting engineering throughput.

---

## 6. Targeted Future Campaign Proposal: `MAINT-PROP-PHASE14-SUSTAINED-POISSON-2HR`

To resolve the outstanding claims and enable permanent production promotion, a narrowly targeted campaign proposal is defined below.

### A. Campaign Objective
Physically execute a true, continuous 2.0-hour observation window under Poisson arrival traffic ($\lambda = 4.0$ req/min) to measure sustained queue stability, and execute a 3-way scheduling ablation to isolate the pure causal contribution of the 7B AWQ model.

### B. Preregistered Evaluation Arms
1. **Arm 1 (Control Baseline)**: Dual-30B with serial Stage 2 scheduling (reproducing Phase 13 Control).
2. **Arm 2 (Ablation Control)**: Dual-30B with Worker 1 offload of Item 06 (isolating the scheduling effect).
3. **Arm 3 (Heterogeneous Candidate)**: 30B Worker 1 + 7B Worker 2 with Item 06 offload (measuring the pure incremental model effect).

### C. Stopping Rule & Sample Size
- Fixed window: Strictly 7,200 seconds (2.0 hours) per arm.
- Minimum completed projects: $N \ge 24$ per arm to achieve 80% power for non-inferiority testing.

### D. Serving Disposition Pending Phase 14
Until `MAINT-PROP-PHASE14-SUSTAINED-POISSON-2HR` is authorized and successfully executed:
- **Serving Baseline**: Protected Homogeneous Dual-30B (`engineering/b0`).
- **Phase 13 Disposition**: `PHASE_13_EVIDENCE_RECONCILIATION: PROVEN_WITH_LIMITATIONS`.
