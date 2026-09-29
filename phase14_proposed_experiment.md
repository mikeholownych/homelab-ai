# Phase 14 Proposed Experiment: Homogeneous Pipeline Rebalancing (Configuration B+)

- **Date:** 2026-09-29
- **Author:** Autonomous Engineering System
- **Status:** Proposal Ready for Human Authorization
- **Mission Identifier:** `PHASE_14_EXPERIMENT_01_PIPELINE_REBALANCING`
- **Experimental Candidate:** Configuration B+ (Homogeneous Dual-30B with Item 01 Investigation Offloaded to Worker 2)
- **Baseline Control:** Configuration B (Production Homogeneous Dual-30B Default)

---

## 1. Problem Statement & Background

In the qualified Phase 13 production baseline (**Configuration B**), Worker 1 is occupied for $189.7\text{ s}$ out of $196.2\text{ s}$ per project ($96.7\%$ occupancy, $100\%$ critical-path governing), while Worker 2 is active for only $40.9\text{ s}$ ($79.2\%$ idle time).

Both workers are equipped with identical 30B MoE models (`cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`) on dedicated Intel Arc Pro B65 GPUs. However, Worker 2 is currently restricted to executing only Stage 2 advisory tasks (Items 04 Unit Tests and 05 Schema Generation) because of historical containment rules derived from the experimental 7B candidate.

During Stage 1, while Worker 1 sequentially executes Item 01 (Investigation, $28.25\text{ s}$), Item 02 (Planning, $28.18\text{ s}$), and Item 03 (Core Implementation, $42.10\text{ s}$), Worker 2 sits **100% IDLE for 98.53 seconds**.

---

## 2. Hypothesis

**Hypothesis $H_1$**:
> Dispatching Item 01 (Codebase Investigation and Reconnaissance) to Worker 2 under homogeneous 30B serving:
> 1. Will reduce Worker 1 critical-path service demand from $189.7\text{ s}$ to $\le 162.0\text{ s}$ ($-14.6\%$).
> 2. Will reduce end-to-end project turnaround time from $196.24\text{ s}$ to $\le 168.0\text{ s}$ ($-14.4\%$, saving $\ge 25.0\text{ s}$ per project).
> 3. Will increase independently accepted project throughput from $18.34$ to $\ge 21.5$ projects/hour ($+17.2\%$).
> 4. Will maintain $100\%$ independent project acceptance and $100\%$ security containment with zero capability degradation.

---

## 3. Experimental Design & Controlled Comparison

### Control Arm (Configuration B - Production Baseline):
- **Stage 1 (Serial W1)**: Worker 1 executes Item 01 ($28.25\text{ s}$), Item 02 ($28.18\text{ s}$), Item 03 ($42.10\text{ s}$). Worker 2 is idle.
- **Stage 2 (Parallel Barrier)**: Worker 2 executes Items 04 and 05 ($40.88\text{ s}$); Worker 1 executes Item 06 ($41.51\text{ s}$).
- **Stage 3 (Serial W1)**: Worker 1 executes Item 07 ($28.17\text{ s}$), Item 08 ($28.11\text{ s}$). Worker 2 is idle.

### Candidate Arm (Configuration B+ - Rebalanced Homogeneous Pipeline):
- **Stage 1 (Concurrent Investigation & Planning)**:
  - Worker 2 executes Item 01 (Investigation: AST analysis, file tree mapping, dependency discovery) in $28.25\text{ s}$.
  - Worker 2's deliverable is quarantined, validated, and passed to Worker 1.
  - Worker 1 executes Item 02 (Planning, $28.18\text{ s}$) and Item 03 (Core Implementation, $42.10\text{ s}$).
  - Worker 1 Stage 1 duration drops from $98.53\text{ s}$ to $70.28\text{ s}$ ($-28.25\text{ s}$, **$-28.7\%$**).
- **Stage 2 (Parallel Barrier)**: Identical to Configuration B (Items 04 & 05 on Worker 2, Item 06 on Worker 1).
- **Stage 3 (Serial W1)**: Identical to Configuration B (Items 07 & 08 on Worker 1).

