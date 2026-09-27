# Authoritative Worker & Hardware Topology Report (Dell Precision T5820)

## 1. Executive Summary & Resolution of Historical PCI Inconsistencies

During the audit of Phase 11 and Phase 12 documentation, an inconsistency was identified regarding the PCI address of Worker 1:
- Historical inventory documents cited PCI address `0000:91:00.0` for Worker 1.
- Final qualification reports cited PCI address `0000:91:00.0` for Worker 1 and `0000:93:00.0` for Worker 2.

To resolve this defect, an exhaustive physical hardware audit was conducted directly on host `10.0.8.5` using `xpu-smi discovery`, `lspci -tv`, and `/dev/dri/by-path`.

### Authoritative Resolution:
1. **GPU 0 (Physical Device 0 / Worker 1)**:
   - Upstream PCIe Root Complex: `0000:4e:00.0` (Sky Lake-E PCIe Root Port A)
   - Downstream PCI Bridge: `0000:4f:00.0` (Device e2ff)
   - Upstream Switch Ports: `0000:50:01.0`, `0000:50:02.0`
   - **Physical VGA / Compute Device BDF**: **`0000:51:00.0`**
   - Audio Subsystem BDF: `0000:52:00.0`
   - DRM Nodes: `/dev/dri/card1`, `/dev/dri/renderD128`
   - Level Zero Index: `0` (`ZE_AFFINITY_MASK=0`)
2. **GPU 1 (Physical Device 1 / Worker 2)**:
   - Upstream PCIe Root Complex: `0000:90:00.0` (Sky Lake-E PCIe Root Port A)
   - Downstream PCI Bridge: `0000:91:00.0` (Device e2ff)
   - Upstream Switch Ports: `0000:92:01.0`, `0000:92:02.0`
   - **Physical VGA / Compute Device BDF**: **`0000:93:00.0`**
   - Audio Subsystem BDF: `0000:94:00.0`
   - DRM Nodes: `/dev/dri/card2`, `/dev/dri/renderD129`
   - Level Zero Index: `1` (`ZE_AFFINITY_MASK=1`)

**Root Cause of Historical Inconsistency**: Prior reports mistakenly recorded the downstream PCI bridge `0000:91:00.0` (which sits on bus 91 between root port 90 and endpoint 93) as Worker 1's device address, when in fact Worker 1's physical endpoint is **`0000:51:00.0`** and Worker 2's physical endpoint is **`0000:93:00.0`**.

---

## 2. Complete Physical Topology & Serving Matrix

```
========================================================================================================
TOPOLOGY ATTRIBUTE       WORKER 1 (CONTROL)                          WORKER 2 (CONTROL BASELINE)
========================================================================================================
Host System              Dell Precision T5820 (Host IP: 10.0.8.5)   Dell Precision T5820 (Host IP: 10.0.8.5)
Host CPU                 Intel Xeon W-2145 (8 cores / 16 threads)    Intel Xeon W-2145 (8 cores / 16 threads)
Host RAM                 64 GB DDR4 ECC                              64 GB DDR4 ECC
GPU Hardware             Intel Arc Pro B65 Graphics (32GB)           Intel Arc Pro B65 Graphics (32GB)
Physical VRAM            32,768 MiB (31.89 GiB physical capacity)    32,768 MiB (31.89 GiB physical capacity)
Physical PCI BDF         0000:51:00.0                                0000:93:00.0
PCIe Generation / Width  PCIe Gen4 x16                               PCIe Gen4 x16
Root Complex Port        0000:4e:00.0                                0000:90:00.0
DRM Card Device          /dev/dri/card1                              /dev/dri/card2
DRM Render Node          /dev/dri/renderD128                         /dev/dri/renderD129
Level Zero Selector      level_zero:0,1                              level_zero:0,1
Level Zero Affinity      ZE_AFFINITY_MASK=0                          ZE_AFFINITY_MASK=1
Container Runtime        Podman (Rootless UID 999: aihost-runtime)   Podman (Rootless UID 999: aihost-runtime)
Container Name           vllm-xpu-tp1-worker1                        vllm-xpu-tp1-worker2
Systemd Unit             aihost-vllm-worker1.service                 aihost-vllm-worker2.service
Serving Port             127.0.0.1:8000                              127.0.0.1:8001
Gateway Integration      Port 8010 (Round-Robin)                     Port 8010 (Round-Robin)
Model Name               cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ   cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ
Model Revision           4bd30395b72ea6045edd04806c4fea448d4467b3   4bd30395b72ea6045edd04806c4fea448d4467b3
Config SHA-256           57f27525c75e8daf33960d13bf8d29afb3762fe...  641c9402ebbc56f5d599512894f72a02304fd66...
Current Allocation       27,869 MiB (85.3% utilized)                 27,697 MiB (84.8% utilized)
Weight Memory            16.85 GiB                                   16.85 GiB
KV Cache Token Memory    8.33 GiB (90,944 tokens)                    8.33 GiB (90,944 tokens)
========================================================================================================
```

---

## 3. Cryptographic & Operational Artifact Digests

All configuration, runtime, and model artifacts are cryptographically bound:

| Target Component | File / Resource Path | SHA-256 Digest | Status |
|---|---|---|---|
| **Worker 1 Config** | `/etc/local-ai/vllm/worker1/vllm-config.yaml` | `57f27525c75e8daf33960d13bf8d29afb3762fef1d9c2b034982a620c304f41d` | **VERIFIED** |
| **Worker 2 Config** | `/etc/local-ai/vllm/worker2/vllm-config.yaml` | `641c9402ebbc56f5d599512894f72a02304fd6615edbb7a2875ab48f93f4e08b` | **VERIFIED** |
| **Gateway Config** | `/etc/local-ai/orchestrator/gateway.env` | `16b7be5bbe4a189dc8730ae2726530820d78e7b13564631a693d332b454c0970` | **VERIFIED** |
| **vLLM XPU Image** | `docker.io/vllm/vllm-openai-xpu` | `sha256:4bdfd5b928b4a6a95c92b1edc861f13587a797a32db8c1bc96ca4e2c0d58629d` | **VERIFIED** |
| **Worker 1 Readiness** | `/var/lib/aihost/evidence/vllm-worker1-readiness.json` | Recorded `READY` (startup 391s) | **VERIFIED** |
| **Worker 2 Readiness** | `/var/lib/aihost/evidence/vllm-worker2-readiness.json` | Recorded `READY` (startup 251s) | **VERIFIED** |

---

## 4. Protected Service Health Audit

At time of qualification:
- **Worker 1**: Active and serving continuously since `Sat 2026-09-26 02:38:40 UTC` (uptime: **1 day 19+ hours**).
- **Worker 2**: Active and serving continuously since `Sun 2026-09-27 20:21:40 UTC`.
- **Hermes Gateway**: PID `986`, continuous uptime since `Sep 22 2026`.
- **SSH Forwarding Tunnel**: PID `2093382`, continuous uptime since `Sep 26 2026`.
- **OpenCode Autonomous Runner**: PID `3130937`, continuous execution since `Sep 26 2026`.
- **Orchestrator Gateway**: Active on `127.0.0.1:8010`, balancing requests across both workers.
