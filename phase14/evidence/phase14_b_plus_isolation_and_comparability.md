# Phase 14 Experiment 02: Configuration B+ Requalification Isolation and Comparability

- **Date:** 2026-09-29
- **Campaign Window (UTC):** `2026-09-29T07:40:03.768Z` to `2026-09-29T08:18:08.600Z`
- **Total Physical Duration:** $2,284.83\text{ seconds}$ ($38.08\text{ minutes}$)
- **Runner Script:** [`phase14/src/autonomous_engineering/pipeline_rebalancing/b_plus_requalification_runner.py`](file:///home/mike/Projects/aihost/phase14/src/autonomous_engineering/pipeline_rebalancing/b_plus_requalification_runner.py)

---

## 1. Workload Isolation Audit and Cursor Accounting

To guarantee and prove physical workload isolation, request-level journal cursor tracking was executed against the containerized vLLM services on the Dell Precision T5820 (`10.0.8.5`):

### A. Preflight Engine State
- **Worker 1 Cursor:** `s=238b81e3b0d944cf9bedada85a9a43e3;i=6614d9;b=4d18cf41f04842e1ab0764ddd12700ed;m=409677751d;t=65c9a49dc3723;x=d97f2d7d4a413fde`
- **Worker 2 Cursor:** `s=238b81e3b0d944cf9bedada85a9a43e3;i=6614e7;b=4d18cf41f04842e1ab0764ddd12700ed;m=409686ec6a;t=65c9a49ebae70;x=58ed1149cb4147ce`
- **Preflight Queue State:** Zero requests in flight (`Running: 0 reqs, Waiting: 0 reqs`).
- **External Client State:** No active OpenCode or external agent processes on either host.

### B. Post-Flight Request Accounting

| Worker Engine | Physical Target | Actual Completions in Journal | Expected Campaign Completions | Unmapped / Outside Requests |
|---|---|---|---|---|
| **Worker 1 (`aihost-vllm-worker1.service`)** | Arc A770 (GPU 0) | **50** | **50** (10 projects $\times$ 5 items) | **0** |
| **Worker 2 (`aihost-vllm-worker2.service`)** | Arc A770 (GPU 1) | **31** | **31** (1 warmup + 10 $\times$ 3 items) | **0** |
| **Total Physical Inference Calls** | Dual-A770 | **81** | **81** | **0** |

**Isolation Verdict:** **100% VERIFIED PHYSICAL ISOLATION**. Exactly 81 inference requests were recorded on the physical GPUs during the 38-minute campaign, perfectly matching the 81 campaign requests (1 warmup + 80 project items). Zero outside requests reached either worker.

---

## 2. Experimental Comparability Preflight

To ensure an uncompromised comparison between the frozen B control and the B+ requalification rerun, all experimental parameters were held strictly invariant:

| Parameter | Frozen B Control | Candidate B+ Requalification | Invariance Status |
|---|---|---|---|
| **Host Hardware** | Dell Precision T5820 | Dell Precision T5820 | Identical physical machine |
| **Acceleration** | Dual Intel Arc A770 16GB (PCIe BDF `03:00.0`, `04:00.0`) | Dual Intel Arc A770 16GB (PCIe BDF `03:00.0`, `04:00.0`) | Identical physical GPUs |
| **Container Image** | `vllm-openai-xpu@sha256:4bdfd5b9...` | `vllm-openai-xpu@sha256:4bdfd5b9...` | Identical container digest |
| **Physical Model** | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | Identical model revision |
| **Target Arrival Rate** | $\lambda = 19.5\text{ proj/hr}$ ($184.62\text{s}$ spacing) | $\lambda = 19.5\text{ proj/hr}$ ($184.62\text{s}$ spacing) | Identical arrival schedule |
| **Matched Corpus** | 6 standardized projects (API, Sec, Schema, Worker, DB, Obs) | 6 standardized projects (API, Sec, Schema, Worker, DB, Obs) | Identical project order & prompts |
| **Item Assignment** | Item 01 on Worker 1 | Item 01 on Worker 2 | Approved experimental variable |
| **Handoff Validation** | N/A (single worker Stage 1) | Cryptographic [`InvestigationHandoffEnvelope`](file:///home/mike/Projects/aihost/phase14/src/autonomous_engineering/pipeline_rebalancing/handoff_contract.py) sealed & validated | Hard gating enforced |
| **External Acceptance** | Independent 4-Gate Boundary | Independent 4-Gate Boundary | Identical validator authority |

**Comparability Verdict:** All experimental conditions, hardware profiles, model revisions, and acceptance boundaries are 100% matched to the frozen B control.
