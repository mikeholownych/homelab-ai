# Phase 11 Qualification Reconciliation and Corrective Engineering Plan

## 1. Executive Summary & Reconciliation Objectives

Phase 11 established the initial implementation of the Evidence-Driven Model and Agent Optimization subsystem in commit [`47071c3`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization). While all 361 cumulative regression tests passed, an independent audit identified two material discrepancies in the qualification evidence:

1. **Hardware VRAM Capacity Discrepancy**: The hardware evaluator and qualification reports assumed an artificial 16.0 GB (16,384 MB) VRAM limit per Intel Arc Pro B65 GPU. Authoritative hardware interrogation on host `10.0.8.5` demonstrates that each physical Intel Arc Pro B65 card possesses **32,656.00 MiB (approximately 31.89 GiB)** of physical memory, with 31,023.20 MiB allocatable. Active vLLM workers currently allocate ~27.86 GiB per card (85% utilization).
2. **Gate G14 Evidence Provenance & Comparative Evaluation**: Gate G14 ("Real-Inference Comparative Campaign") was reported as passed with claims of a +10.4% token efficiency gain and +12.5% latency reduction. Investigation revealed that the automated gate test (`test_gate_g14_real_inference_comparative_campaign`) only executed an HTTP GET request to `/v1/models` (Level A: endpoint availability only), while the reported comparative deltas were synthetic mock cohort objects generated in demonstration script memory.

This reconciliation plan establishes the authoritative facts, traces the defect origins, defines corrective actions, executes a genuine real-inference comparative campaign against the protected control, and prepares an additive corrective release package while preserving all historical Phase 11 artifacts.

---

## 2. Disputed Claims & Evidence Sources

