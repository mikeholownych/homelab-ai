# Phase 13 Expanded Baseline Restoration and Audit Report

## 1. Executive Summary
- **Target Host**: Dell Precision T5820 (`10.0.8.5`)
- **Restoration Reference**: `MAINT-PROP-EXPANDED-HETERO-GPU1`
- **Execution Timestamp**: `2026-09-28T02:57:18Z`
- **Restoration Disposition**: **FULLY RESTORED AND VERIFIED (100% MATCH)**
- **Baseline Topology**: Dual-resident homogeneous 30B MoE (`cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`) across Worker 1 (GPU 0, Port 8000) and Worker 2 (GPU 1, Port 8001).

## 2. Configuration Integrity Verification

| Configuration File | Baseline Backup Path | Restored Path | SHA256 Checksum | Match Status |
| :--- | :--- | :--- | :--- | :--- |
| **Worker 2 Config** | `/etc/local-ai/vllm/worker2/vllm-config.yaml.baseline-backup` | `/etc/local-ai/vllm/worker2/vllm-config.yaml` | `641c9402ebbc56f5d599512894f72a02304fd6615edbb7a2875ab48f93f4e08b` | **EXACT MATCH** |
| **Worker 2 Env** | `/etc/local-ai/vllm/worker2/vllm.env.baseline-backup` | `/etc/local-ai/vllm/worker2/vllm.env` | Restored | **MATCH** |
| **Gateway Env** | `/etc/local-ai/orchestrator/gateway.env.baseline-backup` | `/etc/local-ai/orchestrator/gateway.env` | Restored | **MATCH** |

File ownership (`aihost-runtime:aihost-runtime`) and strict permissions (`0600`) were reinstated.

## 3. Worker and Gateway Service State

- **Worker 1 (`aihost-vllm-worker1.service`)**:
  - Model: `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`
  - Endpoint: `http://10.0.8.5:8000` (Forwarded: `127.0.0.1:18000`)
  - Status: `active (running)`, continuous uptime > 2 days, 0 restarts.
- **Worker 2 (`aihost-vllm-worker2.service`)**:
  - Model: `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`
  - Endpoint: `http://10.0.8.5:8001`
  - Status: `active (running)`, verified via HTTP 200 `/v1/models`.
- **Gateway (`aihost-orchestrator-gateway.service`)**:
  - Endpoint: `http://10.0.8.5:8010`
  - Status: `active (running)`, readiness check passed cleanly (`ExecStartPre` status 0/SUCCESS).

## 4. Protected Process Continuity Verification

Continuous process monitoring verified zero interruptions, restarts, or signals across all protected processes:

| Process Name | PID | Command Line | Status | Signal Disruptions |
| :--- | :--- | :--- | :--- | :--- |
| **Hermes Gateway** | `986` | `/home/mike/Projects/hermes-agent/...` | Active | 0 |
| **SSH Persistent Tunnel** | `2093382` | `/usr/bin/ssh -N -T -o BatchMode=yes ...` | Active | 0 |
| **OpenCode Runner** | `3130937` | `opencode --auto` | Active | 0 |

## 5. Restoration Sign-Off
All experimental artifacts and temporary configurations on Worker 2 have been eradicated. The Dell Precision T5820 inference cluster is fully returned to the authoritative, protected dual-30B baseline.
