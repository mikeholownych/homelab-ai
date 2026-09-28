# Phase 13 Preregistration and Authorization Audit

## 1. Executive Summary & Purpose
This audit reconstructs the chronological progression of preregistered qualification requirements, maintenance authorizations, execution plans, and stopping rules for the Phase 13 Expanded Physical Campaign.

Its primary purpose is to resolve:
1. Whether the physical campaign satisfied the preregistered 2.5-hour observation requirement or an explicitly authorized, prospective amendment.
2. The exact operational meaning of the preregistered 2.5-hour requirement.
3. The validity of the stopping rule executed on physical hardware.

---

## 2. Chronological Reconstruction of the Qualification Contract

| Timestamp (UTC) | Source Document / Event | Invariant / Requirement Established | Governance Status |
| :--- | :--- | :--- | :--- |
| **2026-09-27T22:39Z** | Initial Phase 13 Release (`80f057e`) | Completed initial physical evaluation ($N=2$ projects, 1,050.39s, 6.85 proj/hr). Identified Task 12 adversarial compliance. Dual-30B restored. | Completed & Closed |
| **2026-09-27T22:52Z** | Phase 13 Addendum (`3870f59`) | Published [`expanded_operational_qualification_plan.md`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/evidence/expanded_operational_qualification_plan.md):<br>- $N \ge 12$ complete projects (6 control, 6 heterogeneous)<br>- Minimum continuous observation: 2.0 hours (7,200s)<br>- Maintenance allocation: 150 min (120 min evaluation, 30 min rollback)<br>- Staged Poisson arrival ($\lambda=4.0$ and $\lambda=1.5$ req/min)<br>- Max concurrency: 3 concurrent projects | Preregistered & Frozen Design Specification |
| **2026-09-27T23:02Z** | User Instruction 9 (Directive) | Authorized maintenance proposal `MAINT-PROP-EXPANDED-HETERO-GPU1` for Worker 2 (GPU 1) to execute the expanded qualification, investigate failures, and restore baseline. Explicitly noted: *"Do not treat this authorization as permission to make unrelated infrastructure changes... A separate deployment decision must be supported by final evidence."* | Authorized Scope Bound |
| **2026-09-27T23:06Z** | Execution Plan Formulation | Published [`phase13_expanded_campaign_execution_plan.md`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/evidence/phase13_expanded_campaign_execution_plan.md):<br>Defined "Authoritative 12-Project Protocol" across 4 repository archetypes. Offloaded Items 04 (Tests) and 05 (Schemas) to 7B, while pinning Item 06 (Security) to Lead 30B.<br>**Omission**: Did not schedule Poisson arrival or enforce the 2.0-hour duration timer. | Unamended Protocol Deviation |
| **2026-09-27T23:06Z - 23:27Z** | Live Control Execution | Executed `CTRL-01` through `CTRL-06` sequentially via `expanded_physical_runner.py control`. Elapsed time: 1,271.63s (~21.2 min). | Live Observation |
| **2026-09-28T02:13Z - 02:32Z** | Live Heterogeneous Execution | Executed `HETERO-01` through `HETERO-06` sequentially via `expanded_physical_runner.py heterogeneous`. Elapsed time: 1,137.87s (~19.0 min). | Live Observation |
| **2026-09-28T02:57Z** | Baseline Restoration & Audit | Restored Worker 2 to baseline dual-30B configuration. SHA-256 digest `641c9402...` verified exact match. | Fully Restored |

---

## 3. Analysis of the 2.5-Hour Preregistration Requirement

### 3.1 Original Meaning in `expanded_operational_qualification_plan.md`
The frozen plan distinguishes three distinct operational dimensions:
1. **Total Maintenance Allocation (150 minutes / 2.5 hours)**:
   - Defined in Section 1 and Section 2.1: `150 minutes total (120 minutes continuous testing, 15 minutes preflight isolation/drain, 15 minutes post-campaign restoration and audit)`.
   - Section 6, Rule 5: `Elapsed Window Limit: Total maintenance elapsed time reaching 120 minutes without campaign completion (preserving 30 minutes for rollback)`.
2. **Continuous Observation Interval (2.0 hours / 7,200 seconds)**:
   - Section 2.1 explicitly mandated: `Minimum Continuous Observation Interval: 2.0 Hours (7,200 seconds) of sustained execution`.
3. **Workload Dynamics**:
   - Section 2.2 explicitly mandated: `Staged Poisson arrival process with burst phases (lambda = 4 req/min) and steady phases (lambda = 1.5 req/min)` with up to 3 concurrent active projects.

### 3.2 What the Physical Campaign Actually Executed
- **Control Cohort**: 6 projects executed sequentially with zero wait states between projects. Elapsed wall-clock time was **1,271.63 seconds (~21.19 minutes)**.
- **Heterogeneous Cohort**: 6 projects executed sequentially with zero wait states between projects. Elapsed wall-clock time was **1,137.87 seconds (~18.96 minutes)**.
- **Combined Active Execution**: **2,409.50 seconds (~40.16 minutes)**.

### 3.3 Was There an Authorized Prospective Amendment?
- **Finding**: **NO**.
- There is no record in the repository, git history, or transcript of an authorized prospective amendment reducing the observation interval from 2.0 hours (7,200s) to ~20 minutes, or waiving the Poisson arrival process.
- The authoring agent substituted a fixed-cohort project completion script (`expanded_physical_runner.py`) that iterated over a static array of 6 projects and terminated as soon as the 6th project completed.
- The final report erroneously treated the completion of the 12 projects as full satisfaction of the expanded qualification requirements, overlooking the unfulfilled continuous observation interval requirement.

---

## 4. Stopping Rule and Throughput Metric Discrepancy

1. **Executed Stopping Rule**:
   - The actual stopping rule was **deterministic workload exhaustion** ($N = 6$ projects per cohort).
   - Once Project 06 completed, the runner calculated throughput as:
     $$\text{Throughput} = \frac{6}{\Delta t_{\text{completion}}} \times 3,600$$
2. **Throughput Denominator Meaning**:
   - The reported throughput of **16.99 projects/hr** (Control) and **18.98 projects/hr** (Heterogeneous) represents **back-to-back completed-workload throughput under zero-idle arrival**, NOT sustained queue throughput over a continuous 2.0-hour observation window.
   - It measures the maximum throughput of an idealized queue where the next project is admitted immediately upon completion of the previous one.

---

## 5. Preregistration Reconciliation Disposition

1. **Project Sample Size ($N \ge 12$)**: **SATISFIED**. 12 full multi-stage projects were executed and accepted on physical hardware (6 Control, 6 Heterogeneous).
2. **Four-Gate Independent Acceptance**: **SATISFIED**. All 12 projects were validated out of process.
3. **Continuous Multi-Hour Observation Interval ($\ge 2.0\text{ hours}$)**: **NOT SATISFIED**. The observed physical execution was ~21.2 min (Control) and ~19.0 min (Heterogeneous).
4. **Poisson Arrival & Inter-Project Concurrency**: **NOT SATISFIED**. Projects ran sequentially without Poisson arrival dynamics.

**Conclusion**: The reported campaign represents a valid, rigorous **12-project back-to-back completion benchmark**, but cannot be represented as a fulfilled 2.5-hour multi-project queueing qualification.
