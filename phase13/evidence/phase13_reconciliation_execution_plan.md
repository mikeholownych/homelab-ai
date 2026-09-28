# Phase 13 Reconciliation Execution Plan: Evidence, Timeline, and Statistical Audit

## 1. Governing Reference & Authority
- **Mission**: Evidence reconciliation, physical timeline reconstruction, independent metric recalculation, and qualification integrity audit for Phase 13 Expanded Physical Campaign.
- **Starting Release Baseline**: Commit [`fa65f04`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization) (`phase13-heterogeneous-qualification`).
- **Operating Bounds**:
  - Live protected serving (dual-resident 30B MoE on Dell Precision T5820) remains active, untouched, and undisturbed.
  - Zero model replacement or service interruption authorized.
  - Historical experimental traces remain strictly immutable; all findings and corrections are additive.
  - No retroactive dilution of preregistered criteria.

---

## 2. Workstream Breakdown & Deliverables Mapping

| Workstream | Scope & Methodology | Target Deliverable |
| :--- | :--- | :--- |
| **Workstream A** | **Preregistration & Authorization Reconciliation**<br>Chronological comparison of `expanded_operational_qualification_plan.md` (2.0-hr sustained interval, Poisson arrival, $N \ge 12$), user authorization `MAINT-PROP-EXPANDED-HETERO-GPU1`, and `phase13_expanded_campaign_execution_plan.md`. Audit of stopping rules. | [`phase13_preregistration_and_authorization_audit.md`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/evidence/phase13_preregistration_and_authorization_audit.md) |
| **Workstream B** | **Physical Timeline Reconstruction**<br>Reconstruction of exact wall-clock and monotonic timestamps for Control (1,271.63s), Candidate switch (~85s), Containment probes (~55s), Heterogeneous run (1,137.87s), and Restoration (~250s). Distinguish completed-project vs. fixed-window throughput. | [`phase13_physical_timeline_reconstruction.md`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/evidence/phase13_physical_timeline_reconstruction.md) |
| **Workstream C** | **Independent Metric Recalculation**<br>Recomputation of primary metric (projects/hr), Stage 2 latencies, decode TPS, token distributions, acceptance rates from raw JSON traces (`phase13_expanded_control_results.json`, `phase13_expanded_heterogeneous_results.json`). | [`phase13_independent_metric_recalculation.json`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/evidence/phase13_independent_metric_recalculation.json)<br>[`phase13_independent_metric_recalculation.md`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/evidence/phase13_independent_metric_recalculation.md) |
| **Workstream D** | **Statistical Validity Audit**<br>Audit of statistical units, pseudoreplication, paired vs. independent tests, Welch $t$-test assumptions, $p$-value inflation ($p < 10^{-15}$), and bootstrap resampling with $N=6$. | [`phase13_statistical_validity_audit.md`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/evidence/phase13_statistical_validity_audit.md) |
| **Workstream E** | **Experimental Configuration Reconciliation**<br>Disentangle performance attribution: 7B dense model vs. `max-num-seqs: 4` vs. parallel scheduling of Item 06 to Worker 1. Establish causal limits. | [`phase13_experimental_configuration_audit.md`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/evidence/phase13_experimental_configuration_audit.md) |
| **Workstream F** | **Acceptance & Security Evidence Audit**<br>Audit raw traces of 4-gate project acceptance across 12 projects; verify 10/10 physical containment probes, confirming zero tool escapes or downstream injections. | [`phase13_acceptance_and_security_evidence_audit.md`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/evidence/phase13_acceptance_and_security_evidence_audit.md) |
| **Workstream G** | **Qualification Gate Reassessment**<br>Reassess Gates G9, G10, G14, G18, A8, A9, A10, and EXP-01–EXP-10 against reconciled evidence. Formulate precise gate dispositions. | [`phase13_corrected_gate_reassessment.md`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/evidence/phase13_corrected_gate_reassessment.md) |
| **Workstream H** | **Deterministic Analysis Regression Tests**<br>Implement automated pytest suite covering 12 analytical edge cases: numerator/denominator scoping, window models, zero acceptance, pairing, bootstrap, and missing observations. | [`phase13_analysis_regression_report.md`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/evidence/phase13_analysis_regression_report.md)<br>`phase13/tests/test_phase13_metric_and_statistical_analysis.py` |
| **Workstream I** | **Corrected Deployment Decision Package & Final Report**<br>Separate established physical observations, supported operational conclusions, unresolved claims, and mandatory safeguards. Declare disposition. | [`phase13_corrected_deployment_decision_package.md`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/evidence/phase13_corrected_deployment_decision_package.md)<br>[`phase13_reconciliation_final_report.md`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/evidence/phase13_reconciliation_final_report.md) |

---

## 3. Milestones & Checkpoints
1. Freeze and hash current evidence inventory.
2. Complete chronological audit of preregistration, maintenance authorization, and stopping rules (Workstream A).
3. Reconstruct monotonic physical event timeline from raw traces and journal logs (Workstream B).
4. Build Python recomputation engine to verify all metrics independently (Workstream C).
5. Audit inferential statistics, degrees of freedom, and causal attribution (Workstreams D & E).
6. Verify raw acceptance and security probe telemetry (Workstream F).
7. Reassess all qualification gates and update dispositions (Workstream G).
8. Author and pass deterministic analysis regression tests across all 12 edge cases (Workstream H).
9. Deliver corrected deployment decision package, final reconciliation report, and update `manifest.sha256` (Workstream I).
