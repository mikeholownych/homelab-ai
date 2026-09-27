# Phase 12 Baseline Verification & Host Topology Report

## 1. Executive Summary

This report establishes the verified baseline state for Phase 12 (Physical Model Qualification and Heterogeneous Inference). 

The baseline rests upon the successfully reconciled Phase 11 release (commit [`70c0313`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization)) on branch `phase11-qualification-reconciliation`. All historical evidence, regression suites, and physical host configurations have been independently inspected, audited, and verified prior to introducing Phase 12 components.

---

## 2. Phase 11 Release Baseline Verification

| Attribute | Expected Baseline Specification | Verified Operational Value | Verification Method / Evidence |
| :--- | :--- | :--- | :--- |
| **Git Branch** | `phase11-qualification-reconciliation` | `phase11-qualification-reconciliation` | `git branch --show-current` |
| **Base Commit** | `70c0313` | `70c0313aebfc39e43cd93161c106ad8af2e6ff72` | `git log -n 1 --oneline` |
| **Commit Message** | Reconcile qualification evidence and verify live campaign | Matches official release message | Git commit object inspection |
| **Cumulative Test Suite** | 364 passing across Phases 0–11 | **364 passed in 169.46s (100%)** | `pytest phase0/tests ... phase11/tests` |
| **Evidence Manifest** | 23 files verified | **23 / 23 OK (100%)** | `sha256sum -c phase11/reconciliation/manifest.sha256` |
| **Historical Manifest**| 14 files verified | **14 / 14 OK (100%)** | `sha256sum -c phase11/evidence/manifest.sha256` |
| **Phase 11 Disposition**| `PROVEN` | `PHASE_11_EVIDENCE_DRIVEN_OPTIMIZATION: PROVEN` | Reconciled release report signoff |

---

## 3. Physical Accelerator and Host Topology Audit

Authoritative hardware interrogation was executed directly against Dell Precision T5820 node `10.0.8.5` (`ai-5820-01`) using kernel diagnostics and `xpu-smi`.

### 3.1 Host System Architecture
- **Hostname**: `ai-5820-01`
- **Chassis**: Dell Precision T5820 Workstation
- **Operating System**: Ubuntu 24.04 LTS
- **Kernel Version**: `7.0.0-34-generic #34-Ubuntu SMP PREEMPT_DYNAMIC`
- **Level Zero Driver Version**: `17012470`

### 3.2 Physical GPU Device Topology

```
+---------------------------------------------------------------------------------------------------+
| Dell Precision T5820 Workstation (ai-5820-01, 10.0.8.5)                                            |
|                                                                                                   |
|  +-------------------------------------------+     +-------------------------------------------+  |
|  | GPU 0: Intel Arc Pro B65 Graphics         |     | GPU 1: Intel Arc Pro B65 Graphics         |  |
|  | PCI Address: 0000:51:00.0 (card1)        |     | PCI Address: 0000:93:00.0 (card2)        |  |
|  | Physical VRAM: 32,656.00 MiB (31.89 GiB)  |     | Physical VRAM: 32,656.00 MiB (31.89 GiB)  |  |
|  | Max Allocatable: 31,023.20 MiB            |     | Max Allocatable: 31,023.20 MiB            |  |
|  | Active VRAM: 27,869 MiB (85% Util)        |     | Active VRAM: 27,861 MiB (85% Util)        |  |
|  | Pinned Worker: vllm-xpu-tp1-worker1       |     | Pinned Worker: vllm-xpu-tp1-worker2       |  |
|  | Container Port: 8000                      |     | Container Port: 8001                      |  |
|  | Resident Model: Qwen3-Coder-30B-AWQ-4bit  |     | Resident Model: Qwen3-Coder-30B-AWQ-4bit  |  |
|  | Context Window: 65,536 tokens             |     | Context Window: 65,536 tokens             |  |
|  +-------------------------------------------+     +-------------------------------------------+  |
|                                            \         /                                            |
|                               +---------------------------+                                       |
|                               | Local Orchestrator Gateway|                                       |
|                               | Binding: 127.0.0.1:8010   |                                       |
|                               | Service PID: 742882       |                                       |
|                               +---------------------------+                                       |
+---------------------------------------------|-----------------------------------------------------+
                                              | Forwarded via SSH Tunnel (PID 2093382)
                                              v
                      Local Endpoint: http://127.0.0.1:18010/v1
```

