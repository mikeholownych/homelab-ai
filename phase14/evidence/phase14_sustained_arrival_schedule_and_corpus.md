# Phase 14 Experiment 02: Arrival Schedule and Workload Corpus

## 1. Workload Corpus Specification

The sustained queue qualification uses the identical 6 representative engineering archetypes established in Phase 13 and calibrated in Phase 14 Experiment 01.

| Index | Archetype ID | Archetype Discipline | Title & Primary Scope | Complexity / Max Tokens |
|---|---|---|---|---|
| **1** | `proj-api-01` | API Refactoring | API Gateway Endpoints and Schema Validation | 512–768 tokens |
| **2** | `proj-sec-02` | Security Remediation | RBAC Security Remediation & Input Sanitization | 512–768 tokens |
| **3** | `proj-schema-03` | Schema Contract | Structured Output Contract & Event Schema Migration | 512–768 tokens |
| **4** | `proj-worker-04` | Async Worker | Async Task Queue Worker Concurrency Engine | 512–768 tokens |
| **5** | `proj-db-05` | Database Migration | Multi-Tenant Isolation and Transaction Engine | 512–768 tokens |
| **6** | `proj-obs-06` | Observability Gateway | Telemetry Ingestion Pipeline and Metrics Aggregator | 512–768 tokens |

### Immutable Work Order Prompts
Every archetype generates 8 sequential and concurrent items with deterministic prompts at `temperature=0.0`. Under Configuration B+, Item 01 executes on Worker 2 and produces an `InvestigationHandoffEnvelope`, while under Configuration B, Item 01 executes on Worker 1.

---

## 2. Arrival Schedule & Mathematical Generation

The arrival process is defined over discrete monotonic simulation time $t \ge 0$, parameterized by target arrival rate $\lambda$:

$$\Delta t_{\text{inter-arrival}} = \frac{3600}{\lambda} \quad \text{seconds}$$

### Regime 1 Arrival Schedule ($\lambda = 12.0\text{ projects/hour}$)
- **Target Inter-Arrival Time**: $300.0\text{ seconds}$ ($5.0\text{ minutes}$).
- **Cohort Size**: 4 projects per configuration.
- **Scheduled Relative Arrival Offsets**:
  - Project 1: $t_0 = 0.0\text{s}$
  - Project 2: $t_1 = 300.0\text{s}$ ($5.0\text{m}$)
  - Project 3: $t_2 = 600.0\text{s}$ ($10.0\text{m}$)
  - Project 4: $t_3 = 900.0\text{s}$ ($15.0\text{m}$)

### Regime 2 Arrival Schedule ($\lambda = 19.5\text{ projects/hour}$)
- **Target Inter-Arrival Time**: $184.6\text{ seconds}$ ($3.08\text{ minutes}$).
- **Cohort Size**: 6 projects per configuration (full archetype suite).
- **Scheduled Relative Arrival Offsets**:
  - Project 1: $t_0 = 0.0\text{s}$
  - Project 2: $t_1 = 184.6\text{s}$ ($3.08\text{m}$)
  - Project 3: $t_2 = 369.2\text{s}$ ($6.15\text{m}$)
  - Project 4: $t_3 = 553.8\text{s}$ ($9.23\text{m}$)
  - Project 5: $t_4 = 738.4\text{s}$ ($12.31\text{m}$)
  - Project 6: $t_5 = 923.0\text{s}$ ($15.38\text{m}$)

---

## 3. Queue Buffer Limits & Concurrency Constraints

- **Maximum Admitted Queue Depth**: $Q_{\max} = 10\text{ projects}$.
- **Admission Policy**: FIFO with immediate admission as long as $Q < Q_{\max}$.
- **Worker Execution Invariants**:
  - Worker 1 executes at most one lead task at any instant.
  - Worker 2 executes at most one specialist task at any instant (and in B+, Item 01 investigation).
  - Tasks wait in queue until their worker role is free and all DAG prerequisites are satisfied.
  - Project turnaround is measured from queue arrival to 4-gate independent acceptance.
