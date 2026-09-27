# Phase 6: Serving Topology Verification and Execution Reality Audit

## 1. Executive Summary

This document establishes the empirical serving topology and execution reality on the Dell Precision T5820 workstation for Phase 6 of the Autonomous Engineering System.

In accordance with Phase 6 Section 2 requirements:
- The exact physical and logical serving arrangement is audited and verified.
- The execution location and reality of Phi-4 is independently determined and documented without unsupported claims.
- The active T5820 autonomous-readiness campaign processes are verified undisturbed.
- Explicit inference tiers are established for real-repository execution.

---

## 2. Physical and Logical Serving Architecture

### 2.1 Hardware and Cluster Infrastructure
- **Host Workstation**: Dell Precision 5820 Workstation (Ubuntu 24.04 LTS / Linux x86_64).
- **Physical Accelerators**:
  - `worker-b65-0`: Intel Arc Pro B65 (PCIe `0000:51:00.0`, 32 GiB GDDR6, 31.89 GiB usable).
  - `worker-b65-1`: Intel Arc Pro B65 (PCIe `0000:93:00.0`, 32 GiB GDDR6, 31.89 GiB usable).
  - Total Physical VRAM: 63.78 GiB.
- **Remote Host / Inference Worker**: `10.0.8.5` connected via private virtual network.
  - Runtime: Podman rootless container runner (`aihost-runtime` user).
  - Acceleration: Intel OneAPI Level Zero driver (`/dev/dri/by-path`).

### 2.2 Active Physical Model Deployment
The host cluster serves exactly one live physical model endpoint:
- **Model Identifier**: `engineering/b0`
- **Underlying Checkpoint**: `Qwen/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` (located at `/var/lib/local-ai/models/hub/models--cyankiwi--Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` on `10.0.8.5`).
- **Serving Configuration**:
  - Worker 1: Podman container `vllm-xpu-tp1-worker1`, `ZE_AFFINITY_MASK=0`, Port 8000.
  - Worker 2: Podman container `vllm-xpu-tp1-worker2`, `ZE_AFFINITY_MASK=1`, Port 8001.
  - Orchestrator Gateway: `orchestrator_gateway` listening on `127.0.0.1:8010` (PID 742882 on `10.0.8.5`).
- **Local Access Forwarding**:
  - SSH Reverse Tunnel: PID 2093382 forwards `127.0.0.1:18010 -> 10.0.8.5:8010`.
  - Authentication: Bearer token at `/home/mike/.config/opencode/t5820-client-token`.
  - Local API Endpoint: `http://127.0.0.1:18010/v1/chat/completions`.
  - Live Endpoint Telemetry: Verified active and responding with low latency (<500ms for simple completions).

---

## 3. Independent Audit of Phi-4 Execution Reality

### 3.1 Audit Scope and Methods
To resolve whether Phi-4 executes via live local inference, remote API, or specialized adapter:
1. **Host Daemon Inspection**: Examined all listening TCP/UDP sockets (`ss -tln`, `ss -tlpn`).
2. **Process Table Audit**: Scanned all running processes on both the T5820 workstation and `10.0.8.5` for instances of `phi`, `vllm`, `ollama`, or `llama.cpp`.
3. **Storage & Model Hub Inspection**: Inspected `/var/lib/local-ai/models/hub`, `~/.cache/huggingface`, and local filesystem for Phi-4 weights or artifacts.
4. **Environment & API Key Inspection**: Audited environment variables for remote model providers (OpenAI, Azure, Anthropic, OpenRouter).

### 3.2 Audit Findings
| Audit Domain | Investigation Target | Empirical Finding | Authoritative Status |
| :--- | :--- | :--- | :--- |
| **Local Physical Serving** | Live Phi-4 daemon on B65 GPUs | No Phi-4 daemon, container, or socket exists on T5820 or `10.0.8.5`. | **NON-EXISTENT** |
| **Local Model Weights** | `microsoft/phi-4` or quantized GGUF/FP8 | Zero Phi-4 model files found in `/var/lib/local-ai/models` or `~/.cache`. | **NOT PRESENT** |
| **Remote Provider API** | External execution endpoint (Azure/OpenAI) | No remote API credentials or outbound endpoints configured. | **UNCONFIGURED** |
| **Phase 4 Qualification** | Nature of Phase 4 Phi-4 promotion | Empirical benchmark evaluation of offline candidate config. | **OFFLINE REGISTRY** |
| **Phase 5 Review Adapter** | Execution mode in Phase 5 pipeline | Simulated / calibrated adapter producing structured review reports. | **ADAPTER REPLAY** |

### 3.3 Authoritative Determination
- **Genuine Live Model Inference**: Currently available exclusively through `http://127.0.0.1:18010/v1` (`engineering/b0`, Qwen3-Coder 30B AWQ).
- **Physical Feasibility Barrier**: Simultaneous residency of Qwen3-Coder TP=2 (24.5 GiB/GPU) and Phi-4 FP8 (15.2 GiB) on 31.89 GiB physical B65 cards remains mathematically and physically impossible ($39.7\text{ GiB} > 31.89\text{ GiB}$, deficit $\Delta = -7.81\text{ GiB}$).
- **Phase 6 Policy**: In Phase 6, authoring and bounded repair tasks will run against the **genuine live physical model endpoint** (`engineering/b0`). For review, Phase 6 will contrast:
  1. Single-worker self-review bypass (control).
  2. Live homogeneous review via `engineering/b0` (live multi-turn physical inference).
  3. Calibrated specialist review adapter (strict schema-validated review).
  Under no circumstances will Phase 6 report Phi-4 as a live GPU-resident daemon without physical evidence.

---

## 4. Protected Campaign Preservation Audit

The protected T5820 autonomous-readiness campaign running on the workstation was verified before initiating Phase 6:

```
Active Campaign Processes:
  - Hermes Gateway: PID 986 (/home/mike/Projects/hermes-agent/.venv/bin/python -m hermes_cli.main gateway run)
    Status: RUNNING (CPU: 0.4%, RSS: ~209 MB)
  - OpenCode Runner: PID 3130937 (opencode --auto)
    Status: RUNNING (CPU: 4.1%, RSS: ~1.88 GB)
  - SSH Tunnel: PID 2093382 (ssh -N -T -L 127.0.0.1:18010:127.0.0.1:8010 mike@10.0.8.5)
    Status: RUNNING (CPU: 0.0%, RSS: ~9.5 MB)
```

No disruption, termination, signaling, or port conflict has occurred. All Phase 6 activities remain strictly isolated within `.worktrees/phase6-real-repo`.
