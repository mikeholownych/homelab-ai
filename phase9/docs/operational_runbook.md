# Phase 9: Operational Runbook
## Adaptive Specialized Agent Orchestration

**Status**: ACTIVE / OPERATIONAL  
**Platform**: Dell Precision 5820 Workstation + Remote Node `10.0.8.5`  
**Target Hardware**: 2x Intel Arc Pro B65 GPUs (PCIe `0000:51:00.0`, `0000:93:00.0`)  
**Serving Topology**: Dual-TP=1 vLLM Workers behind Orchestrator Gateway (Local Forward: `127.0.0.1:18010`)  
**Base Commit**: `3970753` | **Current Branch**: `phase9-adaptive-orchestration`

---

## 1. System Overview & Architecture

Phase 9 operationalizes capability-aware, specialized multi-agent orchestration for autonomous engineering. It dynamically composes on-demand specialized agents (Investigator, Architect, Engineer, Reviewer, Analyst) governed by declarative, immutable execution contracts.

```
+-------------------------------------------------------------------------+
|                  Human Work Order / CLI / Service Bus                   |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|            WorkloadRequirementsClassifier (Workstream B)                |
|  - Decouples Reasoning Complexity (Difficulty) from Failure Consequence |
|  - Enforces mandatory security suites for sensitive path mutations      |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|             CapabilityAwareModelScheduler (Workstream D)                |
|  - Stage 1: Hard Gate Filtering (Context, Tools, 5-Tuple Qualification) |
|  - Stage 2: Cost Minimization (Latency, Queue Delay, Expected Repairs)  |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|             Specialized Multi-Agent Execution Pipeline                  |
|  - VersionedAgentProfileRegistry: 3-way intersection permissions        |
|  - InterAgentHandoffManager: Typed EvidencePackage with digest checks   |
|  - ReasoningBudgetManager: Bounded evidence escalation (max depth 2)    |
|  - ContextConstructionManager: Provenance tracking & injection defense  |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|             IndependentAcceptanceManager (CAS Custody)                  |
|  - Isolated Sandbox Execution: AST syntax, security static analysis,   |
|    and sandbox unit test pass                                           |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|             PullRequestDeliveryManager (Human Authorization Gate)       |
|  - Explicit human delivery signature required for remote branch push    |
|  - Autonomous merge strictly PROHIBITED (ProtectedMergeProhibitedError) |
+-------------------------------------------------------------------------+
```

---

## 2. Protected Host Services Inventory

The following services run persistently on the host and must **never** be killed, restarted, or signaled:

| Service | Stable Metadata / Identifier | Command Line | Host / Port | Invariant Constraint |
|---|---|---|---|---|
| **Hermes Gateway** | PID `986` | `/home/mike/Projects/hermes-agent/.venv/bin/python -m hermes_cli.main gateway run` | Localhost | No port or socket conflicts |
| **OpenCode Runner** | PID `3130937` | `opencode --auto` | Localhost pts/1 | Active execution process |
| **SSH Reverse Tunnel**| PID `2093382` | `ssh -N -T -L 127.0.0.1:18010:127.0.0.1:8010 mike@10.0.8.5` | Local:18010 | Do not kill or bind port 18010 |
| **Worker 1 (vLLM)** | Container `vllm-xpu-tp1-worker1` | vLLM XPU TP=1 on GPU 0 (`0000:51:00.0`) | `10.0.8.5:8000` | Model swaps prohibited |
| **Worker 2 (vLLM)** | Container `vllm-xpu-tp1-worker2` | vLLM XPU TP=1 on GPU 1 (`0000:93:00.0`) | `10.0.8.5:8001` | Model swaps prohibited |
| **Orchestrator Gateway**| PID `742882` on node | `/usr/bin/python3 -m orchestrator_gateway` | `10.0.8.5:8010` | Multiplexes workers 1 & 2 |

---

## 3. Routine Operator Workflows

### 3.1 Verifying Host & Inference Health
```bash
# Verify campaign processes
ps -p 986,3130937,2093382 -o pid,stat,time,command

# Probe live inference endpoint via bearer token
curl -s -H "Authorization: Bearer $(cat /home/mike/.config/opencode/t5820-client-token)" http://127.0.0.1:18010/v1/models
```

### 3.2 Executing the Standalone Demonstration
```bash
python3 phase9/run_demo.py
```

### 3.3 Running Phase 9 Tests and Regression Suite
```bash
# Run Phase 9 test suite
PYTHONPATH=phase9/src:phase8/src:phase7/src:phase6/src:phase5/src:phase4/src:phase3/src:phase2/src:phase1/src:phase0/src pytest phase9/tests -q

# Run full cumulative regression suite across all 10 phases
PYTHONPATH=phase9/src:phase8/src:phase7/src:phase6/src:phase5/src:phase4/src:phase3/src:phase2/src:phase1/src:phase0/src pytest phase0/tests phase1/tests phase2/tests phase3/tests phase4/tests phase5/tests phase6/tests phase7/tests phase8/tests phase9/tests -q
```

---

## 4. Emergency Procedures & Troubleshooting

### 4.1 Unqualified Candidate Rejection (`NoQualifiedCandidateError`)
- **Symptom**: Task fails immediately during scheduling with `NoQualifiedCandidateError`.
- **Cause**: The requested workload class or profile does not possess an active `QualificationCertificate` in `ModelCapabilityRegistry`.
- **Remedy**: Verify qualification key using `ModelCapabilityRegistry.is_qualified(key)`. Check if qualification certificate expired or was revoked.

### 4.2 Escalation Depth Exceeded (`EscalationDepthExceededError`)
- **Symptom**: Task fails closed after repeated test or syntax failures.
- **Cause**: Task exceeded maximum allowed escalation depth (default 2).
- **Remedy**: Inspect `EscalationRecord` logs. Common causes include unresolvable upstream specification ambiguity or contradictory test assertions. Escalate to human operator.

### 4.3 Stale Context Detected (`StaleContextError`)
- **Symptom**: Inter-agent handoff or validation aborts with `StaleContextError`.
- **Cause**: Repository HEAD moved externally after context was assembled.
- **Remedy**: Invalidate assembled context, re-pull latest repository HEAD, and re-issue work order against clean baseline commit.

### 4.4 Model Swap Prohibition (`ModelSwapProhibitedError`)
- **Symptom**: Attempt to load alternative model fails with `ModelSwapProhibitedError`.
- **Cause**: Resident model `engineering/b0` is marked as a protected resident.
- **Remedy**: Do not attempt to swap models on the physical cluster. Use calibrated test doubles for non-resident architecture experiments.
