# Phase 7: Serving Topology Verification and Deployment Reconciliation

## 1. Executive Summary

This document establishes the authoritative, forensically audited serving topology record for Phase 7 of the Autonomous Engineering System, resolving prior ambiguities between "TP=2" descriptions and the "Dual-TP=1 Worker Gateway" architecture.

In accordance with Phase 7 Section 3:
1. Physical GPU inventory and VRAM allocations were inspected on the Dell Precision T5820 platform and remote inference node `10.0.8.5`.
2. Active worker processes, GPU affinity masks, and tensor-parallel settings were directly audited.
3. Gateway routing, credential separation, and OpenCode client configurations were examined and reconciled.
4. The execution reality of model endpoints was verified via authenticated HTTP probes.

---

## 2. Forensic Infrastructure Audit

### 2.1 Hardware and Physical Accelerators
- **Host Workstation**: Dell Precision 5820 Workstation (`Linux 6.8.0-52-generic x86_64`).
- **Target Inference Host**: `10.0.8.5` (connected via private network).
- **Physical Accelerators**:
  - `worker-b65-0`: Intel Arc Pro B65 (PCIe `0000:51:00.0`, 32 GiB GDDR6, 31.89 GiB usable).
  - `worker-b65-1`: Intel Arc Pro B65 (PCIe `0000:93:00.0`, 32 GiB GDDR6, 31.89 GiB usable).
  - Total Physical VRAM: 63.78 GiB across two physical B65 cards.

### 2.2 Serving Topology & Worker Processes
Audit of active processes on `10.0.8.5` demonstrates:
- **Worker 1**:
  - Container: `vllm-xpu-tp1-worker1`
  - Accelerator Assignment: GPU 0 (`ZE_AFFINITY_MASK=0`, `ONEAPI_DEVICE_SELECTOR=level_zero:0,1`)
  - Tensor Parallelism: `--tensor-parallel-size 1` (TP=1)
  - Listening Port: `0.0.0.0:8000`
  - Status: Active (running since Sep 26)
- **Worker 2**:
  - Container: `vllm-xpu-tp1-worker2`
  - Accelerator Assignment: GPU 1 (`ZE_AFFINITY_MASK=1`, `ONEAPI_DEVICE_SELECTOR=level_zero:0,1`)
  - Tensor Parallelism: `--tensor-parallel-size 1` (TP=1)
  - Listening Port: `0.0.0.0:8001`
  - Status: Active (running since Sep 26)
- **Model Checkpoint**:
  - `Qwen/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` (cached at `/var/lib/local-ai/models/hub/models--cyankiwi--Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`).
- **Orchestrator Gateway**:
  - Process: `/usr/bin/python3 -m orchestrator_gateway` (PID `742882` on `10.0.8.5`).
  - Listening Port: `127.0.0.1:8010`.
  - Function: Multiplexes and load-balances client requests across Worker 1 and Worker 2, enforcing OpenAI API contracts, request ID generation, and credential authentication.

---

## 3. Reconciliation of Prior Phase Reports

### 3.1 The "TP=2" vs "Dual-TP=1" Discrepancy
Earlier phase documentation colloquially referenced "TP=2" when discussing the two physical Arc Pro B65 cards. Forensic inspection reveals that:
- **Historical Context**: The initial baseline design considered a single vLLM instance spanning both cards via TP=2.
- **Production Architecture**: The actual operational deployment deployed on the platform is **Dual-TP=1**: two independent TP=1 vLLM container instances (one dedicated to GPU 0, one dedicated to GPU 1) managed behind the `orchestrator_gateway`.
- **OpenCode Configuration Confirmation**: Inspection of `/home/mike/.config/opencode/opencode.jsonc` confirms this authoritative nomenclature:
  ```jsonc
  "models": {
    "engineering/b0": {
      "name": "engineering/b0 (T5820 dual TP=1 gateway)",
      "limit": {
        "context": 65536,
        "output": 1024
      }
    }
  }
  ```

### 3.2 Gateway Authentication and Route Verification
- **Local Access Tunnel**: SSH reverse tunnel PID `2093382` forwards local port `127.0.0.1:18010` to remote `10.0.8.5:8010`.
- **Client Authentication**: Enforced via bearer token located at `/home/mike/.config/opencode/t5820-client-token`.
- **Authenticated Endpoint Verification**:
  ```bash
  $ curl -H "Authorization: Bearer <t5820-client-token>" http://127.0.0.1:18010/v1/models
  {"object":"list","data":[{"id":"engineering/b0","object":"model","owned_by":"aihost-orchestrator"}]}
  ```
- **Unauthenticated Probe**: Returns `{"error":{"message":"authentication required","type":"authentication_error"}}`.

---

## 4. Model Capabilities and Serving Boundaries

### 4.1 Physical Model: `engineering/b0`
- Available via authenticated endpoint `http://127.0.0.1:18010/v1`.
- Backed by two physical Intel Arc Pro B65 GPUs running dual TP=1 Qwen3-Coder-30B AWQ workers.
- Context window: 65,536 tokens; maximum output: 1,024 tokens.

### 4.2 Review Specialist: Phi-4 Reality
- Forensic scans of both the T5820 host and `10.0.8.5` verify that **no physical Phi-4 daemon or container is deployed**.
- Mathematical feasibility check confirms that dual residency of Qwen3-Coder (24.5 GiB) and Phi-4 FP8 (15.2 GiB) on a 31.89 GiB physical GPU exceeds physical memory capacity ($39.7 > 31.89$ GiB).
- In accordance with Phase 7 instructions: **Simulated or calibrated model outputs are strictly distinguished from physical model execution.** Physical execution is credited only to `engineering/b0`.

---

## 5. Protected Process Inventory

The following protected campaign processes are actively running on the workstation and must remain undisturbed:

| Process | PID | Command Line | Status |
| :--- | :---: | :--- | :--- |
| **Hermes Gateway** | `986` | `/home/mike/Projects/hermes-agent/.venv/bin/python -m hermes_cli.main gateway run` | Active |
| **OpenCode Runner** | `3130937` | `opencode --auto` | Active |
| **SSH Reverse Tunnel** | `2093382` | `/usr/bin/ssh -N -T -o BatchMode=yes -o ExitOnForwardFailure=yes -L 127.0.0.1:18010:127.0.0.1:8010 mike@10.0.8.5` | Active |

Phase 7 operations strictly adhere to zero-interference constraints.
