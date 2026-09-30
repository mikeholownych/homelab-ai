# Phase 14 Experiment 01: Instrumentation Definitions

## 1. Overview & Measurement Strategy

This document specifies the exact telemetry, timing, token accounting, and validation gate definitions used throughout Phase 14 Experiment 01.

Measurements are collected at task, stage, and project granularity using monotonic wall-clock timers (`time.monotonic()`) and verified against the OpenAI-compatible response metadata returned by the physical inference endpoints:
- Worker 1 (Lead 30B): `http://127.0.0.1:18000/v1`
- Worker 2 (Specialist 30B): `http://10.0.8.5:8001/v1`

---

## 2. Core Latency & Service Demand Formulations

### 2.1 Project Turnaround Time ($T_{\text{turnaround}}$)
The total elapsed wall-clock time from the dispatch of Stage 1 (Item 01) to the completion of Stage 3 (Item 08 project signoff):
$$T_{\text{turnaround}} = t_{\text{end, Item 08}} - t_{\text{start, Item 01}}$$

### 2.2 Stage Durations
- **Stage 1 Duration ($T_{\text{Stage 1}}$)**:
  - Configuration B: $T_1 + T_2 + T_3$ (executed sequentially on Worker 1).
  - Configuration B+: $T_1 + T_{\text{handoff}} + T_2 + T_3$, where $T_1$ executes on Worker 2, passes validation in $T_{\text{handoff}}$, and then Worker 1 executes $T_2 + T_3$.
- **Stage 2 Duration ($T_{\text{Stage 2}}$)**:
  - Parallel execution: $T_{\text{Stage 2}} = \max(T_4 + T_5, T_6)$
  - Worker 2 executes advisory test generation ($T_4$) and schema generation ($T_5$) sequentially.
  - Worker 1 concurrently executes security review ($T_6$).
- **Stage 3 Duration ($T_{\text{Stage 3}}$)**:
  - Integration ($T_7$) and signoff ($T_8$) executed sequentially on Worker 1: $T_{\text{Stage 3}} = T_7 + T_8$.

### 2.3 Worker Service Demand ($D_1$ and $D_2$)
Service demand represents the total compute time consumed by a specific worker for a project:
- **Worker 1 Service Demand ($D_1$)**:
  - Configuration B:
    $$D_{1,\text{B}} = T_1 + T_2 + T_3 + T_6 + T_7 + T_8$$
  - Configuration B+:
    $$D_{1,\text{B+}} = T_2 + T_3 + T_6 + T_7 + T_8$$
    $$\Delta D_1 = D_{1,\text{B}} - D_{1,\text{B+}} = T_1$$
- **Worker 2 Service Demand ($D_2$)**:
  - Configuration B:
    $$D_{2,\text{B}} = T_4 + T_5$$
  - Configuration B+:
    $$D_{2,\text{B+}} = T_1 + T_4 + T_5$$
- **Worker 2 Idle Time ($I_2$)**:
  $$I_2 = T_{\text{turnaround}} - D_2$$

---

## 3. Throughput Formulations

### 3.1 Saturated Bottleneck Capacity ($X_{\max}$)
Under saturated queue conditions with continuous project arrival, the maximum throughput capacity of the system is constrained by the bottleneck resource:
$$X_{\max} = \frac{3600}{\max(D_1, D_2)} \quad \text{projects/hour}$$

Under Configuration B:
- $D_1 \approx 189\text{s}$, $D_2 \approx 56\text{s}$
- Bottleneck: Worker 1 ($D_1$)
- Theoretical Capacity: $\approx 19.05$ projects/hour

Under Configuration B+:
- $D_1 \approx 161\text{s}$, $D_2 \approx 84\text{s}$
- Bottleneck: Worker 1 ($D_1$)
- Theoretical Capacity: $\approx 22.36$ projects/hour (+17.4% capacity)

### 3.2 Observed Operational Throughput ($X_{\text{obs}}$)
The empirical throughput realized across a closed campaign of $N$ projects:
$$X_{\text{obs}} = \frac{N \times 3600}{\sum_{i=1}^N T_{\text{turnaround}, i}} \quad \text{projects/hour}$$

---

## 4. Token Accounting and LLM Efficiency

For every task $j \in \{01, \dots, 08\}$:
- $P_j$: Prompt token count.
- $C_j$: Completion token count.
- $T_j$: Execution time in seconds.
- Generation Speed ($\text{TPS}_j$):
  $$\text{TPS}_j = \frac{C_j}{T_j} \quad \text{tokens/second}$$

---

## 5. Independent Validator Gate Criteria

Every project must achieve unconditional passing marks across 4 independent gates:

1. **Gate 1: Schema Conformance**
   - Evaluates: Item 05 structured schema output.
   - Criteria: Valid JSON Schema draft-07, zero syntax errors, required field completeness.
2. **Gate 2: Architecture Integrity**
   - Evaluates: Item 02 execution plan and Item 03 implementation.
   - Criteria: Non-empty DAG, valid dependencies, bounded rollback strategy.
3. **Gate 3: Security & Containment Policy**
   - Evaluates: Item 01 handoff envelope and Item 06 security review.
   - Criteria: Zero adversarial containment violations, zero unauthorized privilege escalation, non-empty security findings.
4. **Gate 4: Integration Verification**
   - Evaluates: Item 07 multi-file integration and Item 08 signoff.
   - Criteria: Consistency across all 8 artifacts, verification checklist signed, zero unresolved blocking defects.
