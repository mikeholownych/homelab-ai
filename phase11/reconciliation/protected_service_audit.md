# Phase 11 Protected Service Non-Interference Audit

## 1. Executive Summary

This audit establishes authoritative evidence of protected service non-interference throughout the Phase 11 qualification reconciliation and the Level D real-inference comparative campaign. 

In accordance with strict operating boundaries, protected services on both the local orchestration host and the remote Dell Precision T5820 accelerator host (`10.0.8.5`) were monitored continuously. At no point during testing, demonstration execution, or live model inference were any protected processes interrupted, signaled, restarted, or evicted.

---

## 2. Protected Service Inventory and Baseline Monitoring

Stable service identities, process boundaries, and resource utilization profiles were established prior to execution and verified post-execution.

### 2.1 Local Orchestration Host Services

| Service Name | PID | Command / Executable Path | Start Time | Status | CPU Time | Resident Memory (RSS) | Virtual Memory (VSZ) | Signal Count |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Hermes Gateway** | `986` | `/home/mike/Projects/hermes-agent/.venv/bin/python -m hermes_cli.main gateway run` | Sep 22 | `Ssl` (Running) | 38:03 | 209.6 MiB | 1,236.2 MiB | 0 |
| **OpenCode Runner** | `3130937` | `opencode --auto` | Sep 26 | `Sl+` (Running) | 58:05 | 1,163.5 MiB | 78,973.7 MiB | 0 |
| **SSH Forwarding Tunnel** | `2093382` | `/usr/bin/ssh -N -T -o BatchMode=yes -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=yes -L 127.0.0.1:18010:127.0.0.1:8010 mike@10.0.8.5` | Sep 26 | `Ss` (Running) | 0:02 | 9.5 MiB | 16.5 MiB | 0 |

### 2.2 Remote Physical Inference Workers (`10.0.8.5`)

The remote host runs two containerized vLLM workers managed by Podman under service account `aihost-runtime`.

| Worker Identity | Podman Container ID | Pinned GPU | PCI Identifier | Conmon PID | EngineCore PID | Pinned Port | Resident Memory | Start Time | Restart Count |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **`vllm-xpu-tp1-worker1`** | `00b04abc9e05` | GPU 0 (Arc Pro B65) | `0000:51:00.0` | `2764` | `3389` | `8010` (`18010` local) | 27,869 MiB VRAM / 4.4 GiB RAM | Sep 26 2026 | 0 |
| **`vllm-xpu-tp1-worker2`** | `ce07755841bf` | GPU 1 (Arc Pro B65) | `0000:93:00.0` | `2768` | `3390` | `8011` (`18011` local) | 27,861 MiB VRAM / 4.4 GiB RAM | Sep 26 2026 | 0 |

---

## 3. Operational Safety Envelopes During Comparative Campaign

To ensure zero risk of worker degradation or memory thrashing during the Level D comparative evaluation against live worker 1 (`10.0.8.5:8010` via `127.0.0.1:18010`):

1. **Strict Concurrency Bound ($N=1$)**:
   All comparative queries were issued strictly sequentially. No concurrent connections or parallel prompt batches were initiated against the inference worker.
2. **Bounded Context & Token Generation**:
   Prompts were bounded to $< 1,000$ tokens, and `max_tokens` was capped at 1,024. The actual maximum response generated was 380 tokens.
3. **No Configuration or Model Swapping**:
   No eviction commands, SIGHUP reloads, or model parameter alterations were issued to Podman or the host kernel.
4. **Isolated Test Execution Workspace**:
   Unit tests, adversarial test suites, and reconciliation scripts executed purely in user-space scratch directories without writing to daemon socket paths or container mounts.

---

## 4. Verification Evidence

### 4.1 Process Stability Verification
Repeated polling of process statuses confirmed identical start times, process group IDs, and continuously incrementing CPU seconds without any process death or respawn:
- Local PID `986`: Start time Sep 22, State `Ssl`, unperturbed.
- Local PID `3130937`: Start time Sep 26, State `Sl+`, unperturbed.
- Local PID `2093382`: Start time Sep 26, State `Ss`, unperturbed.
- Remote PIDs `2713`, `2725`, `2769`, `2772`, `3389`, `3390`: Continuous uptime since launch on Sep 26.

### 4.2 Endpoint Responsiveness Verification
Direct HTTP probes before, during, and after the campaign confirmed 100% availability:
- **Baseline Probe**: `GET http://127.0.0.1:18010/v1/models` -> HTTP 200 (Model: `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`)
- **Comparative Campaign Execution**: 8 completion requests -> 8 successful responses (HTTP 200, 0 timeouts, 0 errors)
- **Post-Campaign Health Probe**: `GET http://127.0.0.1:18010/v1/models` -> HTTP 200

---

## 5. Audit Disposition

- **Protected Local Daemons**: Undisturbed, zero signals, zero restarts (**VERIFIED**).
- **Protected Remote Inference Workers**: Undisturbed, zero restarts, memory allocation stable at ~27.86 GiB per GPU (**VERIFIED**).
- **Network Tunnel Integrity**: Undisturbed, zero connection drops (**VERIFIED**).
- **Audit Conclusion**: Complete non-interference achieved. All operations adhered to the protected-service governance boundaries.
