# Phase 13 Physical Timeline Reconstruction Report

## 1. Executive Summary
This report forensically reconstructs the complete chronological timeline of the Phase 13 Expanded Physical Qualification across all phases: preflight, homogeneous control campaign, candidate switch, physical containment probing, heterogeneous sustained campaign, and baseline restoration.

All timestamps are established from raw ISO 8601 wall-clock logs and monotonic microsecond deltas recorded in the physical trace files:
- [`phase13_expanded_control_results.json`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/traces/phase13_expanded_control_results.json)
- [`phase13_physical_containment_results.json`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/traces/phase13_physical_containment_results.json)
- [`phase13_expanded_heterogeneous_results.json`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/traces/phase13_expanded_heterogeneous_results.json)
- Systemd journal entries on target host `10.0.8.5`.

---

## 2. Master Chronological Event Timeline

| Event ID | Timestamp (UTC) | Duration | Operation / Action | Target Endpoint / Worker | Outcome / Verification |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **EV-01** | `2026-09-27T23:05:10Z` | ~30s | Preflight Verification Checklist | Host `10.0.8.5` | 9/9 Preflight Gates PASSED |
| **EV-02** | `2026-09-27T23:06:33Z` | - | Control Campaign Launch | Dual-30B Baseline | Began `CTRL-01` |
| **EV-03** | `2026-09-27T23:10:05Z` | 212.02s | Project `CTRL-01` Completed | Worker 1 & Worker 2 (30B) | Accepted (Stage 2: 57.58s) |
| **EV-04** | `2026-09-27T23:13:36Z` | 211.11s | Project `CTRL-02` Completed | Worker 1 & Worker 2 (30B) | Accepted (Stage 2: 56.96s) |
| **EV-05** | `2026-09-27T23:17:08Z` | 212.27s | Project `CTRL-03` Completed | Worker 1 & Worker 2 (30B) | Accepted (Stage 2: 56.94s) |
| **EV-06** | `2026-09-27T23:20:41Z` | 212.30s | Project `CTRL-04` Completed | Worker 1 & Worker 2 (30B) | Accepted (Stage 2: 57.08s) |
| **EV-07** | `2026-09-27T23:24:13Z` | 212.72s | Project `CTRL-05` Completed | Worker 1 & Worker 2 (30B) | Accepted (Stage 2: 57.21s) |
| **EV-08** | `2026-09-27T23:27:45Z` | 211.21s | Project `CTRL-06` Completed | Worker 1 & Worker 2 (30B) | Accepted (Stage 2: 56.55s) |
| **EV-09** | `2026-09-27T23:27:45Z` | **1,271.63s** | **Control Campaign Concluded** | Dual-30B Baseline | **6/6 Accepted (16.99 proj/hr)** |
| **EV-10** | `2026-09-27T23:28:40Z` | ~85s | Candidate Switch on Worker 2 | Worker 2 (GPU 1) | Deployed `Qwen2.5-7B-Instruct-AWQ` |
| **EV-11** | `2026-09-27T23:30:22Z` | - | Candidate Ready on Port 8001 | Worker 2 (GPU 1) | HTTP 200 on `/v1/models` |
| **EV-12** | `2026-09-28T02:08:40Z` | 55.0s | Physical Containment Run 1 | Worker 2 (7B) | 8/10 contained (Regex gap identified) |
| **EV-13** | `2026-09-28T02:11:06Z` | ~60s | Boundary Regex Remediation | Local `containment.py` | Added JSON key & evasion regex |
| **EV-14** | `2026-09-28T02:12:28Z` | 55.0s | Physical Containment Run 2 | Worker 2 (7B) | **10/10 Safely Quarantined (100%)** |
| **EV-15** | `2026-09-28T02:13:37Z` | - | Heterogeneous Campaign Launch | 30B Lead + 7B Specialist | Began `HETERO-01` |
| **EV-16** | `2026-09-28T02:16:47Z` | 189.86s | Project `HETERO-01` Completed | Worker 1 (30B) & W2 (7B) | Accepted (Stage 2: 35.05s) |
| **EV-17** | `2026-09-28T02:19:56Z` | 189.19s | Project `HETERO-02` Completed | Worker 1 (30B) & W2 (7B) | Accepted (Stage 2: 34.73s) |
| **EV-18** | `2026-09-28T02:23:06Z` | 189.90s | Project `HETERO-03` Completed | Worker 1 (30B) & W2 (7B) | Accepted (Stage 2: 34.90s) |
| **EV-19** | `2026-09-28T02:26:15Z` | 189.17s | Project `HETERO-04` Completed | Worker 1 (30B) & W2 (7B) | Accepted (Stage 2: 34.94s) |
| **EV-20** | `2026-09-28T02:29:25Z` | 190.33s | Project `HETERO-05` Completed | Worker 1 (30B) & W2 (7B) | Accepted (Stage 2: 34.93s) |
| **EV-21** | `2026-09-28T02:32:35Z` | 189.42s | Project `HETERO-06` Completed | Worker 1 (30B) & W2 (7B) | Accepted (Stage 2: 34.76s) |
| **EV-22** | `2026-09-28T02:32:35Z` | **1,137.87s** | **Hetero Campaign Concluded** | 30B Lead + 7B Specialist | **6/6 Accepted (18.98 proj/hr)** |
| **EV-23** | `2026-09-28T02:32:44Z` | ~250s | Baseline Restoration Script | Worker 2 (GPU 1) | Reverted config; vLLM warmup |
| **EV-24** | `2026-09-28T02:57:05Z` | - | Worker 2 Baseline Ready | Worker 2 (GPU 1) | Restored 30B serving on 8001 |
| **EV-25** | `2026-09-28T02:57:18Z` | - | Final Restoration Audit | Target Host `10.0.8.5` | Config SHA256 `641c9402...` match |

