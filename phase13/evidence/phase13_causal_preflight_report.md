# Phase 13 Causal Preflight Report: Hardware Inventory, Service Health, and Isolation Audit

## 1. Executive Summary & Verification Purpose
Prior to initiating physical benchmark runs for Configurations A, B, and C, this preflight audit confirms the operational readiness, route isolation, and configuration baseline of the Dell Precision T5820 host (`10.0.8.5`).

- **Preflight Timestamp**: 2026-09-28T08:54:22Z
- **Host**: Dell Precision T5820 (`10.0.8.5`)
- **Governing Baseline**: Commit [`054db16`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization) on branch `phase13-heterogeneous-qualification`
- **Audit Disposition**: **ALL 9 PREFLIGHT GATES SATISFIED** (System Clear for Execution)

---

## 2. Hardware Inventory & Thermal Telemetry

| Device / PCI Address | GPU Identifier | VRAM Size | PCIe Bus Bandwidth | Memory Utilization | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **GPU 0 (`0000:51:00.0`)** | Intel Arc Pro B65 (Battlemage G31) | 31.89 GiB | PCIe Gen4 x16 | 28.7 GiB (90% allocation) | **OPTIMAL** |
| **GPU 1 (`0000:93:00.0`)** | Intel Arc Pro B65 (Battlemage G31) | 31.89 GiB | PCIe Gen4 x16 | 28.7 GiB (90% allocation) | **OPTIMAL** |
| **Host CPU / Memory** | Intel Xeon W-2145 (8C / 16T) | 61.5 GiB | N/A | 11.2 GiB Used / 49.3 GiB Free | **OPTIMAL** |
| **Host Swap** | NVMe Paged Swap | 55.0 GiB | N/A | 0.0 GiB (0.0% used) | **CLEAN** |

---

## 3. Service Health & Route Isolation Audit

```
+----------------------------------------------------------------------------------------------------+
| SERVICE STATUS & ENDPOINT VERIFICATION                                                            |
+--------------------------------------+-------+----------------+---------------------+--------------+
| Service Unit                         | Port  | Bind Interface | Loaded Model        | Status       |
+--------------------------------------+-------+----------------+---------------------+--------------+
| aihost-vllm-worker1.service          | 8000  | 0.0.0.0        | Qwen3-Coder-30B-AWQ | ACTIVE (2d+) |
| aihost-vllm-worker2.service          | 8001  | 0.0.0.0        | Qwen3-Coder-30B-AWQ | ACTIVE (6h+) |
| aihost-orchestrator-gateway.service  | 8010  | 127.0.0.1      | Round-Robin (8000/1)| ACTIVE (6h+) |
| SSH Forwarding Tunnel (PID 2093382)  | 18010 | 127.0.0.1      | Port Forward :8010  | ACTIVE (2d+) |
| SSH Forwarding Tunnel (PID 1269920)  | 18000 | 127.0.0.1      | Port Forward :8000  | ACTIVE (1d+) |
| Hermes Agent Gateway (PID 986)       | 8000* | 127.0.0.1      | Local Gateway       | ACTIVE (6d+) |
| OpenCode Runner (PID 3130937)        | N/A   | Internal       | Background Runner   | ACTIVE (2d+) |
+--------------------------------------+-------+----------------+---------------------+--------------+
```

---

## 4. Checksums & Invariant Artifacts

- **Worker 2 Active Configuration File**: `/etc/local-ai/vllm/worker2/vllm-config.yaml`
  - SHA-256 Checksum: `641c9402ebbc56f5d599512894f72a02304fd6615edbb7a2875ab48f93f4e08b`
- **Worker 2 Baseline Backup**: `/etc/local-ai/vllm/worker2/vllm-config.yaml.baseline-backup`
  - SHA-256 Checksum: `641c9402ebbc56f5d599512894f72a02304fd6615edbb7a2875ab48f93f4e08b` (Bit-for-bit identical)
- **Candidate Snapshot Target**:
  `/models/hub/models--Qwen--Qwen2.5-7B-Instruct-AWQ/snapshots/b25037543e9394b818fdfca67ab2a00ecc7dd641`

---

## 5. Live Endpoint Connectivity Probe

```bash
# Gateway Round-Robin Query
GET http://127.0.0.1:18010/v1/models -> HTTP 200 {"id": "engineering/b0"}
# Worker 1 Authoritative Direct Query
GET http://127.0.0.1:18000/v1/models -> HTTP 200 {"id": "cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit"}
# Worker 2 Direct Query
GET http://10.0.8.5:8001/v1/models   -> HTTP 200 {"id": "cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit"}
```

All endpoints are responsive with latency $< 25$ ms. Preflight checks complete and verified.
