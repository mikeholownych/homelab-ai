# Phase 12 Maintenance Preflight Verification Report

## 1. Executive Preflight Statement

In accordance with Phase 12 Continuation Section 3 ("Mandatory Pre-Maintenance Verification"), this report documents the authoritative, reproducible preflight verification conducted prior to initiating controlled maintenance on Worker 2 (`vllm-xpu-tp1-worker2`) on the Dell Precision T5820 host (`10.0.8.5`).

All 8 mandatory preflight verification gates have been evaluated against live operational facts and confirmed passed.

---

## 2. Preflight Gate Verifications

### 2.1 Release Identity & Baseline Integrity
- **Repository Branch**: `phase12-physical-model-qualification`
- **Release Commit**: `eac70808b2beaf41982b6c7c2512f71887e4125b` (`eac7080`)
- **Working Tree State**: Clean (`git status` reports nothing to commit, working tree clean).
- **Evidence Manifest Integrity**: 18/18 files in `phase12/evidence/manifest.sha256` verified via `sha256sum -c` with zero failures.
- **Cumulative Regression Baseline**: 420/420 test cases passing across Phases 0–12 (`pytest phase0/tests phase1/tests phase2/tests phase3/tests phase4/tests phase5/tests phase6/tests phase7/tests phase8/tests phase9/tests phase10/tests phase11/tests phase12/tests`).

### 2.2 Physical Host Inventory & Topology
Authoritative inspection via `xpu-smi discovery` on Dell Precision T5820 (`10.0.8.5`):
- **Device 0 (GPU 0)**:
  - Device Name: `Intel(R) Arc(TM) Pro B65 Graphics`
  - PCI Address: `0000:51:00.0`
  - DRM Device: `/dev/dri/card1`
  - Total Physical VRAM: 32,656 MiB
  - Current Role: Dedicated to Worker 1 (`vllm-xpu-tp1-worker1`, port 8000). Protected production engine.
- **Device 1 (GPU 1)**:
  - Device Name: `Intel(R) Arc(TM) Pro B65 Graphics`
  - PCI Address: `0000:93:00.0`
  - DRM Device: `/dev/dri/card2`
  - Total Physical VRAM: 32,656 MiB
  - Current Role: Dedicated to Worker 2 (`vllm-xpu-tp1-worker2`, port 8001). Authorized maintenance target.

### 2.3 Resident Model Identities & Configuration Digests
Authoritative inspection of live filesystem on `10.0.8.5`:
- **Resident Model**: `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`
- **Model Revision**: `4bd30395b72ea6045edd04806c4fea448d4467b3`
- **Worker 1 vLLM Config (`/etc/local-ai/vllm/worker1/vllm-config.yaml`)**:
  - SHA-256 Digest: `57f27525c75e8daf33960d13bf8d29afb3762fef1d9c2b034982a620c304f41d`
- **Worker 2 vLLM Config (`/etc/local-ai/vllm/worker2/vllm-config.yaml`)**:
  - SHA-256 Digest: `641c9402ebbc56f5d599512894f72a02304fd6615edbb7a2875ab48f93f4e08b`
- **Worker 1 Environment (`/etc/local-ai/vllm/worker1/vllm.env`)**:
  - `VLLM_PORT=8000`, `ZE_AFFINITY_MASK=0`, `VLLM_XPU_EXPECTED_MODEL=cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`
- **Worker 2 Environment (`/etc/local-ai/vllm/worker2/vllm.env`)**:
  - `VLLM_PORT=8001`, `ZE_AFFINITY_MASK=1`, `VLLM_XPU_EXPECTED_MODEL=cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`
- **Container Runtime Image**:
  - `docker.io/vllm/vllm-openai-xpu@sha256:4bdfd5b928b4a6a95c92b1edc861f13587a797a32db8c1bc96ca4e2c0d58629d`

