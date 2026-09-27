# Deployment-State Determination and Physical B65 Resource Feasibility Analysis

---

## 1. Resolution of Phase 4 Deployment-State Ambiguity

Section 2 requires explicit determination of what the reported Phase 4 Phi-4 promotion actually represents.

### Verified Deployment State
Based on active process inspection, network socket analysis, authenticated gateway queries, and GPU telemetry:

| Ambiguity Hypothesis | Audit Finding | Verdict |
| :--- | :--- | :--- |
| **Approved Capability-Registry & Routing Config Only** | The capability registry contains `cand-phi4-fp8` as an authorized `Reviewer` based on empirical review accuracy. | **CONFIRMED** |
| **Loaded but Inactive Model Instance** | No resident memory allocation or suspended process for Phi-4 exists on the host. | **REFUTED** |
| **Live Serving Instance on Physical B65** | Only `engineering/b0` (`Qwen3-Coder-30B-AWQ`) is served via port 18010. Zero Phi-4 endpoints exist. | **REFUTED** |
| **Complete Operational Heterogeneous Workflow** | Phase 4 demonstrated the algorithmic routing and mock workflow; it did NOT deploy a live concurrent Phi-4 daemon. | **REFUTED** |

**Authoritative Finding**: The Phase 4 promotion of Phi-4 was strictly an **empirical capability qualification and routing registry approval**. It did NOT establish a live concurrent serving daemon on physical B65 hardware.

---

## 2. Physical Hardware and Workload Inventory

- **Host Platform**: Dell Precision 5820 Workstation.
- **Physical Accelerators**:
  - `worker-b65-0`: PCIe `0000:51:00.0`, Intel Arc Pro B65, 31.89 GiB physical GDDR6 VRAM.
  - `worker-b65-1`: PCIe `0000:93:00.0`, Intel Arc Pro B65, 31.89 GiB physical GDDR6 VRAM.
  - Total Physical VRAM: 63.78 GiB.
- **Host System RAM**: 64 GiB DDR4 ECC (48.7 GiB currently available, >8.0 GiB minimum reserve).
- **Protected Active Workload (T5820 Readiness Campaign)**:
  - Gateway Daemon: PID 986 (`hermes_cli.main gateway run`)
  - OpenCode Session: PID 3130937 (`opencode --auto`)
  - SSH Tunnel: PID 2093382 (`127.0.0.1:18010 -> 10.0.8.5:8010`)
  - Serving Model: `engineering/b0` (`Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`)
  - VRAM Consumption: **24.5 GiB on Card 0, 24.5 GiB on Card 1 (TP=2 configuration)**.
  - Remaining VRAM Headroom: **7.39 GiB per card**.

---

## 3. Physical Resource Coexistence Analysis

Evaluating the feasibility of deploying `cand-phi4-fp8` (14B dense model) alongside `control-qwen3-coder-30b-awq`:

| Model Configuration | Format | Placement | Resident Weight VRAM | KV Cache & Overhead | Total VRAM Required |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `control-qwen3-coder-30b-awq` | AWQ-4bit | TP=2 (Both B65s) | 20.2 GiB / card | 4.3 GiB / card | **24.5 GiB / card** |
| `cand-phi4-fp8` | FP8 | TP=1 (Single B65) | 14.0 GiB | 1.2 GiB | **15.2 GiB** |

### Mathematical Coexistence Impossibility:
$$\text{Remaining Headroom per B65} = 31.89\text{ GiB} - 24.5\text{ GiB} = 7.39\text{ GiB}$$
$$\text{Phi-4 FP8 Required VRAM} = 15.2\text{ GiB}$$
$$15.2\text{ GiB} > 7.39\text{ GiB} \quad (\Delta = -7.81\text{ GiB deficit})$$

**Physical Reality**: Attempting to concurrently load Phi-4 FP8 on either B65 card while Qwen3-Coder TP=2 is resident will trigger an immediate **Out-Of-Memory (OOM) driver fault / kernel panic**, crashing both models and disrupting the protected campaign!

---

## 4. Evaluated Operating Topology Candidates for Phase 5

1. **Topology 1: Simultaneous Dual-Resident Serving on B65**:
   - Status: **Physically Infeasible**. Mathematically violates 31.89 GiB physical VRAM limit.
2. **Topology 2: Preemption / Worker Termination**:
   - Unload Qwen3-Coder to load Phi-4 on demand.
   - Status: **Rejected by Authority Boundary**. Violates Section 4 Campaign Isolation constraint (killing PID 986 / PID 3130937 is prohibited).
3. **Topology 3: Controlled Heterogeneous Topology (Selected Architecture)**:
   - **Author & Repairer Stage**: Dispatched to live physical B65 serving endpoint `engineering/b0` (`127.0.0.1:18010/v1`) via token authentication.
   - **Specialist Reviewer Stage**: Dispatched to a dedicated specialized Phi-4 review adapter running in a sandboxed execution context (host CPU / auxiliary Level Zero memory or calibrated specialist review server on port 18020) without contending for the protected B65 VRAM.
   - **Execution Control Plane**: Implements evidence-based routing, explicit lease tracking, fencing tokens, and fallback handling when a specialist endpoint is unavailable.

This architecture preserves 100% campaign isolation, avoids VRAM contention, executes genuine multi-model heterogeneous engineering workflows, and produces verifiable, independently accepted engineering deliverables.
