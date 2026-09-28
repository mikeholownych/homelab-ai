# Phase 13 Corrected Qualification Gate Reassessment

## 1. Executive Summary & Reconciliation Mandate
This document formally reassesses every qualification gate affected by the evidence reconciliation, physical timeline reconstruction, and statistical validity audit of the Phase 13 Expanded Physical Campaign.

In accordance with Section 11 of the governing instruction:
- No gate is marked passed solely because an artifact file exists.
- The distinction between completed-workload benchmark throughput and multi-hour queue observation is strictly enforced.
- Statistical inferential claims are bounded to their defensible mathematical limits.

---

## 2. Comprehensive Gate Reassessment Matrix

| Gate ID | Original Requirement | Previously Reported Disposition | Reconciled Empirical Evidence | Corrected Gate Disposition | Remaining Limitation / Blocking Condition |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **G9 / EXP-06** | Physical Heterogeneous Campaign on authorized hardware | PASSED | Executed on Worker 2 (GPU 1) under `MAINT-PROP-EXPANDED-HETERO-GPU1`; 6 projects completed in 1,137.87s; 48 tasks accepted. | **PASSED WITH LIMITATIONS** | Limited to sequential project dispatch; multi-project Poisson arrival unobserved. |
| **G10 / A9** | Sustained Throughput Measurement | PASSED | Recomputed throughput is 16.99 proj/hr (Control) vs 18.98 proj/hr (Heterogeneous) over ~20 min completion intervals. | **PASSED WITH LIMITATIONS** | Measures completed-workload saturation throughput, NOT sustained 2.0-hour queue throughput. |
| **G11** | Project-Level Acceptance (4-gate validation) | PASSED | 12 / 12 projects passed all 4 independent gates (AST, pytest, SAST, Lead integration) verified from raw traces. | **PASSED** | None. Independent validation confirmed 100% rigorous. |
| **G13 / A11** | Protected Service Non-Interference | PASSED | Worker 1 uptime continuous (> 2 days); PIDs 986, 2093382, 3130937 untouched; dual-30B restored (hash `641c9402...`). | **PASSED** | None. Protected baseline completely intact. |
| **G14 / A8** | Adversarial Security & Containment | PASSED | Model complied in text with 9/10 injection prompts, but `ExternalAuthorityBoundary` rejected 10/10; 0 tool escapes. | **PASSED (SYSTEM LEVEL)** | 7B model has zero inherent prompt-injection resistance; safe ONLY under boundary quarantine. |
| **G18 / A14** | Production Promotion Separation | PASSED | Zero unauthorized promotion applied; cluster serving baseline dual-30B. | **PASSED** | Permanent deployment requires human authorization. |
| **A10** | Expanded Sustained Campaign Frozen Specification | PASSED | Frozen plan specified 2.0-hr continuous interval & Poisson arrival. Actual execution ran ~20 min fixed cohort. | **PARTIALLY FULFILLED** | $N=12$ project count met; continuous 2.0-hr duration and Poisson queueing unmet. |
| **EXP-01** | Authorized Maintenance Scope Compliance | PASSED | Maintenance strictly scoped to Worker 2 GPU 1; completed within authorized boundary. | **PASSED** | None. |
| **EXP-02** | Preflight Verification Checklist | PASSED | 9/9 preflight gates passed before candidate switch. | **PASSED** | None. |
| **EXP-03** | Physical Homogeneous Control Campaign | PASSED | 6 projects completed in 1,271.63s; 16.99 proj/hr. Stage 2: 57.05s. | **PASSED WITH LIMITATIONS** | Concurrency on Worker 2 was restricted to `max-num-seqs: 2`. |
| **EXP-05** | Live Physical Containment Probing | PASSED | 10/10 live probes quarantined; 0 tool executions; 0 side effects. | **PASSED** | Candidate strictly prohibited from authoritative roles. |
| **EXP-07** | Immediate Rollback & Restoration | PASSED | Worker 2 restored to 30B MoE; SHA-256 `641c9402...` verified. | **PASSED** | None. Rollback complete. |
| **EXP-08** | Protected Daemon Continuity | PASSED | PIDs 986, 2093382, 3130937 maintained 100% uptime with 0 restarts. | **PASSED** | None. |
| **EXP-09** | Statistical Comparative Analysis | PASSED | Recomputed paired $t = 115.08$ ($df=5$). Corrected erroneous variance ($0.415$ vs $0.126$) and misstated $p < 0.001$ non-inferiority. | **CORRECTED / PASSED WITH LIMITATIONS** | Valid for the 6 tested benchmark fixtures; cannot infer $p < 10^{-15}$ across arbitrary repositories. |
| **EXP-10** | Deployment Decision Package | PASSED | Qualified for conditional deployment with strict fencing. | **REVISED WITH LIMITATIONS** | Requires prospective multi-hour queueing evaluation or explicit waiver before permanent production promotion. |

---

## 3. Detailed Audit of Specific Gate Discrepancies

### 3.1 Gate A10 (Preregistered Duration Requirement)
- **Requirement**: `Minimum Continuous Observation Interval: 2.0 Hours (7,200 seconds) of sustained execution`.
- **Actual Telemetry**: Control elapsed = 1,271.63s (~21.2 min); Heterogeneous elapsed = 1,137.87s (~19.0 min).
- **Finding**: The campaign terminated upon exhausting the 6-project cohort rather than observing sustained operation across the preregistered 2.0-hour window.
- **Disposition**: **PARTIALLY FULFILLED**. The project count requirement ($N \ge 12$) was satisfied, but the continuous observation duration was not met.

### 3.2 Gate EXP-09 (Statistical Methodology)
- **Reported**: Welch $t = 93.42$, $p < 10^{-15}$, Bootstrap CI `[1.112x, 1.123x]`, Non-inferiority $p < 0.001$.
- **Finding**:
  1. Arithmetic error in control sample variance ($s_1^2 = 0.4150$, not $0.126$). Correct Welch $t = 68.92$.
  2. Because identical fixtures were run at `temperature = 0.0`, the design is paired ($df = 5, t_{\text{paired}} = 115.08$).
  3. Non-inferiority claim ($p < 0.001$) was ungrounded; exact 95% Clopper-Pearson lower bound for 6/6 is 54.07%.
- **Disposition**: **CORRECTED / PASSED WITH LIMITATIONS**.

---

## 4. Reconciled Overall Terminal Disposition

Because all safety, containment, and baseline-restoration gates passed, but the continuous 2.0-hour observation requirement was not met and performance attribution is composite rather than isolated, the reconciled terminal disposition is:

$$\mathbf{PHASE\_13\_EVIDENCE\_RECONCILIATION:\ PROVEN\_WITH\_LIMITATIONS}$$