### 3.3 Physical GPU Specifications
- **Device Count**: 2 physical discrete GPUs
- **Model Identity**: Intel(R) Arc(TM) Pro B65 Graphics (Device ID: `0xe222`, Stepping `A0`, Production ES)
- **PCI BDF Addresses**: `0000:51:00.0` (GPU 0), `0000:93:00.0` (GPU 1)
- **Execution Units**: 160 EUs per GPU, 5 Slices, 4 Sub-slices per slice, 8 threads/EU
- **Clock Frequencies**: Core Clock: 2400 MHz base / 400 MHz idle; Media Clock: 400 MHz idle
- **Total Physical Memory**: 32,656.00 MiB (31.8906 GiB / 34.24 GB decimal) per GPU
- **Max Allocatable Memory**: 31,023.20 MiB per GPU
- **Aggregate System VRAM**: 65,312.00 MiB (63.78 GiB) across both GPUs

---

## 4. Protected Serving Environment & Process Inventory

### 4.1 Remote Host Services (`10.0.8.5`)
- **Worker 1 (`vllm-xpu-tp1-worker1`)**:
  - Container ID: `00b04abc9e05` (Podman, user `aihost-runtime`)
  - Image: `docker.io/vllm/vllm-openai-xpu@sha256:4bdfd5b928b4a6a95c92b1edc861f13587a797a32db8c1bc96ca4e2c0d58629d`
  - EngineCore PID: `3389`
  - Resident VRAM: 27,869 MiB
  - Model Path: `/models/hub/models--cyankiwi--Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit/snapshots/4bd30395b72ea6045edd04806c4fea448d4467b3`
  - Listening Port: `0.0.0.0:8000`
  - Status: Up 41+ hours, 0 restarts
- **Worker 2 (`vllm-xpu-tp1-worker2`)**:
  - Container ID: `ce07755841bf` (Podman, user `aihost-runtime`)
  - Image: `docker.io/vllm/vllm-openai-xpu@sha256:4bdfd5b928b4a6a95c92b1edc861f13587a797a32db8c1bc96ca4e2c0d58629d`
  - EngineCore PID: `3390`
  - Resident VRAM: 27,861 MiB
  - Model Path: `/models/hub/models--cyankiwi--Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit/snapshots/4bd30395b72ea6045edd04806c4fea448d4467b3`
  - Listening Port: `0.0.0.0:8001`
  - Status: Up 41+ hours, 0 restarts
- **Orchestrator Gateway**:
  - Host PID: `742882` (`/usr/bin/python3 -m orchestrator_gateway`)
  - User: `aihost-runtime`
  - Listening Port: `127.0.0.1:8010`
  - Uptime: 1 day, 5 hours

### 4.2 Local Orchestration Workstation Services
- **Hermes Gateway**: PID `986`, command `/home/mike/Projects/hermes-agent/.venv/bin/python -m hermes_cli.main gateway run`, uptime 5 days 11 hours.
- **OpenCode Runner**: PID `3130937`, command `opencode --auto`, uptime 1 day 0 hours.
- **SSH Forwarding Tunnel**: PID `2093382`, command `/usr/bin/ssh -N -T ... -L 127.0.0.1:18010:127.0.0.1:8010 mike@10.0.8.5`, uptime 1 day 9 hours.

---

## 5. Local Model Disk Inventory (`/var/lib/local-ai/models/hub`)

Inspection of the remote storage array identified four model repositories stored locally:

| Model Hub Identifier | Snapshot Revision Digest | Architecture & Format | Weight Size on Disk | Supported Context | Target Role / Suitability |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | `4bd30395b72ea6045edd04806c4fea448d4467b3` | `qwen2` (AWQ 4-bit GEMM) | 16.8 GB (5 safetensors) | 65,536 tokens | **Protected Resident Control** (`engineering/b0`) |
| `Qwen/Qwen2.5-7B-Instruct-AWQ` | `b25037543e9394b818fdfca67ab2a00ecc7dd641` | `Qwen2ForCausalLM` (AWQ 4-bit) | 5.3 GB (2 safetensors) | 32,768 tokens | Fast Specialist / Tool Calling candidate |
| `cyankiwi/Qwen3.8-27B-AWQ-INT4` | `6e134bae811fb5adac50ee042ae5f029ac6779aa` | `qwen3_5` multimodal (compressed) | 14.8 GB (5 safetensors) | 262,144 tokens | Experimental long-context candidate |
| `casperhansen/llama-3.3-70b-instruct-awq` | `64d255621f40b42adaf6d1f32a47e1d4534c0f14` | `LlamaForCausalLM` (AWQ 4-bit) | 38.6 GB (9 safetensors) | 131,072 tokens | Large candidate (requires TP=2) |

---

## 6. Baseline Verification Disposition

- **Phase 11 Reconciled Release**: **VERIFIED INTACT**
- **Cumulative Regression Health**: **VERIFIED (364/364 PASSING)**
- **Protected Service Non-Interference**: **VERIFIED (ZERO INTERRUPTIONS)**
- **Host Topology & Physical Limits**: **VERIFIED (2x 32,656 MiB Intel Arc Pro B65 GPUs)**
- **Baseline Readiness**: **AUTHORIZED TO PROCEED TO PHASE 12**