---

## 3. Elapsed Time vs. Active Time vs. Idle Time

### 3.1 Control Campaign Execution Decomposition
- **Total Campaign Elapsed Time**: **1,271.63 seconds** (21.19 minutes).
- **Active Inference Time (Sum of Projects)**: **1,271.63 seconds**.
- **Inter-Project Queue Idle Time**: **0.00 seconds** (back-to-back synchronous project invocation).
- **Stage 1 (Lead Planning)**: Mean 98.42s per project (46.4% of project time).
- **Stage 2 (Concurrent Offload)**: Mean 57.05s per project (26.9% of project time).
- **Stage 3 (Lead Integration & Acceptance)**: Mean 56.47s per project (26.6% of project time).

### 3.2 Heterogeneous Campaign Execution Decomposition
- **Total Campaign Elapsed Time**: **1,137.87 seconds** (18.96 minutes).
- **Active Inference Time (Sum of Projects)**: **1,137.87 seconds**.
- **Inter-Project Queue Idle Time**: **0.00 seconds** (back-to-back synchronous project invocation).
- **Stage 1 (Lead Planning)**: Mean 98.39s per project (51.9% of project time).
- **Stage 2 (Concurrent Offload)**: Mean 34.88s per project (18.4% of project time).
- **Stage 3 (Lead Integration & Acceptance)**: Mean 56.38s per project (29.7% of project time).

### 3.3 Maintenance and Operational Transitions
- **Candidate Switch & Cold Start**: ~85 seconds.
- **Physical Containment Probing**: 110 seconds total (two 55s runs).
- **Baseline Restoration & JIT Compile / Warmup**: ~250 seconds.
- **Combined Active Physical Benchmarking Time**: 1,271.63s + 1,137.87s + 110s = **2,519.50 seconds (~42.0 minutes)**.

---

## 4. Analytical Distinction: Completed-Project Throughput vs. Fixed-Window Throughput

1. **Completed-Project Throughput ($\text{Rate}_{\text{completion}}$)**:
   - Defined as:
     $$\text{Rate}_{\text{completion}} = \frac{N_{\text{completed}}}{\Delta t_{\text{completed}}} \times 3,600$$
   - Observed values: **16.99 proj/hr** (Control) vs. **18.98 proj/hr** (Heterogeneous).
   - This metric measures **system processing capacity under saturation (zero inter-arrival idle time)**.

2. **Fixed-Window Observation Throughput ($\text{Rate}_{\text{window}}$)**:
   - Defined against a fixed preregistered observation window $T_{\text{window}}$ (e.g., $T_{\text{window}} = 7,200\text{ seconds}$ / 2.0 hours):
     $$\text{Rate}_{\text{window}} = \frac{N_{\text{completed\_in\_window}}}{T_{\text{window}}} \times 3,600$$
   - Because the test runner halted immediately upon completing 6 projects (~20 minutes), the physical campaign **did not observe the system across a continuous 2.0-hour window**.
   - If the system had completed 6 projects in 20 minutes and experienced zero further demand for the remaining 100 minutes of a 2-hour window, the fixed-window throughput would be $6 / 2.0 = 3.0\text{ proj/hr}$.

**Finding**: The reported primary metric was strictly **completed-workload throughput under continuous demand**, not a multi-hour fixed-window observation.
