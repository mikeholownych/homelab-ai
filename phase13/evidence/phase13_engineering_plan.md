# Phase 13 Mandatory Engineering Plan: Heterogeneous Operational Qualification and Deployment Readiness

## 1. Executive Mission & Baseline Identity

Phase 13 establishes the operational qualification framework to evaluate whether a heterogeneous two-worker inference configuration improves the Autonomous Engineering System's real engineering delivery rate without compromising independent acceptance, authorization, isolation, or protected-service continuity.

### 1.1 Release Baseline & Prior Qualification
- **Prior Disposition**: `PHASE_12_PHYSICAL_MODEL_QUALIFICATION: PROVEN`
- **Release Commit**: `ac69c480a91c67169aea5a952e48ebbac7f425be`
- **Release Branch**: `phase12-physical-model-qualification`
- **Cumulative Regression Baseline**: 420 / 420 passing tests
- **Evidence Manifest**: 31 / 31 SHA-256 verified artifacts

### 1.2 Model & Worker Identifiers
- **Control Model (Lead Engineering Model)**:
  - Public ID: `engineering/b0`
  - Model Name: `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`
  - Pinned Revision: `4bd30395b72ea6045edd04806c4fea448d4467b3`
  - Weight VRAM: 16.85 GiB
  - Architecture: Qwen2 MoE (30B total, ~3.3B active parameters)
  - Max Context: 65,536 tokens
  - Role: Primary repository architect, multi-file implementation engineer, and fallback authority.
- **Candidate Model (Specialist Model)**:
  - Model Name: `Qwen/Qwen2.5-7B-Instruct-AWQ`
  - Pinned Revision: `b25037543e9394b818fdfca67ab2a00ecc7dd641`
  - Weight VRAM: 5.19 GiB
  - Architecture: Qwen2 Dense (7.61B parameters)
  - Max Context: 32,768 tokens
  - Role: Bounded specialist for unit test generation, structured output/OpenAPI synthesis, and tool call proposals.

---

## 2. Authoritative Physical Topology (Dell Precision T5820)

Live host verification via `xpu-smi discovery` and `lspci` resolves historical documentation discrepancies and establishes the authoritative hardware topology:

| Hardware Component | Device 0 (Worker 1) | Device 1 (Worker 2) |
|---|---|---|
| **Accelerator Card** | Intel Arc Pro B65 Graphics | Intel Arc Pro B65 Graphics |
| **Physical VRAM** | 32,768 MiB (31.89 GiB) | 32,768 MiB (31.89 GiB) |
| **Physical PCI BDF** | **`0000:51:00.0`** | **`0000:93:00.0`** |
| **Upstream Root Port / Bridge** | `0000:4e:00.0` (Bus 4e -> 4f bridge) | `0000:90:00.0` (Bus 90 -> 91 bridge) |
| **DRM Card Device** | `/dev/dri/card1` | `/dev/dri/card2` |
| **DRM Render Node** | `/dev/dri/renderD128` | `/dev/dri/renderD129` |
| **Level Zero Device Index** | `level_zero:0` (`ZE_AFFINITY_MASK=0`) | `level_zero:1` (`ZE_AFFINITY_MASK=1`) |
| **Active Service Unit** | `aihost-vllm-worker1.service` | `aihost-vllm-worker2.service` |
| **Container Name** | `vllm-xpu-tp1-worker1` | `vllm-xpu-tp1-worker2` |
| **Local Port** | `127.0.0.1:8000` | `127.0.0.1:8001` |
| **Public Route** | `engineering/b0` (via Gateway :8010) | `engineering/b0` (via Gateway :8010) |

---

## 3. Evaluation Hypotheses & Preregistered Criteria

### 3.1 Primary Metric
The primary evaluation metric is strictly defined as:
$$\text{Efficiency} = \mathbf{INDEPENDENTLY\_ACCEPTED\_ENGINEERING\_WORK\_PER\_HOUR}$$
Under no circumstances will raw decode token throughput be treated as an acceptable optimization target if it compromises independent acceptance or increases validator rejections.

### 3.2 Hypotheses
- **H1 (Specialist Throughput & Latency)**: For bounded specialist tasks (test suite synthesis, structured schema generation, AST mutations), the 7B dense candidate achieves $>35\text{ tokens/sec}$ and reduces task wall-clock latency by $\ge 50\%$ compared to the 30B MoE model.
- **H2 (Fair Control Parity)**: The apparent 3/12 acceptance rate of the 30B control in Phase 12 was an artifact of unconstrained conversational preambles colliding with the 1,024-token ceiling. When supplied with an explicit code-first prompt and a realistic completion budget ($\ge 2,048$ tokens), the 30B control achieves $\ge 90\%$ independent acceptance.
- **H3 (Heterogeneous Concurrency Benefit)**: Serving `Qwen3-Coder-30B` on Worker 1 and `Qwen2.5-7B` on Worker 2 delivers $>25\%$ higher accepted engineering projects per hour under concurrent multi-agent workloads than homogeneous dual-30B serving.
- **H4 (Fail-Closed Capability Routing)**: A capability-aware scheduler with deterministic fallback preserves 100% authority containment, prevents retry loops, and incurs zero cross-tenant contamination.

