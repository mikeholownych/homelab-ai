# Phase 14 Experiment 02: Preflight and Baseline Identity Verification

## 1. Executive Preflight Disposition

Before running any sustained multi-project experimental workloads, all preflight gates and operational boundaries mandated by Phase 14 Experiment 02 were audited and unconditionally verified.

```
PHASE_14_EXPERIMENT_02_PREFLIGHT: PASSED
```

---

## 2. Preflight Checklist and Audit Trail

| Audit Dimension | Target Requirement | Verified Evidence / Value | Status |
|---|---|---|---|
| **1. Canonical Repository & HEAD** | `mikeholownych/homelab-ai` on `main` | Commit [`a8c3b6a1a4c27f391f28ebdf5a74c1bfd1d148ce`](https://github.com/mikeholownych/homelab-ai/commit/a8c3b6a1a4c27f391f28ebdf5a74c1bfd1d148ce) | PASSED |
| **2. Canonical CI Status** | Workflow `quality` on remote `main` | GitHub Actions Run `36518246209` (`conclusion: success`) | PASSED |
| **3. Evidence Manifest Integrity** | Phase 12, 13, and 14 Experiment 01 | Phase 12: 31/31 OK<br>Phase 13: 129/129 OK<br>Phase 14: 16/16 OK | PASSED |
| **4. Configuration B Source Identity** | Certified baseline scheduler | [`CapabilityAwareScheduler`](file:///home/mike/Projects/aihost/phase13/src/autonomous_engineering/heterogeneous/capability_scheduler.py) (`SchedulingMode.CONFIGURATION_B`) | PASSED |
| **5. Configuration B+ Source Identity** | Isolated rebalanced scheduler | [`RebalancedScheduler`](file:///home/mike/Projects/aihost/phase14/src/autonomous_engineering/pipeline_rebalancing/rebalanced_scheduler.py) (`ExtendedSchedulingMode.CONFIGURATION_B_PLUS`) | PASSED |
| **6. Production Default Invariance** | Experimental mode cannot be default | Default in both schedulers is strictly `CONFIGURATION_B`; B+ requires explicit opt-in parameter | PASSED |
| **7. Physical Model Identities** | Homogeneous dual-30B AWQ MoE | Worker 1: `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`<br>Worker 2: `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | PASSED |
| **8. Gateway Authentication** | Bearer auth on port 18010 (:8010) | HTTP 200 returning `engineering/b0` (`aihost-orchestrator`) | PASSED |
| **9. External Validator Independence** | Independent, non-bypassable gates | AST verifier, JSON Schema draft-07, `ExternalAuthorityBoundary` | PASSED |
| **10. Protected Service Isolation** | PIDs undisturbed | Worker 1 PID 986, SSH Tunnel PID 2093382, Gateway PID 1269920 active | PASSED |
| **11. Host & Memory Headroom** | Ample host and GPU resources | Local host: 42 GiB free RAM, 392 GiB free disk (31% used)<br>Dell T5820 (10.0.8.5): 49 GiB free RAM, 55 GiB free disk (46% used) | PASSED |
| **12. Thermal & Interconnect Headroom** | Chassis operating within margins | GPU 0 & GPU 1 thermals $\le 62^\circ\text{C}$, dual PCIe Gen4 x16 lanes | PASSED |
| **13. Production Traffic Isolation** | Zero cross-contamination | Production routes to gateway port 8010; experimental traffic connects directly to worker test endpoints with dedicated tracking | PASSED |

---

## 3. Production Isolation Confirmation

No production requests enter the experimental queue.
All experimental tasks use explicit work IDs prefixed with `sust-b-` or `sust-bplus-` and carry cryptographic provenance tags.
The production gateway remains fully dedicated to serving production engineering requests on `http://127.0.0.1:18010`.
Safe isolation is demonstrated; no external maintenance window is required.
