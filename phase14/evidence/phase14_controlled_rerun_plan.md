# Phase 14 Experiment 02: Controlled Rerun Plan and Feasibility Assessment

- **Date:** 2026-09-29
- **Scope:** Predeclared execution protocol, isolation criteria, and execution feasibility decision for candidate physical requalification.

---

## 1. Controlled Rerun Specification

If physical requalification is authorized, the rerun must adhere to the following predeclared protocol:

### A. Operating Conditions (Mutually Exclusive Options)
1. **Option A: Exclusive Experimental Access (Recommended)**
   - Pre-condition: An explicit maintenance reservation window is established on `10.0.8.5`.
   - All external clients (including OpenCode agents) are coordinated to withhold requests during the measurement window.
   - Zero-traffic invariant: Verification of 0 external requests in `aihost-vllm-worker1.service` and `aihost-vllm-worker2.service` journalctl logs across the entire campaign.
2. **Option B: Controlled Concurrent Background Load**
   - Pre-condition: A synthetic, deterministic background stream of requests (matching OpenCode prompt lengths: ~2,800 prompt tokens, ~150 completion tokens) is applied with exact mathematical symmetry to **both** Configuration B and Configuration B+ cohorts.
   - Background arrival rate: Exactly 1 request every 60 seconds dispatched via the port 8010 gateway.

### B. Workload Corpus and Arrival Schedule
- **Corpus:** 6 projects per arm matching the standardized archetypes (API Refactoring, Security Infrastructure, Schema Refactoring, Worker Engine, Database Schema, Observability Contract).
- **Arrival Regimes:**
  - **Regime 1:** $\lambda = 12.0\text{ proj/hr}$ ($T_{\text{arr}} = 300\text{s}$), 2 projects per arm.
  - **Regime 2:** $\lambda = 18.0\text{ proj/hr}$ ($T_{\text{arr}} = 200\text{s}$) — Evaluates sustainable queue stability.
  - **Regime 3:** $\lambda = 19.5\text{ proj/hr}$ ($T_{\text{arr}} = 184.6\text{s}$) — Evaluates capacity boundary stress.
- **Run Order:** Alternating sequence (B $\rightarrow$ B+ $\rightarrow$ B $\rightarrow$ B+) with 120-second drain intervals between cohorts to prevent thermal and queue carryover.

### C. Safety and Termination Gates
- **Queue Wait Threshold:** If any project experiences queue wait $> 300\text{ seconds}$, the cohort automatically aborts.
- **Error Limit:** 0 HTTP 5xx errors permitted; zero uncontained adversarial outputs.
- **Rollback Verification:** Immediate automated rollback to `SchedulingMode.CONFIGURATION_B` upon campaign conclusion.

---

## 2. Rerun Feasibility and Execution Decision

In accordance with Section 1 and Section 11 of the Human Authorization:
> *"Do not begin a physical rerun until its isolation conditions and execution plan are verified. A non-disruptive rerun may proceed under this authorization only if it can be isolated from all other T5820 workloads without interrupting them. Otherwise, stop and request an explicit maintenance or workload-coordination authorization."*
> *"A verbal agreement that another agent will remain idle is insufficient without request-log verification. Do not interrupt or terminate the other agent's active work without authorization."*

### Current Physical Operating State:
1. The Dell Precision T5820 gateway (`aihost-orchestrator-gateway.service`) is currently active and configured with `opencode-client-token`.
2. There is no automated hardware-level reservation token or mutual exclusion semaphore that can guarantee that external agents will not submit requests during an autonomous run without reconfiguring or interrupting the gateway service.
3. Terminating or blocking external agents is strictly forbidden by human instructions without separate authorization.

### Execution Decision:
**A PHYSICAL RERUN IS NOT EXECUTED IN THIS TURN.**

The investigation halts physical execution and reports the reconciled findings under the authorized disposition:
`PHASE_14_EXPERIMENT_02_RECONCILIATION: PROVEN_WITH_LIMITATIONS`.

To execute a physical rerun, the operator should authorize an explicit workload-coordination maintenance window or instruct the system to proceed during a scheduled off-peak interval with verified exclusive access.
