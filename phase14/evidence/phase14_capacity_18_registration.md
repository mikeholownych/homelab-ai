# Phase 14: Configuration B+ Sustained-Capacity Qualification (18.0 proj/hr)
## Experiment Preregistration and Frozen Stability Criteria

- **Document ID:** `PHASE_14_EXPERIMENT_02_B_PLUS_CAPACITY_18_REGISTRATION`
- **Preregistration Date:** 2026-09-29T09:20:00Z
- **Authorizing Instruction:** Phase 14 Configuration B+ Sustained-Capacity Qualification (Section 4)
- **Repository:** `mikeholownych/homelab-ai`
- **Target Host:** Dell Precision T5820 (`10.0.8.5`)
- **Production Status:** Production remains locked on `SchedulingMode.CONFIGURATION_B`. B+ is evaluated as an experimental rebalanced pipeline.

---

## 1. Objective and Mission

The objective of this experiment is to independently determine whether Configuration B+ can sustain an offered arrival rate of $\lambda = 18.0\text{ projects/hour}$ ($\Delta t = 200.0\text{ seconds}$ inter-arrival interval) while maintaining:
1. 100% independent project acceptance across all 4 quality gates.
2. Complete dependency and authority invariants (Item 01 cryptographic handoff envelope sealed and verified before Item 02 planning; Worker 1 lead authority over DAG, security, integration, and signoff).
3. Strictly bounded queue depth and non-divergent queue wait ($O(1)$ backlog).
4. Stable worker utilization and service demand across early, middle, and late windows.
5. Consistent end-to-end latency without late-window degradation.
6. Zero outside request contamination and verified non-disruptive physical isolation.
7. Telemetry integration with the newly deployed orchestrator gateway observability endpoints (`/health` and `/metrics`) ingested by Prometheus.

---

## 2. System and Configuration Identities

| Component | Identifier / Specification | Verification Method |
|---|---|---|
| **Git Commit SHA** | `3a21d516244d2d471583d73b64ec471887e07621` | `git rev-parse HEAD` |
| **Deployed Gateway Release** | `t5820-gateway-3a21d51` | `/etc/systemd/system/aihost-orchestrator-gateway.service.d/15-release.conf` |
| **Gateway Service** | `aihost-orchestrator-gateway.service` (PID `1766552`, port `8010`) | `systemctl status aihost-orchestrator-gateway.service` |
| **Production Scheduling Mode** | `SchedulingMode.CONFIGURATION_B` | Pinned production default (unaltered) |
| **Experimental Scheduling Mode** | `SchedulingMode.CONFIGURATION_B_PLUS` | Item 01 investigation rebalanced to Worker 2 |
| **Worker 1 (Lead)** | `b0-live-tp1-worker1` (PID `2574`, port `8000` / tunnel `18000`) | Intel Arc A770 16GB (PCIe `0000:03:00.0`) |
| **Worker 2 (Specialist)** | `b0-live-tp1-worker2` (PID `3534321`, port `8001`) | Intel Arc A770 16GB (PCIe `0000:04:00.0`) |
| **Model** | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | vLLM 0.6.x containerized |
| **Observability Telemetry** | Gateway `/health` & `/metrics` -> Prometheus (`127.0.0.1:9090`) | Scrape interval 10s |

---

## 3. Workload Corpus and Deterministic Ordering

The experiment executes the approved 10-project standardized engineering corpus in deterministic sequence:

| Seq | Project ID | Project Name | Archetype | Segment |
|---|---|---|---|---|
| 1 | `proj-api-01` | API Gateway Endpoints and Schema Validation | API Refactoring | Matched 6-Project |
| 2 | `proj-sec-02` | RBAC Security Remediation and Input Sanitization | Security Remediation | Matched 6-Project |
| 3 | `proj-schema-03` | Structured Output Contract & Event Schema Migration | Schema Contract | Matched 6-Project |
| 4 | `proj-worker-04` | Async Task Queue Worker Concurrency Engine | Async Worker | Matched 6-Project |
| 5 | `proj-db-05` | Multi-Tenant Isolation and Transaction Engine | Database Migration | Matched 6-Project |
| 6 | `proj-obs-06` | Telemetry Ingestion Pipeline and Metrics Aggregator | Observability Gateway | Matched 6-Project |
| 7 | `proj-api-07` | Distributed Rate Limiting and Gateway Ingress | API Refactoring | Extended Observation |
| 8 | `proj-sec-08` | Mutual TLS Transport and Secret Vault Isolation | Security Remediation | Extended Observation |
| 9 | `proj-schema-09` | Event-Driven Protobuf Schema Compiler and Validator | Schema Contract | Extended Observation |
| 10 | `proj-worker-10` | Priority Preemption and Deadlock Detection Engine | Async Worker | Extended Observation |

Each project comprises 8 discrete items executed across 3 stages:
- **Stage 1 (Sequential Prerequisite):**
  - Item 01: Architecture Investigation -> Worker 2 (Specialist).
  - *Hard Gate:* Cryptographic seal of `InvestigationHandoffEnvelope` validated by `Item01HandoffValidator` before Item 02 proceeds.
  - Item 02: Execution DAG & Rollback Formulation -> Worker 1 (Lead).
  - Item 03: Core Engine Implementation -> Worker 1 (Lead).