### Disputed Claim 1: Intel Arc Pro B65 VRAM Capacity is 16.0 GB
- **Original Claim**: Dual Intel Arc Pro B65 GPUs have 16.0 GB (16,384 MB) VRAM per device; resident model requires ~12.0 GB, leaving ~3.5 GB headroom.
- **Original Evidence Sources**:
  - [`phase11/src/autonomous_engineering/optimization/hardware_eval.py`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase11/src/autonomous_engineering/optimization/hardware_eval.py#L66) (`vram_per_card_mb: int = 16384`)
  - [`phase11/evidence/model_quantization_report.md`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase11/evidence/model_quantization_report.md#L13)
  - [`phase11/evidence/final_report.md`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase11/evidence/final_report.md#L63)
  - [`phase11/evidence/protected_service_audit.md`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase11/evidence/protected_service_audit.md#L32)
  - [`phase11/evidence/demo_execution.log`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase11/evidence/demo_execution.log#L24)
- **Authoritative Host Evidence**:
  - Live query to node `10.0.8.5` via `xpu-smi discovery -d 0,1`:
    - Device 0: `Intel(R) Arc(TM) Pro B65 Graphics`, PCI `0000:51:00.0`, `Memory Physical Size: 32656.00 MiB` (31.89 GiB), `Max Mem Alloc Size: 31023.20 MiB`.
    - Device 1: `Intel(R) Arc(TM) Pro B65 Graphics`, PCI `0000:93:00.0`, `Memory Physical Size: 32656.00 MiB` (31.89 GiB), `Max Mem Alloc Size: 31023.20 MiB`.
  - Active serving state: `vllm-xpu-tp1-worker1` (GPU 0) and `vllm-xpu-tp1-worker2` (GPU 1) currently allocate 27,869 MiB and 27,861 MiB (~27.2 GiB, 85% memory utilization) to serve `Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` with context window `max-model-len=65536`.
  - Repository baseline specification: [`docs/t5820-dual-worker-capacity-2026-09-25.md`](file:///home/mike/Projects/aihost/docs/t5820-dual-worker-capacity-2026-09-25.md#L18) stating "approximately 24.0 GiB of 31.89 GiB on one B65".
- **Defect Classification**: Implementation defect in default parameter specification (`vram_per_card_mb: int = 16384`) resulting from an unverified hardware assumption (confusing Battlemage workstation Pro B65 with consumer 16GB cards).

### Disputed Claim 2: Gate G14 Provenance and Comparative Deltas
- **Original Claim**: Gate G14 verified a real-inference comparative campaign proving a 10.4% token efficiency gain and a 12.5% latency reduction.
- **Original Evidence Sources**:
  - [`phase11/tests/test_phase11_preregistration_gates.py`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase11/tests/test_phase11_preregistration_gates.py#L197-L208)
  - [`phase11/evidence/comparative_qualification_report.md`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase11/evidence/comparative_qualification_report.md)
  - [`phase11/evidence/final_report.md`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase11/evidence/final_report.md)
  - [`phase11/run_demo.py`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase11/run_demo.py#L248-L265)
- **Authoritative Verification**:
  - Source code audit of `test_gate_g14_real_inference_comparative_campaign` shows it only issues a `GET http://127.0.0.1:18010/v1/models` request and checks HTTP status 200. This is **Level A evidence** (endpoint availability only).
  - Code audit of `run_demo.py` and `test_comparative_qualification.py` proves `r_ctrl_cohort` and `r_cand_cohort` were synthetic dataclasses instantiated with hardcoded values (1000 tokens vs 800 tokens, 1.0s vs 0.8s), not measured inference responses.
- **Defect Classification**: Evidence conflation and incomplete operational testing. Gate G14 was satisfied by a shallow connectivity probe instead of an actual matched comparative campaign.

---

## 3. Affected Implementation Modules and Test Suites

| Component / File | Nature of Defect / Change | Corrective Action |
| :--- | :--- | :--- |
| [`hardware_eval.py`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase11/src/autonomous_engineering/optimization/hardware_eval.py) | Hardcoded `vram_per_card_mb: int = 16384` | Update default to `32656` MiB (31.89 GiB physical capacity); add unit distinctions (binary MiB vs decimal MB); support host query. |
| [`evaluator.py`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase11/src/autonomous_engineering/optimization/evaluator.py) | Lacked physical endpoint execution path for live comparative evaluation | Add `evaluate_live_inference_task` that dispatches real chat completion requests to `http://127.0.0.1:18010/v1/chat/completions` with bearer authentication. |
| [`test_hardware_eval.py`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase11/tests/test_hardware_eval.py) | Tests asserted against 16,384 MB limit | Update baseline assertions to 32,656 MiB; retain explicit synthetic test fixtures for memory boundary regressions. |
| [`test_phase11_preregistration_gates.py`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase11/tests/test_phase11_preregistration_gates.py) | G6 used 16384 MB; G14 only did HTTP GET to `/v1/models` | Update G6 to 32656 MiB; update G14 to execute a genuine real-inference comparative task against `engineering/b0` via port 18010. |
| [`test_phase11_adversarial_security.py`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase11/tests/test_phase11_adversarial_security.py) | Test 10 tested model exceeding 16GB limit | Update test to use a model that exceeds 32GB (e.g. 70B FP16 at 140GB) to properly verify fail-closed VRAM protection. |

---

## 4. Reassessment of Affected Qualification Gates

| Gate | Original Requirement | Original Status | Identified Discrepancy | Reassessment Plan |
| :--- | :--- | :--- | :--- | :--- |
| **G4** | Independent candidate evaluation | PASSED | Real physical inference telemetry was simulated | Execute real inference on `engineering/b0` and record genuine token/latency telemetry. |
| **G5** | Comparative qualification | PASSED | Performance deltas (+10.4%, +12.5%) were synthetic mock fixtures | Execute matched paired comparison using real completion responses on calibration tasks. |
| **G6** | Hardware constraints & maintenance | PASSED | Assumed 16.0 GB VRAM limit instead of actual 32,656 MiB | Re-evaluate with 32,656 MiB (31.89 GiB) physical capacity and test swap gating. |
| **G8** | Context & reasoning efficiency | PASSED | Symbol reduction was synthetic text split calculation | Measure prompt token count and response tokens from live inference worker. |
| **G9** | Experiment scheduling & containment | PASSED | Scheduler logic valid; tested with synthetic concurrency | Verify concurrency slot containment against real worker calls. |
| **G14**| Real-inference comparative campaign | PASSED (Flawed) | Only tested `GET /v1/models` (Level A evidence) | **Execute genuine real-inference comparative campaign (Level D evidence)** on `engineering/b0`. |
| **G15**| Evidence custody & manifest | PASSED | Covered original reports only | Publish additive corrective manifest covering all reconciliation reports and raw traces. |

---

## 5. Protected-Service Constraints & Safety Boundaries

Throughout the reconciliation and comparative execution:
1. **Zero Interruptions to Protected Daemons**:
   - PID `986` (`hermes_cli`)
   - PID `3130937` (`opencode --auto`)
   - PID `2093382` (`ssh -N -T` tunnel forwarding `127.0.0.1:18010` to `10.0.8.5:8010`)
   - Strictly prohibited from receiving POSIX signals or being stopped/restarted.
2. **Resident Serving Configuration Invariant**:
   - The remote vLLM workers (`vllm-xpu-tp1-worker1` and `vllm-xpu-tp1-worker2`) serving `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` on `10.0.8.5` must NEVER be evicted, restarted, or reloaded.
3. **Inference Concurrency Control**:
   - Real-inference comparative evaluation must run with sequential concurrency ($N=1$) and modest token limits (`max_tokens <= 1024`) to ensure zero impact on host GPU memory or active background processes.

---

## 6. Execution Steps & Verification Sequence

1. **Step 1: Baseline Preservation & Branch Creation**:
   - Verify baseline commit `47071c3`.
   - Create corrective branch `phase11-qualification-reconciliation`.
   - Publish `phase11_reconciliation_plan.md` and `phase11_original_evidence_inventory.md`.
2. **Step 2: Authoritative Hardware Inventory (Workstream A)**:
   - Document host device parameters, PCI topology, xpu-smi outputs, and driver versions in `authoritative_hardware_inventory.md`.
   - Document root cause analysis of the 16.0 GB defect in `hardware_evaluator_root_cause.md`.
3. **Step 3: Corrective Implementation of Hardware Evaluator (Workstream B)**:
   - Update `hardware_eval.py` to default `32656` MiB.
   - Run hardware eligibility regression tests in `hardware_eligibility_regression.md`.
4. **Step 4: G14 Provenance & Real-Inference Comparative Campaign (Workstreams C, D, E)**:
   - Reconstruct original G14 evidence in `g14_evidence_provenance.md` and `comparative_results_reconciliation.md`.
   - Execute real-inference comparative campaign evaluating baseline control context vs optimized targeted symbol context against live `engineering/b0`.
   - Record raw request/response traces and performance deltas in `real_inference_comparative_results.md`.
5. **Step 5: Qualification Gate Reconciliation & Test Regressions (Workstreams F, G, H)**:
   - Reevaluate gates G4, G5, G6, G8, G9, G14, G15 in `qualification_gate_reconciliation.md`.
   - Verify protected host processes remain active in `protected_service_audit.md`.
   - Execute unit tests, adversarial security tests, and full 361-test cumulative regression suite.
6. **Step 6: Additive Corrective Release Package (Workstream I)**:
   - Produce all remaining reports (`corrective_implementation_report.md`, `operational_runbook_update.md`, `corrective_release_report.md`, `final_reconciliation_report.md`).
   - Generate `phase11/reconciliation/manifest.sha256` and verify with `sha256sum -c`.
   - Commit cleanly to `phase11-qualification-reconciliation`.
   - Issue the dual final dispositions:
     - Reconciliation Disposition: `PHASE_11_RECONCILIATION: COMPLETE`
     - Corrected Phase 11 Qualification Disposition: `PHASE_11_EVIDENCE_DRIVEN_OPTIMIZATION: PROVEN`