### 3.3 Quantitative Acceptance Criteria (FROZEN)
1. **Engineering Acceptance Floor**:
   - First-pass acceptance $\ge 80.0\%$ for specialist tasks.
   - Final acceptance after bounded repair (max 2 retries) $\ge 95.0\%$.
2. **Operational Throughput Target**:
   - Heterogeneous accepted engineering tasks/hr $\ge 1.20\times$ baseline homogeneous throughput.
3. **Protected Service Non-Interference**:
   - Worker 1 uptime: 100% continuous.
   - Zero dropped requests or errors on production route `engineering/b0`.
   - Continuous uninterrupted execution of Hermes Gateway (PID `986`), SSH tunnel (PID `2093382`), and OpenCode Runner (PID `3130937`).
4. **Authority & Security Containment**:
   - 100% pass on all 16 mandatory adversarial security tests.
   - Zero unaccepted specialist deliverables admitted to integration boundaries.

---

## 4. Workstream Breakdown & Operational Boundaries

```
+---------------------------------------------------------------------------------------------------+
| PHASE 13 WORKSTREAM MAP                                                                           |
+-----------------------------------+---------------------------------------------------------------+
| Workstream A                      | Phase 12 Comparative Validity Audit                           |
| Workstream B                      | Fair Control Qualification (Code-First & Expanded Budget)     |
| Workstream C                      | Specialist Routing Contracts & Authority Containment          |
| Workstream D                      | Capability-Aware Scheduler & Fail-Closed Fallback             |
| Workstream E                      | Sustained Engineering Workload & Multi-Task Design            |
| Workstream F                      | Operational Performance & Work-Per-Hour Benchmarks            |
| Workstream G                      | Heterogeneous Physical Campaign & Maintenance Governance      |
| Workstream H                      | Production-Like Reliability, Fault Injection & Recovery       |
| Workstream I                      | Resource Capacity, VRAM Sizing & Hardware Contention          |
| Workstream J                      | Production Deployment Readiness Proposal                      |
+-----------------------------------+---------------------------------------------------------------+
```

### 4.1 Operating Authority Governance
- In accordance with Section 2 of the Phase 13 Charter, the agent is strictly prohibited from evicting either resident model or executing physical model replacement without explicit, separate human maintenance authorization.
- If physical heterogeneous evaluation requires swapping Worker 2, proposal [`MAINT-PROP-PHASE13-HETERO-GPU1`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase13/proposals/maint_prop_phase13_hetero_gpu1.md) will be prepared with pre-flight safety checks and stop at the authorization boundary.
- Non-disruptive control evaluations against the currently running baseline Worker 1 and Worker 2 are fully authorized.

---

## 5. Preregistered Qualification Gates (G1–G18)

- **G1**: Phase 12 baseline release commit (`ac69c48`) and evidence manifest verified.
- **G2**: Physical GPU and worker topology reconciled from live host hardware evidence.
- **G3**: Phase 12 comparative validity independently audited against raw traces.
- **G4**: Fair control configuration (code-first prompt + 2048 token budget) and criteria frozen.
- **G5**: Specialist routing contracts implemented, tested, and bound to immutable profiles.
- **G6**: Capability-aware fallback preserves authority, provenance, and prevents retry loops.
- **G7**: Sustained engineering workload cohort and independent validators verified.
- **G8**: Fair comparative evaluation completed between control and specialist candidate.
- **G9**: Physical heterogeneous campaign completed on authorized capacity (or blocked pending authorization).
- **G10**: Accepted engineering work per hour measured under sustained multi-agent operation.
- **G11**: Project-level acceptance and multi-task integration verified.
- **G12**: Resource, memory, thermal, and reliability limits satisfied.
- **G13**: Protected-service non-interference verified across all daemon processes.
- **G14**: Mandatory adversarial security test suite passes 100%.
- **G15**: Cumulative regression suite passes across all phases (Phases 0–13).
- **G16**: Evidence manifest verified via cryptographic SHA-256 digests.
- **G17**: Deployment-readiness proposal is evidence-supported and auditable.
- **G18**: Production promotion remains strictly separated and unauthorized.
