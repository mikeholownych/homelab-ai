# Phase 14 Experiment 02: Extended Configuration B+ Queue-Stability Qualification

- **Date:** 2026-09-29
- **Campaign Scope:** 10-Project Sustained Execution under Offered Rate $\lambda = 19.5\text{ proj/hr}$ ($T_{\text{arr}} = 184.62\text{s}$)
- **Evidence Source:** [`phase14/evidence/phase14_b_plus_extended_requalification_results.json`](file:///home/mike/Projects/aihost/phase14/evidence/phase14_b_plus_extended_requalification_results.json)

---

## 1. 10-Project Queue Dynamic Trajectory

The extended queue stability observation ran 10 sequential engineering projects across the full 6 standardized archetypes plus 4 extended archetypes:

| Project # | Project ID | Archetype | Arrival (s) | Dispatch (s) | Queue Wait (s) | Turnaround (s) | Completion (s) | W1 Demand (s) | W2 Demand (s) | Accepted |
|---|---|---|---|---|---|---|---|---|---|---|
| **1** | `requal-b_plus-proj-api-01` | API Refactoring | 0.00 | 0.00 | **0.00** | 224.31 | 224.31 | 168.49 | 94.75 | True |
| **2** | `requal-b_plus-proj-sec-02` | Security Remediation | 184.62 | 184.62 | **0.00** | 229.74 | 414.35 | 152.62 | 92.48 | True |
| **3** | `requal-b_plus-proj-schema-03` | Schema Contract | 369.23 | 369.23 | **0.00** | 241.09 | 610.32 | 167.85 | 96.88 | True |
| **4** | `requal-b_plus-proj-worker-04` | Async Worker | 553.85 | 553.85 | **0.00** | 251.97 | 805.82 | 168.11 | 96.93 | True |
| **5** | `requal-b_plus-proj-db-05` | Database Migration | 738.46 | 749.25 | **10.79** | 257.71 | 1,006.96 | 172.27 | 98.11 | True |
| **6** | `requal-b_plus-proj-obs-06` | Observability Gateway | 923.08 | 947.81 | **24.74** | 272.70 | 1,220.51 | 185.28 | 105.81 | True |
| **7** | `requal-b_plus-proj-api-07` | API Refactoring Ext | 1,107.69 | 1,163.41 | **55.72** | 255.34 | 1,418.75 | 170.02 | 96.89 | True |
| **8** | `requal-b_plus-proj-sec-08` | Security Rem Ext | 1,292.31 | 1,361.58 | **69.27** | 257.48 | 1,619.06 | 172.30 | 97.45 | True |
| **9** | `requal-b_plus-proj-schema-09` | Schema Contract Ext | 1,476.92 | 1,560.32 | **83.40** | 271.90 | 1,832.22 | 185.14 | 104.91 | True |
| **10** | `requal-b_plus-proj-worker-10` | Async Worker Ext | 1,661.54 | 1,775.15 | **113.62** | 254.44 | 2,029.60 | 169.47 | 97.80 | True |

---

## 2. Queue Wait and Backlog Dynamics

```
Queue Wait Progression (seconds):
[0.00s]  P1 |
[0.00s]  P2 |
[0.00s]  P3 |
[0.00s]  P4 |
[10.79s] P5 |==
[24.74s] P6 |=====
[55.72s] P7 |===========
[69.27s] P8 |==============
[83.40s] P9 |=================
[113.62s]P10|======================
```

### Analysis of the Backlog Trajectory:
1. **The Sub-Saturated Phase (Projects 1 to 4):**
   - For the first 4 projects, queue wait was strictly **$0.00\text{ seconds}$**.
   - Worker 1 service demand averaged **$164.27\text{s}$**, well below the arrival window of **$184.62\text{s}$** ($\rho_1 \approx 0.89$).
   - Worker 2 cleared Item 01 in ~35s, allowing immediate project dispatch upon arrival.
2. **The Backlog Transition (Projects 5 to 10):**
   - Starting at Project 5, queue wait began accumulating: $10.79\text{s} \rightarrow 24.74\text{s} \rightarrow 55.72\text{s} \rightarrow 69.27\text{s} \rightarrow 83.40\text{s} \rightarrow 113.62\text{s}$.
   - The queue wait growth slope across the 10-project campaign averaged **$+12.62\text{ seconds per project}$**.
3. **Comparison Against Configuration B Control:**
   - Under Configuration B, queue wait accumulation was **$+39.3\text{ seconds per project}$**, reaching **$189.67\text{ seconds}$** by Project 6 alone.
   - Configuration B+ reduced the rate of queue backlog accumulation by **$67.9\%$** ($+12.62\text{s/proj}$ vs $+39.30\text{s/proj}$).
   - However, because the slope remains positive ($+12.62 > 0$), Configuration B+ does **not** achieve infinite-horizon steady-state queue stability at an offered rate of $\lambda = 19.5\text{ proj/hr}$.

---

## 3. Mathematical Attribution: Why Backlog Grows at 19.5 proj/hr

While Worker 1 service demand averaged **$171.16\text{s} < 184.62\text{s}$**, the pipeline turnaround ($T$) averaged **$254.68\text{ seconds}$**. 

In an engineering pipeline with sequential dependencies (Item 01 on W2 $\rightarrow$ Items 02, 03 on W1 $\rightarrow$ Items 04, 05 on W2 $\parallel$ Item 06 on W1 $\rightarrow$ Items 07, 08 on W1):
- Even though Worker 1 demand is less than the arrival period, the **inter-stage synchronization handoffs** and stochastic variations in LLM generation tokens create pipeline bubbles where Worker 1 cannot immediately begin the next project until the preceding project clears Stage 3.
- When an arrival interval is $184.62\text{s}$, any project whose turnaround stretches to $270\text{s}$ (such as Projects 6 and 9) pushes subsequent dispatches behind schedule, causing a ratcheting effect.

---

## 4. Reconciled Sustainable Operating Capacity

To ensure complete, unbounded queue stability where queue wait remains asymptotically bounded at zero:
- The arrival period ($T_{\text{arr}}$) must provide sufficient clearance for both Worker 1 service demand ($171\text{s}$) and pipeline handoff synchronization buffers.
- Setting $T_{\text{arr}} \ge 200\text{ seconds}$ yields an offered rate of:
  $$\lambda_{\text{sustainable}} \le \frac{3600}{200} = \mathbf{18.0\text{ projects/hour}}$$
- At $\lambda \le 18.0\text{ proj/hr}$, Worker 1 utilization is $\rho_1 \le 0.85$, preventing pipeline handoff backlog accumulation.
- At $\lambda = 19.5\text{ proj/hr}$, Configuration B+ delivers higher throughput (17.74 proj/hr vs 16.15 proj/hr) and delays backlog onset for 4 projects, but exhibits transient backlog accumulation over extended 10+ project cohorts.
