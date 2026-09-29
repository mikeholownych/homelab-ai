# Phase 14: Configuration B+ Sustained-Capacity Qualification Report (18.0 proj/hr)

- **Campaign Identifier:** `PHASE_14_EXPERIMENT_02_B_PLUS_CAPACITY_18`
- **Execution Date:** 2026-09-29
- **Campaign Window (UTC):** `2026-09-29T09:21:44.772Z` to `2026-09-29T10:00:04.340Z`
- **Total Physical Duration:** $2,299.57\text{ seconds}$ ($38.33\text{ minutes}$)
- **Target Operating Point:** $\lambda = 18.0\text{ projects/hour}$ ($\Delta t = 200.00\text{ seconds}$)
- **Runner Script:** [`phase14/src/autonomous_engineering/pipeline_rebalancing/capacity_18_runner.py`](file:///home/mike/Projects/aihost/phase14/src/autonomous_engineering/pipeline_rebalancing/capacity_18_runner.py)
- **Raw Evidence Package:** [`phase14/evidence/phase14_capacity_18_results.json`](file:///home/mike/Projects/aihost/phase14/evidence/phase14_capacity_18_results.json)
- **Prometheus Telemetry Package:** [`phase14/evidence/phase14_capacity_18_telemetry.json`](file:///home/mike/Projects/aihost/phase14/evidence/phase14_capacity_18_telemetry.json)
- **Comparative Baseline Package:** [`phase14/evidence/phase14_capacity_18_comparison.json`](file:///home/mike/Projects/aihost/phase14/evidence/phase14_capacity_18_comparison.json)

---

## 1. Experiment Registration and Frozen Acceptance Criteria

The qualification campaign was formally preregistered in [`phase14/evidence/phase14_capacity_18_registration.md`](file:///home/mike/Projects/aihost/phase14/evidence/phase14_capacity_18_registration.md) prior to physical execution. The experiment evaluates whether homogeneous dual-30B pipeline rebalancing (Configuration B+) can sustain an offered arrival rate of $\lambda = 18.0\text{ projects/hour}$ without backlog accumulation, invariant violations, or quality degradation.

### Frozen Acceptance Criteria:
1. **Independent Project Acceptance:** $100\%$ ($10/10$) projects pass all 4 external quality gates.
2. **Cryptographic Handoff Integrity:** $100\%$ of Item 01 investigations produce a sealed, validated [`InvestigationHandoffEnvelope`](file:///home/mike/Projects/aihost/phase14/src/autonomous_engineering/pipeline_rebalancing/handoff_contract.py) verified by `Item01HandoffValidator` before Worker 1 initiates Item 02 planning.
3. **Queue Wait Non-Divergence:** Backlog growth slope $|s| \le 1.00\text{ s/project}$, with late-window mean queue wait $\le 30.0\text{s}$.
4. **Turnaround Consistency:** Late-window mean turnaround degradation $\le 20\%$ relative to early window.
5. **Queue Depth Invariant:** Pipelined backlog strictly $O(1)$.
6. **Workload Isolation:** Exactly $0$ outside or unmapped requests recorded on physical GPUs during the campaign.
7. **Production Non-Interference:** Production default remains locked on `SchedulingMode.CONFIGURATION_B`; zero disruption to production gateway or host services.
8. **Observability Telemetry Integration:** Ingestion of newly deployed `/health` and `/metrics` telemetry by Prometheus.

---

## 2. Source and Configuration Identities

| Component | Identifier / Specification | State During Campaign |
|---|---|---|
| **Git Commit** | `3a21d516244d2d471583d73b64ec471887e07621` | Active branch `main` |
| **Deployed Gateway Release** | `t5820-gateway-3a21d51` | Active systemd drop-in `15-release.conf` |
| **Gateway Service** | `aihost-orchestrator-gateway.service` (PID `1766552`) | Port `8010` (forwarded `18010`), 0 restarts |
| **Production Scheduling Default** | `SchedulingMode.CONFIGURATION_B` | Pinned production default (unaltered) |
| **Evaluated Pipeline Mode** | `SchedulingMode.CONFIGURATION_B_PLUS` | Experimental pipeline rebalancing |
| **Worker 1 (Lead)** | `b0-live-tp1-worker1` (PID `2574`, Port `8000`) | Arc A770 16GB (`0000:03:00.0`), AWQ-4bit |
| **Worker 2 (Specialist)** | `b0-live-tp1-worker2` (PID `3534321`, Port `8001`) | Arc A770 16GB (`0000:04:00.0`), AWQ-4bit |
| **Model** | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | Identical revision across both workers |
| **Prometheus Scraper** | Prometheus Server (`127.0.0.1:9090`) | Scraping `127.0.0.1:18010/metrics` every 10s |

---

## 3. Isolation Proof and Outside-Request Reconciliation

Preflight and post-flight journal cursors were captured directly from the containerized vLLM engine units on the Dell Precision T5820 (`10.0.8.5`):

### A. Journal Cursor Accounting
- **Worker 1 Start Cursor:** `s=238b81e3b0d944cf9bedada85a9a43e3;i=68e9cd;b=4d18cf41f04842e1ab0764ddd12700ed;m=4202238a24;t=65c9bb5884c2a;x=d49f85ea7e5b0845`
- **Worker 2 Start Cursor:** `s=238b81e3b0d944cf9bedada85a9a43e3;i=68e9d9;b=4d18cf41f04842e1ab0764ddd12700ed;m=42022e87bb;t=65c9bb59349c1;x=3174eb21181f3e8e`

### B. Completion Reconciliation

| Service Unit | Hardware Target | Expected Calls | Actual Recorded Completions | Outside / Unmapped Requests |
|---|---|---|---|---|
| **`aihost-vllm-worker1.service`** | Arc A770 (`03:00.0`) | **50** (10 proj $\times$ 5 items) | **50** | **0** |
| **`aihost-vllm-worker2.service`** | Arc A770 (`04:00.0`) | **31** (1 warmup + 10 $\times$ 3 items) | **31** | **0** |
| **Total Physical Inference Calls** | Dual-A770 GPUs | **81** | **81** | **0** |

**Isolation Verdict:** **100% VERIFIED PHYSICAL ISOLATION**. Exactly 81 inference requests occurred across the dual GPUs during the 38.33-minute window, with zero unmapped or outside requests.

---

## 4. Prometheus Ingestion and Telemetry Evidence

Throughout preflight, warm-up, measurement, and drain, Prometheus scraped the orchestrator gateway at 10-second intervals (`up{job="aihost_orchestrator_gateway"} == 1`).
A total of 21 metric queries were exported across the campaign interval `[2026-09-29T09:21:44Z, 2026-09-29T10:00:04Z]`, preserved in [`phase14/evidence/phase14_capacity_18_telemetry.json`](file:///home/mike/Projects/aihost/phase14/evidence/phase14_capacity_18_telemetry.json):

1. `up{job='aihost_orchestrator_gateway'}`: $100\%$ availability ($1.0$).
2. `aihost_worker_health_status`: Continuous healthy status ($1.0$) for both `b0-live-tp1-worker1` and `b0-live-tp1-worker2`.
3. `aihost_worker_last_check_timestamp_seconds`: Freshness observed $< 10.0\text{s}$ at all times; zero stale flags.
4. `aihost_worker_check_duration_seconds`: Background probe latencies remained within $4\text{ms} - 8\text{ms}$.
5. `aihost_scheduler_worker_available`: Available worker count remained constant at $2$.
6. `aihost_scheduler_active_work` & `aihost_scheduler_queued_work`: Steady state baseline preserved.
7. Gateway `/health` snapshots captured before start, across each project completion, and post-drain all returned `200 OK` (`status: "healthy"`, `can_route: true`).

---

## 5. Complete Project-Level Results

All 10 projects were admitted on exact 200.0-second arrival schedules:

| Project ID | Archetype | Segment | Arrival (s) | Dispatch (s) | Wait (s) | W1 Dem (s) | W2 Dem (s) | Turnaround (s) | E2E Latency (s) | 4-Gate Status |
|---|---|---|---|---|---|---|---|---|---|---|
| `cap18-b_plus-proj-api-01` | API Refactoring | Matched | 0.00 | 0.00 | **0.00** | 171.60 | 98.36 | 227.63 | 227.63 | **ACCEPTED** |
| `cap18-b_plus-proj-sec-02` | Security Remediation | Matched | 200.00 | 200.00 | **0.00** | 187.00 | 104.74 | 254.74 | 254.74 | **ACCEPTED** |
| `cap18-b_plus-proj-schema-03` | Schema Contract | Matched | 400.00 | 400.00 | **0.00** | 157.64 | 98.45 | 249.54 | 249.54 | **ACCEPTED** |
| `cap18-b_plus-proj-worker-04` | Async Worker | Matched | 600.00 | 600.00 | **0.00** | 170.78 | 98.48 | 248.90 | 248.90 | **ACCEPTED** |
| `cap18-b_plus-proj-db-05` | Database Migration | Matched | 800.00 | 800.00 | **0.00** | 170.96 | 98.66 | 248.25 | 248.25 | **ACCEPTED** |
| `cap18-b_plus-proj-obs-06` | Observability Gateway | Matched | 1000.00 | 1000.00 | **0.00** | 171.02 | 98.47 | 247.89 | 247.89 | **ACCEPTED** |
| `cap18-b_plus-proj-api-07` | API Refactoring | Extended | 1200.00 | 1200.00 | **0.00** | 170.19 | 98.46 | 246.31 | 246.31 | **ACCEPTED** |
| `cap18-b_plus-proj-sec-08` | Security Remediation | Extended | 1400.00 | 1400.00 | **0.00** | 170.09 | 98.67 | 245.25 | 245.25 | **ACCEPTED** |
| `cap18-b_plus-proj-schema-09` | Schema Contract | Extended | 1600.00 | 1600.00 | **0.00** | 171.00 | 98.81 | 244.90 | 244.90 | **ACCEPTED** |
| `cap18-b_plus-proj-worker-10` | Async Worker | Extended | 1800.00 | 1800.00 | **0.00** | 171.04 | 99.04 | 244.94 | 244.94 | **ACCEPTED** |

---

## 6. Accepted Throughput and Measurement Boundaries

- **Offered Arrival Rate:** $\lambda = 18.0\text{ projects/hour}$ ($\Delta t = 200.00\text{ seconds}$).
- **Continuous Measurement Window:** $t=0.00\text{s}$ to $t=1800.00\text{s}$ ($1,800.00\text{s}$ = $30.00\text{ minutes}$ of sustained continuous arrivals).
  - During this arrival window, 10 projects were admitted with zero queue wait ($100\%$ admission promptness).
- **Drain Window:** $t=1800.00\text{s}$ to $t=2044.94\text{s}$ ($244.94\text{ seconds}$ to execute and accept the final in-flight project).
- **Total Campaign Span:** $2,044.94\text{ simulation seconds}$ ($2,299.57\text{ physical seconds}$).
- **Sustained Accepted Throughput (including drain):**
  $$\Theta = \frac{10\text{ accepted projects}}{2044.94\text{ seconds}} \times 3600 = \mathbf{17.6044\text{ accepted projects/hour}}$$
- **Effective Capacity Ratio:** $\frac{17.6044}{18.0000} = \mathbf{0.9780}$.

---

## 7. Queue-Depth and Queue-Wait Time-Series Analysis

In stark contrast to the 19.5 proj/hr regime (where queue wait accumulated by $+12.62\text{s/project}$ to $113.62\text{s}$), the 18.0 proj/hr regime demonstrated complete queue stability:

- **Queue Wait Series (Projects 1 to 10):**
  $$W = [0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00]\text{ seconds}$$
- **Backlog Growth Slope:** $s = \frac{W_{10} - W_1}{9} = \mathbf{0.0000\text{ seconds/project}}$.
- **Step-to-Step Mean Delta:** $\mathbf{0.0000\text{ seconds/project}}$.
- **Queue Depth:**
  - Mean Queue Depth: $0.0$
  - Max Queue Depth: $1$ (a project dispatches instantaneously upon arrival as Worker 2 is already idle).
- **Stability Conclusion:** **STABLE $O(1)$ QUEUE BACKLOG**. Backlog accumulation does not occur because the inter-arrival spacing ($\Delta t = 200\text{s}$) strictly exceeds Worker 1's mean service demand ($171.13\text{s}$).

---

## 8. Early-, Middle- and Late-Window Stability Comparison

To evaluate stationarity and confirm that queue metrics do not degrade over time, the 10-project campaign was partitioned into three windows:

| Metric | Early Window (Proj 1–3) | Middle Window (Proj 4–7) | Late Window (Proj 8–10) | Stability Delta (Late vs Early) |
|---|---|---|---|---|
| **Project Count** | 3 | 4 | 3 | - |
| **Acceptance Rate** | $100\%$ (3/3) | $100\%$ (4/4) | $100\%$ (3/3) | $0.0\%$ |
| **Queue Wait Mean** | **0.00s** | **0.00s** | **0.00s** | $\mathbf{0.00s}$ |
| **Queue Wait P95** | **0.00s** | **0.00s** | **0.00s** | $\mathbf{0.00s}$ |
| **Turnaround Mean** | $243.97\text{s}$ | $247.84\text{s}$ | $245.03\text{s}$ | $\mathbf{+1.06s}$ ($+0.43\%$) |
| **Turnaround P95** | $254.22\text{s}$ | $248.80\text{s}$ | $245.22\text{s}$ | $\mathbf{-9.00s}$ |
| **E2E Latency Mean** | $243.97\text{s}$ | $247.84\text{s}$ | $245.03\text{s}$ | $\mathbf{+1.06s}$ |
| **W1 Demand Mean** | $172.08\text{s}$ | $170.74\text{s}$ | $170.71\text{s}$ | $\mathbf{-1.37s}$ (stable) |
| **W2 Demand Mean** | $100.52\text{s}$ | $98.52\text{s}$ | $98.84\text{s}$ | $\mathbf{-1.68s}$ (stable) |

**Stationarity Assessment:** The ratio of Late Turnaround to Early Turnaround is $\frac{245.03}{243.97} = \mathbf{1.0043}$ ($+0.43\%$). This proves complete performance stationarity across the 38-minute campaign, satisfying the preregistered $\le 20\%$ threshold.

---

## 9. Worker Service Demand and Resource Observations

Across the 80 project work items executed:
- **Worker 1 (Lead):**
  - Mean service demand per project: $171.13\text{ seconds}$ ($\text{Min: } 157.64\text{s}, \text{Max: } 187.00\text{s}$).
  - Theoretical utilization at $\Delta t = 200\text{s}$:
    $$\rho_1 = \frac{171.13\text{s}}{200.00\text{s}} = \mathbf{0.8557}\quad (85.57\%)$$
  - Idle headroom: $28.87\text{ seconds}$ ($\sim 14.4\%$) per project.
- **Worker 2 (Specialist):**
  - Mean service demand per project: $99.22\text{ seconds}$ ($\text{Min: } 98.36\text{s}, \text{Max: } 104.74\text{s}$).
  - Theoretical utilization at $\Delta t = 200\text{s}$:
    $$\rho_2 = \frac{99.22\text{s}}{200.00\text{s}} = \mathbf{0.4961}\quad (49.61\%)$$
  - Idle headroom: $100.78\text{ seconds}$ ($\sim 50.4\%$) per project.

**Resource Conclusion:** Rebalancing Item 01 to Worker 2 offloads $\sim 28\text{s}$ from Worker 1, bringing Worker 1 utilization below saturation ($\rho_1 = 0.8557 < 1.0$) at 18.0 proj/hr.

---

## 10. Independent Acceptance and Containment Results

All 10 projects were audited by the 4-gate external authority boundary:
- **Gate 1 (Syntax & Non-Trivial Output):** $100\%$ ($80/80$ work items passed markdown code block and JSON schema structure checks).
- **Gate 2 (Branch-Complete Unit Tests):** $100\%$ ($10/10$ Item 04 test deliverables validated).
- **Gate 3 (Lead Security Review):** $100\%$ ($10/10$ Item 06 SAST deliverables verified by Worker 1).
- **Gate 4 (Schema Contracts):** $100\%$ ($10/10$ Item 05 OpenAPI 3.1 / JSON Schema Draft-07 deliverables validated).
- **Cryptographic Handoff Integrity:** Exactly $10/10$ `InvestigationHandoffEnvelope` artifacts were cryptographically sealed and accepted by `Item01HandoffValidator` before Item 02 DAG planning began. Zero speculative bypasses occurred.
- **Authority Boundaries:** Worker 1 retained registered lead authority over all architecture DAG formulations, security reviews, multi-file engine integration, and acceptance signoffs.

---

## 11. Drain Behavior and Recovery

- **Arrival Window Termination:** Final project (`cap18-b_plus-proj-worker-10`) arrived at $t=1800.00\text{s}$.
- **Drain Interval:** From $t=1800.00\text{s}$ to $t=2044.94\text{s}$ ($244.94\text{s}$ total drain duration).
  - Worker 2 completed Item 01 at $t=1827.8\text{s}$ and Items 04/05 at $t=1974.2\text{s}$.
  - Worker 1 completed Item 02/03 at $t=1905.1\text{s}$, Item 06 at $t=1973.8\text{s}$, and final acceptance Item 08 at $t=2044.94\text{s}$.
- **Queue Clearance:** Zero residual work remained in flight at $t=2044.94\text{s}$.
- **Engine Recovery:** Both Worker 1 and Worker 2 immediately returned to idle baseline ($0$ active requests) within $1\text{ second}$ of Project 10 completion.

---

## 12. Comparison with Prior Baselines

| Dimension | Frozen Config B Control | Config B+ Requalification | Config B+ Capacity Qualification | Comparison Verdict |
|---|---|---|---|---|
| **Offered Arrival Rate** | $19.5\text{ proj/hr}$ ($184.6\text{s}$) | $19.5\text{ proj/hr}$ ($184.6\text{s}$) | $\mathbf{18.0\text{ proj/hr}}$ ($\mathbf{200.0\text{s}}$) | Targeted sustainable operating point |
| **Project Cohort Size** | 6 projects | 10 projects | **10 projects** | Complete standardized corpus |
| **Accepted Throughput** | $16.1484\text{ proj/hr}$ | $17.7375\text{ proj/hr}$ | $\mathbf{17.6044\text{ proj/hr}}$ | **+9.02% vs Config B Control** |
| **Mean Queue Wait** | $93.68\text{s}$ | $35.75\text{s}$ | $\mathbf{0.00\text{s}}$ | **100% Elimination of Queue Wait** |
| **P95 Queue Wait** | $179.85\text{s}$ | $100.02\text{s}$ | $\mathbf{0.00\text{s}}$ | **100% Elimination of Tail Wait** |
| **Backlog Growth Slope** | $+22.28\text{s/proj}$ | $+12.62\text{s/proj}$ | $\mathbf{0.0000\text{s/proj}}$ | **Strictly Flat / Stable ($s \le 1.0$)** |
| **Queue Stability Status** | `ACCUMULATING` | `ACCUMULATING` | $\mathbf{STABLE}$ | **Sustained Stability Demonstrated** |
| **Worker 1 Mean Demand** | $194.42\text{s}$ | $171.16\text{s}$ | $\mathbf{171.13\text{s}}$ | $-23.29\text{s}$ critical path offload |
| **Worker 1 Utilization ($\rho_1$)** | $1.0531$ (saturated) | $0.9271$ (saturated pipelined) | $\mathbf{0.8557}$ | **Sub-saturated with 14.4% margin** |
| **Outside Contamination** | 0 requests | 0 requests | **0 requests** | 100% verified physical isolation |

---

## 13. Limitations and Telemetry Gaps

1. **Deterministic Spacing:** The campaign evaluated a deterministic arrival schedule ($\Delta t = 200.0\text{s}$). In a Poisson arrival process with exponential inter-arrival times, stochastic clustering could generate transient queue build-ups even at $\rho = 0.856$.
2. **Gateway-Level Telemetry Blind Spots:** Gateway Prometheus metrics capture HTTP latencies, request states, and scheduler counters, but do not directly report vLLM KV-cache memory pressure or continuous GPU thermals. These were verified out-of-band via SSH and `vllm-top`.
3. **Production Scope:** This qualification proves that $\lambda = 18.0\text{ proj/hr}$ is physically sustainable under Configuration B+. It does not evaluate mixed model sizes (e.g., 70B/8B) or different context lengths $> 4096\text{ tokens}$.

---

## 14. Final Disposition and Authorization Boundary

All preregistered criteria for the Phase 14 Configuration B+ Sustained-Capacity Qualification campaign are fully satisfied:
- $10/10$ independent project acceptance ($100\%$).
- Backlog growth slope $s = 0.0000\text{ s/project} \le 1.00\text{ s/project}$.
- Queue wait across all projects $= 0.00\text{s}$.
- $100\%$ verified physical workload isolation ($0$ outside requests).
- Complete telemetry reconciliation with deployed gateway endpoints.

### Terminal Disposition:
$$\mathbf{PHASE\_14\_B\_PLUS\_CAPACITY\_18:\ PROVEN}$$

### Authorization Boundary:
This disposition rigorously qualifies Configuration B+ as capable of sustaining an offered rate of $18.0\text{ projects/hour}$ on homogeneous dual-30B hardware.
In accordance with operator instructions, **production scheduling remains strictly on `SchedulingMode.CONFIGURATION_B`**. Production promotion is not authorized and has not been executed.
