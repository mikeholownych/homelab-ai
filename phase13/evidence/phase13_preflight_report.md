# Phase 13 Preflight Verification Report

**Document Identifier**: `phase13_preflight_report.md`  
**Host Target**: Dell Precision T5820 (`ai-5820-01`, `10.0.8.5`)  
**Timestamp**: 2026-09-27T22:04:40Z  
**Preflight Disposition**: `ALL_GATES_PASSED_READY_FOR_ISOLATION`  

---

## 1. Release Baseline & Manifest Integrity

- **Branch**: `phase13-heterogeneous-qualification`
- **HEAD Commit**: `69a7257f742f629bed37a0c49b2fcbc4b0bace55`
- **Phase 13 Manifest Verification**: 18/18 artifacts verified OK against `phase13/evidence/manifest.sha256`.
- **Phase 12 Manifest Verification**: 31/31 artifacts verified OK against `phase12/evidence/manifest.sha256`.
- **Working Tree State**: Clean.

---

## 2. Remote Worker & Hardware Topology Verification

Physical inspection performed via authenticated loopback on `10.0.8.5`:

| Component | Target Identity | Verified Physical State | Status |
|---|---|---|---|
| **GPU 0** | Intel Arc Pro B65 (32GB) | PCI BDF `0000:51:00.0`, Level Zero `0`, `/dev/dri/card1` | PASS |
| **Worker 1** | `aihost-vllm-worker1.service` | Port `8000`, Model `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`, Uptime > 1d 19h | PASS |
| **GPU 1** | Intel Arc Pro B65 (32GB) | PCI BDF `0000:93:00.0`, Level Zero `1`, `/dev/dri/card2` | PASS |
| **Worker 2** | `aihost-vllm-worker2.service` | Port `8001`, Model `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`, Uptime > 1d 19h | PASS |
| **Gateway** | `aihost-orchestrator-gateway.service` | Port `8010`, Round-robin active across workers 8000 and 8001 | PASS |

Configuration SHA-256 Checksums on Host `10.0.8.5`:
- Worker 2 Config (`/etc/local-ai/vllm/worker2/vllm-config.yaml`): `641c9402ebbc56f5d599512894f72a02304fd6615edbb7a2875ab48f93f4e08b`
- Worker 1 Config (`/etc/local-ai/vllm/worker1/vllm-config.yaml`): `57f27525c75e8daf33960d13bf8d29afb3762fef1d9c2b034982a620c304f41d`
- Gateway Env (`/etc/local-ai/orchestrator/gateway.env`): `16b7be5bbe4a189dc8730ae2726530820d78e7b13564631a693d332b454c0970`

---

## 3. Active Campaign & Worker 2 Drain Audit

1. **In-Flight Requests**:
   - `vllm:num_requests_running`: `0.0`
   - `vllm:num_requests_waiting`: `0.0`
2. **Host Protected Processes**:
   - Hermes Gateway (PID `986`): Active, uptime > 5 days.
   - SSH Tunnel (PID `2093382`): Active, port forwarding `127.0.0.1:18010 -> 10.0.8.5:8010`.
   - OpenCode Autonomous Runner (PID `3130937`): Active, 0 active child bwrap sandbox processes.
3. **Drain Gate Conclusion**: Worker 2 is completely idle and ready for immediate isolation.

---

## 4. Candidate Artifact Verification

The target candidate model artifacts exist on local persistent storage at `10.0.8.5`:
- Pinned Snapshot Path: `/var/lib/local-ai/models/hub/models--Qwen--Qwen2.5-7B-Instruct-AWQ/snapshots/b25037543e9394b818fdfca67ab2a00ecc7dd641`
- `config.json` SHA-256: `ec0c1f5f875ad8bc1f78c5140c22dbdde1b55478442ad358e7a4d9ecf947a327`
- Verified Weights: 4-bit AWQ safetensors present, verified during Phase 12 qualification.

---

## 5. Rollback Preparedness

- Backup paths verified and writeable on target host:
  - `/etc/local-ai/vllm/worker2/vllm-config.yaml.baseline-backup`
  - `/etc/local-ai/vllm/worker2/vllm.env.baseline-backup`
  - `/etc/local-ai/orchestrator/gateway.env.baseline-backup`
- Rollback load time estimated: ~270s.
- Time limit budget: 15 minutes hard ceiling.

**PREFLIGHT DISPOSITION: PASS**. Ready to proceed with Step 2 (Production Route Isolation & Workload Drain).