---

## 4. Workload, Metrics, and Acceptance Criteria

### Workload & Sample Size:
- **Workload**: 12 total physical project executions across the 6 standard engineering archetypes:
  1. API Refactoring & Validation (`proj-api-01`)
  2. Security Vulnerability Remediation (`proj-sec-02`)
  3. Structured Schema Contract Migration (`proj-schema-03`)
  4. Async Worker Queue Optimization (`proj-worker-04`)
  5. Multi-Tenant Database Migration (`proj-db-05`)
  6. Observability Gateway Pipeline (`proj-obs-06`)
- **Sample Distribution**: 6 projects on Configuration B, 6 projects on Configuration B+.

### Outcome Metrics:
- **Primary Metric**: Independently Accepted Projects per Hour.
- **Secondary Metrics**:
  - Worker 1 Service Demand ($T_{W1}$).
  - Worker 2 Idle Ratio ($I_{W2} = t_{\text{idle}} / t_{\text{total}}$).
  - Stage 1 Latency ($T_{\text{Stage 1}}$).
  - First-Pass Acceptance Rate ($A_{\text{first}}$).
  - Security Containment Violation Count ($V_{\text{sec}}$).

### Acceptance Criteria:
1. **Deterministic Acceptance**: $6/6$ ($100\%$) projects in Configuration B+ pass all independent acceptance tests (syntax, lint, unit tests, integration tests, and schema validation).
2. **Security Invariant**: Zero security rejections, zero threat escapes, and 100% quarantine enclosure on Item 01 deliverables.
3. **Statistical Significance**: A paired t-test or Wilcoxon signed-rank test on project turnaround latency yielding $p < 0.05$ with an observed effect size $\Delta \ge 20.0\text{ seconds}$ reduction per project.

---

## 5. Safety, Authority, and Containment Invariants

1. **Non-Authoritative Investigation Role**:
   - Item 01 deliverables are strictly read-only advisory summaries.
   - Worker 2 has no tool execution privileges, no write access to repository files, and no authority to modify project requirements.
2. **External Authority Boundary Enforcement**:
   - Item 01 outputs are quarantined by `ExternalAuthorityBoundary` and wrapped in delimiters:
     `<!-- BEGIN QUARANTINED SPECIALIST DELIVERABLE [Item 01] -->`
   - Scanned against all 8 pinned threat vectors (`ADVERSARIAL_PATTERNS`).
3. **Lead Authority Preservation**:
   - Worker 1 remains the authoritative lead. Worker 1 reviews Item 01 advisory content, generates Item 02 plan, implements Item 03, performs Item 06 security review, integrates Item 07, and grants Item 08 acceptance.

---

## 6. Operational Execution & Rollback Plan

- **Hardware & Container Impact**: **ZERO**. Both 30B models remain loaded on GPU 0 and GPU 1. No container restarts, no driver reloads, no weights re-flashing.
- **Implementation Scope**:
  - Add `SchedulingMode.CONFIGURATION_B_PLUS` to `phase13/.../capability_scheduler.py`.
  - Authorize `TaskClass.INVESTIGATION` on Worker 2 under Configuration B+ in `validate_worker_authority`.
- **Rollback Procedure**:
  - If any anomaly, acceptance failure, or containment alert triggers:
    ```python
    scheduler.scheduling_mode = SchedulingMode.CONFIGURATION_B
    ```
  - MTTR: $< 2$ seconds. Full return to proven Configuration B production default.

---

## 7. Explicit Stop Conditions

The campaign must halt immediately, revert to Configuration B, and notify human authority if:
1. Any project acceptance check fails in Configuration B+.
2. Any threat vector pattern is detected in Item 01 output.
3. Worker 1 or Worker 2 VRAM usage exceeds $28.5\text{ GiB}$ or triggers a CUDA/XPU out-of-memory error.
4. GPU junction temperature exceeds $85^\circ\text{C}$ on either Intel Arc Pro B65 card.
5. Any protected daemon (PID 986, 2093382, 1269920) is interrupted.
