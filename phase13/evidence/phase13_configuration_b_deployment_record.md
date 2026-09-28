# Phase 13 Configuration B Deployment Record: Production Promotion Event

## 1. Deployment Overview & Identity

- **Deployment Event**: Production Promotion of Configuration B Scheduling
- **Deployment Timestamp**: 2026-09-28T09:44:00Z
- **Deployment Authority**: Explicit Human Authorization (Section 1)
- **Deployment Type**: In-place Software Scheduling Transition (Zero Hardware/Container Downtime)
- **Source Commit**: [`2c677a9`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization)
- **Transition Status**: **DEPLOYED & ACTIVE**

---

## 2. Production Service Configuration

```
+----------------------------------------------------------------------------------------------------+
| PROMOTED PRODUCTION CONFIGURATION STATE                                                            |
+--------------------------+-------------------------------------------------------------------------+
| Parameter                | Deployed Value                                                          |
+--------------------------+-------------------------------------------------------------------------+
| Scheduler Module         | autonomous_engineering.heterogeneous.capability_scheduler               |
| Scheduler Class          | CapabilityAwareScheduler                                                |
| Default Scheduling Mode  | SchedulingMode.CONFIGURATION_B                                          |
| Pipeline Coordinator     | autonomous_engineering.heterogeneous.production_pipeline                |
| Worker 1 PCI & Port      | 0000:51:00.0 (GPU 0), Port 8000 (Tunnel 18000)                          |
| Worker 2 PCI & Port      | 0000:93:00.0 (GPU 1), Port 8001                                         |
| Gateway Port             | 10.0.8.5:8010 (Tunnel 18010)                                            |
| Worker 1 Model           | cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit                         |
| Worker 2 Model           | cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit                         |
| Model Snapshot Revision  | 4bd30395b72ea6045edd04806c4fea448d4467b3                                |
| Worker 2 Config SHA-256  | 641c9402ebbc56f5d599512894f72a02304fd6615edbb7a2875ab48f93f4e08b       |
| In-Flight Drain Count    | 0 active tasks at transition boundary                                   |
| Errors / Warnings        | 0 errors, 0 warnings                                                    |
| Rollback State           | Verified ready (immediate toggle to CONFIGURATION_A)                    |
+--------------------------+-------------------------------------------------------------------------+
```

---

## 3. Production Task Placement Contract

Under promoted Configuration B:

```
Stage 1: Lead Architecture & Work Order Formulation (Sequential)
  ├── PROJ-XX-01 (Architecture Investigation)     ──> Worker 1 (30B MoE)
  ├── PROJ-XX-02 (Execution DAG & Rollback Plan)  ──> Worker 1 (30B MoE)
  └── PROJ-XX-03 (Core Engine Implementation)     ──> Worker 1 (30B MoE)

Stage 2: Concurrent Specialist Offload & Security Review (Parallel)
  ├── PROJ-XX-04 (Branch-Complete Unit Tests)     ──> Worker 2 (30B MoE)  [Advisory]
  ├── PROJ-XX-05 (OpenAPI 3.1 & Schema Contracts) ──> Worker 2 (30B MoE)  [Advisory]
  └── PROJ-XX-06 (SAST Security Invariant Review) ──> Worker 1 (30B MoE)  [Authoritative]

Stage 3: Lead Integration & Independent Project Acceptance (Sequential)
  ├── PROJ-XX-07 (Multi-Stage Integration)        ──> Worker 1 (30B MoE)  [Authoritative]
  └── PROJ-XX-08 (Independent 4-Gate Acceptance)  ──> Worker 1 (30B MoE)  [Authoritative]
```

---

## 4. Protected-Service Non-Interference Verification

During and following the deployment transition:
- Hermes Agent Gateway (PID 986): 0 dropped packets, 0 restarts.
- SSH Forwarding Tunnel (PID 2093382): 0 dropped packets, continuous forwarding on port `18010`.
- OpenCode Runner Service (PID 3130937): 0 dropped packets, continuous operation.
- Worker 1 & Worker 2 resident vLLM instances remained active without container termination.

Deployment confirmed complete, verified, and operational.
