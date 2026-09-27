# Maintenance Proposal: Controlled Worker 2 Heterogeneous Deployment

## Proposal ID: `MAINT-PROP-PHASE13-HETERO-GPU1`
**Proposal Status**: `STOPPED_PENDING_EXPLICIT_HUMAN_AUTHORIZATION`
**Created At**: 2026-09-27T21:42:00Z
**Author**: Principal Autonomous Engineering Agent
**Target Host**: Dell Precision T5820 (`10.0.8.5`)
**Target Accelerator**: GPU 1 (PCI BDF `0000:93:00.0`, Intel Arc Pro B65 32GB)
**Target Service**: `aihost-vllm-worker2.service` (`vllm-xpu-tp1-worker2`)

---

## 1. Justification & Scope

In accordance with Phase 13 Workstream G and Section 11, physical operational qualification of the heterogeneous dual-worker inference topology requires deploying the physically qualified specialist model `Qwen/Qwen2.5-7B-Instruct-AWQ` on Worker 2 while preserving Worker 1 as the protected resident lead engineering model (`cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`).

Because the Phase 12 maintenance experiment was bounded and terminated with full baseline restoration, a new, explicit human maintenance authorization is mandatory before any physical modification to Worker 2.

In strict obedience to Section 2 and Section 11, **this proposal is prepared and locked at the authorization boundary. No container or service state will be altered without explicit human approval.**

---

## 2. Target Component & Topology Specification

| Configuration Dimension | Current Baseline State | Proposed Maintenance State |
|---|---|---|
| **Host System** | Dell Precision T5820 (`10.0.8.5`) | Dell Precision T5820 (`10.0.8.5`) |
| **Worker Unit** | `aihost-vllm-worker2.service` | `aihost-vllm-worker2.service` |
| **Container Name** | `vllm-xpu-tp1-worker2` | `vllm-xpu-tp1-worker2` |
| **Physical PCI BDF** | **`0000:93:00.0`** (DRM `/dev/dri/card2`) | **`0000:93:00.0`** (DRM `/dev/dri/card2`) |
| **Upstream Root Port** | `0000:90:00.0` (Bus 90 -> 91 bridge) | `0000:90:00.0` (Bus 90 -> 91 bridge) |
| **Level Zero Device** | `level_zero:1` (`ZE_AFFINITY_MASK=1`) | `level_zero:1` (`ZE_AFFINITY_MASK=1`) |
| **Target Model** | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | `Qwen/Qwen2.5-7B-Instruct-AWQ` |
| **Pinned Revision** | `4bd30395b72ea6045edd04806c4fea448d4467b3` | `b25037543e9394b818fdfca67ab2a00ecc7dd641` |
| **Artifact Snapshot** | `/var/lib/local-ai/models/hub/models--cyankiwi...` | `/var/lib/local-ai/models/hub/models--Qwen...` |
| **Baseline Config SHA** | `641c9402ebbc56f5d599512894f72a02304fd66...` | Staged Candidate Config |
| **Serving Port** | `127.0.0.1:8001` (Baseline Gateway Round-Robin) | `127.0.0.1:8001` (Isolated Specialist Route) |
| **Gateway Port 8010** | Dual-worker round robin | Pinned exclusively to Worker 1 (8000) |

---

## 3. Mandatory Pre-Maintenance Safety Gates

Prior to any execution of this proposal, the following 4 pre-flight safety gates must be completed and verified:
1. **Production Route Pinning**: Update `/etc/local-ai/orchestrator/gateway.env` to pin `ORCHESTRATOR_GATEWAY_WORKER_PORTS="8000 "` and restart gateway. Verify 100% of production traffic hits Worker 1.
2. **Active Campaign Drain**: Verify active autonomous engineering tasks under PID `3130937` have completed. Verify Worker 2 has 0 in-flight requests.
3. **Cryptographic Backup**: Create verified backups:
   - `/etc/local-ai/vllm/worker2/vllm-config.yaml.baseline-backup`
   - `/etc/local-ai/vllm/worker2/vllm.env.baseline-backup`
   - `/etc/local-ai/orchestrator/gateway.env.baseline-backup`
4. **Worker 1 Protection**: Verify Worker 1 remains untouched and 100% operational on GPU 0.

---

## 4. Deterministic Rollback Procedure (< 2 Minutes)

If maintenance is aborted, fails, or completes:
1. Stop Worker 2 container: `systemctl stop aihost-vllm-worker2.service`
2. Restore verified baseline configurations:
   ```bash
   cp /etc/local-ai/vllm/worker2/vllm-config.yaml.baseline-backup /etc/local-ai/vllm/worker2/vllm-config.yaml
   cp /etc/local-ai/vllm/worker2/vllm.env.baseline-backup /etc/local-ai/vllm/worker2/vllm.env
   cp /etc/local-ai/orchestrator/gateway.env.baseline-backup /etc/local-ai/orchestrator/gateway.env
   ```
3. Restart Worker 2: `systemctl start aihost-vllm-worker2.service`
4. Wait for readiness observer to record `READY` (< 300s).
5. Restart gateway: `systemctl restart aihost-orchestrator-gateway.service`.
6. Verify round-robin load balancing across both baseline workers.

---

## 5. Current Governance Determination

**STATUS: LOCKED / STOPPED PENDING EXPLICIT HUMAN AUTHORIZATION**

No command has been dispatched to modify Worker 2. The cluster remains in its baseline state.
