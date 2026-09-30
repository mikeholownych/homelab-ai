# Phase 14 Experiment 02: Final Corrected Qualification Disposition

- **Date:** 2026-09-29
- **Investigation ID:** `PHASE_14_EXP02_FORENSIC_RECONCILIATION`
- **Canonical Repository:** `mikeholownych/homelab-ai`
- **Canonical Remote Target:** `origin/main` (`a8c3b6a1a4c27f391f28ebdf5a74c1bfd1d148ce`)

---

## 1. Terminal Disposition Statement

```
================================================================================
PHASE_14_EXPERIMENT_02_RECONCILIATION: PROVEN_WITH_LIMITATIONS
================================================================================
```

---

## 2. Reconciled Technical Findings

The forensic investigation into the concurrent OpenCode workload during the Phase 14 Experiment 02 campaign has established the following empirically grounded conclusions:

1. **Unmodeled Concurrent Workload Fully Accounted For:**
   - Exactly **14 inference requests** (41,853 total tokens) from an autonomous OpenCode agent landed on the Dell Precision T5820 via the orchestrator gateway (port 8010) during the 1-hour campaign window.
   - 12 requests landed on Worker 1 (`b0-live-tp1-worker1`) and 2 requests landed on Worker 2 (`b0-live-tp1-worker2`).
2. **Complete Directional Asymmetry Identified:**
   - 100% of the concurrent OpenCode requests arrived during **Cohort 3 (Regime 2 Configuration B+)**, specifically overlapping Projects 5 and 6 between `06:19:19Z` and `06:26:17Z`.
   - Cohorts 1, 2, and 4 (including Configuration B under Regime 2) executed with **zero external interference**.
3. **Queue Wait & Tail Latency Attribution:**
   - The queue wait growth observed in Configuration B+ ($0.0\text{s}$ on Projects 1–4 jumping to $12.2\text{s}$ on Project 5 and $25.5\text{s}$ on Project 6) was directly driven by continuous batching compute-sharing with OpenCode, rather than inherent pipeline oversaturation.
   - For Projects 1–4, uncontended Worker 1 service demand averaged **164.80s** ($< 184.6\text{s}$ inter-arrival), yielding zero queue delay.
4. **Superior Throughput Preserved Despite Contention:**
   - Even while carrying the entirety of the concurrent background workload, Configuration B+ completed Regime 2 in **1214.10 seconds** (**17.79 proj/hr**), outperforming uncontended Configuration B (**1337.59 seconds**, **16.15 proj/hr**) by **+10.15%**.
5. **Architectural, Safety, and Quality Claims 100% Proven:**
   - Item 01 cryptographic handoff envelope and DAG integrity: **PROVEN** (16/16 verified).
   - Worker 1 lead authority over architecture, integration, and acceptance: **PROVEN**.
   - Dual-model security containment and adversarial isolation: **PROVEN** (4/4 blocked).
   - Independent 4-gate project acceptance: **PROVEN** (16/16 accepted).
   - Worker 1 service demand reduction: **PROVEN** (-14.4% in Regime 1, -15.4% in Regime 2).
6. **Operating Capacity Limits:**
   - While finite-cohort throughput is empirically higher under B+ (17.79 vs 16.15 proj/hr), steady-state queue stability at an offered rate of $\lambda = 19.5\text{ proj/hr}$ cannot be asserted as proven without qualification under open-world multi-tenant conditions.
   - Reconciled sustainable long-run capacity ceiling for Configuration B+ is bounded at **$\lambda \le 18.0\text{ projects/hour}$**.

---

## 3. Production Invariants and Next Steps

- **Production Configuration:** Production engineering pipeline retains **`SchedulingMode.CONFIGURATION_B`** as the default production scheduler.
- **Candidate Status:** Configuration B+ remains an experimental scheduling candidate.
- **Physical Model Allocation:** Dual homogeneous 30B MoE (`cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`) remains operational and invariant.
- **Rerun Requirement:** A physical rerun is deferred until an explicit workload-coordination or maintenance reservation window is authorized by the operator.