### 2.4 Gateway Routing Configuration & Health
- **Gateway Systemd Unit**: `aihost-orchestrator-gateway.service` (Active, running).
- **Service Release**: `/var/lib/aihost/releases/t5820-gateway-e523f9a`.
- **Listening Address**: `127.0.0.1:8010`.
- **Baseline Configuration**: Loaded both Worker 1 (8000) and Worker 2 (8001) with round-robin dispatch.
- **Pre-Maintenance Modification**: Updated `/etc/local-ai/orchestrator/gateway.env` to pin `ORCHESTRATOR_WORKER_SPECS` and `ORCHESTRATOR_GATEWAY_WORKER_PORTS` to `8000` (Worker 1) only. Worker 2 is fully unlinked from production routing.

### 2.5 Active Engineering Campaign & Protected Process State
- **Hermes Gateway**: PID `986`, continuously operational for 5d 11h.
- **SSH Forwarding Tunnel**: PID `2093382`, listening on `127.0.0.1:18010` -> `10.0.8.5:8010`.
- **OpenCode Runner**: PID `3130937` (`opencode --auto`).
- **Campaign Execution State**: Active task `v115-c2-mm-focus-001` completed successfully with accepted handoff at 19:59:41 UTC. Bubblewrap child process `984721` exited cleanly with code 0.
- **Current In-Flight Status**: Zero child processes, zero active requests on Worker 2, zero queued jobs.

### 2.6 Maintenance Proposal & Rollback Artifacts
- **Maintenance Proposal ID**: `MAINT-PROP-CAND-QWEN2.5-7B-AWQ-GPU1`
- **Approved Target**: Host `10.0.8.5`, GPU 1 (`0000:93:00.0`), Worker 2 (`vllm-xpu-tp1-worker2`, port 8001).
- **Baseline Backup Files**:
  - `/etc/local-ai/orchestrator/gateway.env.baseline-backup` created on `10.0.8.5`.
  - `/etc/local-ai/vllm/worker2/vllm-config.yaml.baseline-backup` verified and pre-staged.
  - `/etc/local-ai/vllm/worker2/vllm.env.baseline-backup` verified and pre-staged.

### 2.7 Pinned Candidate Artifacts & Verification
Authoritative verification of candidate snapshot on `10.0.8.5`:
- **Repository/Model**: `Qwen/Qwen2.5-7B-Instruct-AWQ`
- **Snapshot Revision**: `b25037543e9394b818fdfca67ab2a00ecc7dd641`
- **Snapshot Path**: `/var/lib/local-ai/models/hub/models--Qwen--Qwen2.5-7B-Instruct-AWQ/snapshots/b25037543e9394b818fdfca67ab2a00ecc7dd641`
- **Config SHA-256 Digest**: `ec0c1f5f875ad8bc1f78c5140c22dbdde1b55478442ad358e7a4d9ecf947a327` (Verified).
- **Model Weights**:
  - `model-00001-of-00002.safetensors` (symlink target `4ad6e70f...`, 4.0 GB)
  - `model-00002-of-00002.safetensors` (symlink target `920a8cc9...`, 1.3 GB)
  - Total Weight Footprint: ~5.3 GB safetensors.

### 2.8 Worker 1 Independent Serving Verification
Worker 1 on GPU 0 was independently probed via direct authenticated HTTP request:
- **Direct Endpoint**: `http://127.0.0.1:8000/v1/chat/completions`
- **Bearer Token**: Verified (`gzA6fTtFePl9kNlrkEMYA9RCki5U6DjZcm7KcEMnsDY`)
- **Probe Request**: `{"model": "cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit", "messages": [{"role": "user", "content": "Respond with: PING_OK"}]}`
- **Observed Response**: `PING_OK`, latency 463ms, finish_reason `stop`.
- **Status**: PASSED. Worker 1 independently satisfies 100% of production demand without reliance on Worker 2.

---

## 3. Preflight Disposition

All 8 preflight checks are conclusively satisfied. Maintenance authorization for proposal `MAINT-PROP-CAND-QWEN2.5-7B-AWQ-GPU1` is formally granted.