- **Stage 2 (Parallel Fan-Out):**
  - Items 04 & 05: Unit Tests and OpenAPI Schema Contract -> Worker 2 (Specialist).
  - Item 06: SAST & Lead Security Review -> Worker 1 (Lead).
- **Stage 3 (Sequential Integration & Acceptance):**
  - Item 07: System Integration & Verification Harness -> Worker 1 (Lead).
  - Item 08: Acceptance Signoff & 4-Gate Audit -> Worker 1 (Lead).

---

## 4. Arrival Schedule and Observation Rationale

- **Offered Arrival Rate:** $\lambda = 18.0\text{ projects/hour}$
- **Inter-Arrival Spacing:** $\Delta t = \frac{3600}{18.0} = 200.00\text{ seconds}$ exactly.
- **Scheduled Arrival Times:**
  - Proj 1: $0.0\text{s}$
  - Proj 2: $200.0\text{s}$
  - Proj 3: $400.0\text{s}$
  - Proj 4: $600.0\text{s}$
  - Proj 5: $800.0\text{s}$
  - Proj 6: $1000.0\text{s}$
  - Proj 7: $1200.0\text{s}$
  - Proj 8: $1400.0\text{s}$
  - Proj 9: $1600.0\text{s}$
  - Proj 10: $1800.0\text{s}$
- **Measurement Span:** $0.0\text{s}$ to $1800.0\text{s}$ (30 minutes of continuous arrivals).
- **Drain Span:** From $1800.0\text{s}$ until Project 10 completion and acceptance signoff.
- **Total Physical Campaign Duration:** $\approx 2000 - 2300\text{ seconds}$ ($\sim 35 - 38\text{ minutes}$).

### Duration and Cohort Size Rationale:
In the previous 19.5 proj/hr campaign ($\Delta t = 184.62\text{s}$), queue wait expanded continuously from Project 5 to Project 10 ($10.79\text{s} \to 113.62\text{s}$), demonstrating that $\lambda = 19.5\text{ proj/hr}$ exceeds the capacity boundary of the dual-30B pipeline.
Worker 1 service demand averaged $168.56\text{s}$.
Under an offered spacing of $\Delta t = 200.0\text{s}$, the expected server utilization is:
$$\rho_1 = \frac{168.56\text{s}}{200.00\text{s}} = 0.8428$$
Leaving an expected idle headroom of $31.44\text{s}$ ($\sim 15.7\%$) between project allocations on Worker 1.
A 10-project corpus spanning 30 minutes of arrivals and $> 33$ minutes of physical execution provides sufficient statistical power to detect backlog accumulation:
- If $\rho_1 \ge 1.0$, queue wait will systematically increase at a rate $\ge 10\text{s}$ per project across the 10 projects.
- If $\rho_1 < 1.0$, the queue will remain strictly bounded and queue wait will settle into a flat, non-divergent regime ($|s| \le 1.0\text{s/proj}$).

---

## 5. Pre-Registered Stability & Acceptance Criteria

To achieve a terminal disposition of `PHASE_14_B_PLUS_CAPACITY_18: PROVEN`, the campaign must satisfy **all** of the following pre-registered criteria without exception:

1. **Independent Project Acceptance:** 10/10 ($100\%$) projects must independently satisfy all 4 quality gates:
   - Gate 1: Code and syntax verification on all work items.
   - Gate 2: Branch-complete unit test verification.
   - Gate 3: SAST security and invariant verification.
   - Gate 4: OpenAPI / JSON Schema Draft-07 contract verification.
2. **Cryptographic Handoff Integrity:** 10/10 ($100\%$) projects must produce a verified, sealed `InvestigationHandoffEnvelope` with matching repo commit SHA, valid symbol inspection, and explicit finding digest before Worker 1 initiates Item 02 planning. Speculative bypass is prohibited.
3. **Queue Wait Non-Divergence:**
   - The queue wait backlog growth slope $s = \frac{W_{late} - W_{early}}{N - 1}$ must satisfy $|s| \le 1.00\text{ s/project}$, OR queue wait must remain strictly bounded with late-window mean wait $\le 30.0\text{s}$.
4. **Turnaround Stability:** Late-window mean turnaround must not degrade by more than $20\%$ compared to the early-window mean turnaround.
5. **Queue Depth Invariant:** Pipelined queue backlog must remain $O(1)$ throughout the arrival schedule (no accumulating queue depth).
6. **Workload Isolation:** Pre- and post-flight journal cursor audits must prove exactly $0$ outside or unmapped inference requests reached either GPU.
7. **Production Non-Interference:** Zero interruptions, restarts, or config changes to production services or gateway.
8. **Observability Integration:** Prometheus metrics and gateway health endpoints must record all requests, worker availability, and health transitions across preflight, warm-up, measurement, and drain.

---

## 6. Stop and Rollback Protocol

- **Immediate Stop Conditions:**
  - Any HTTP 5xx error from either worker or gateway during project execution.
  - Any external validator failure or uncontained adversarial output.
  - Queue wait exceeding $300\text{ seconds}$ on any single project.
  - Any uncoordinated outside inference traffic reaching either worker during the measurement window.
- **Rollback Procedure:**
  - Production scheduling remains on `SchedulingMode.CONFIGURATION_B` by default.
  - The experimental runner halts without altering any systemd units, configuration files, or model weights.
