# Phase 12 Operational Runbook: Heterogeneous Model Serving & Maintenance

## 1. Scope & System Architecture

This operational runbook provides instructions for engineers and operators administering the Autonomous Engineering System's inference cluster on Dell Precision T5820 hardware (`10.0.8.5`).

### 1.1 Architecture Topology
- **Host**: `ai-5820-01` (10.0.8.5), Ubuntu 24.04 LTS, Kernel 7.0.0-34-generic
- **Accelerators**: 2x Intel Arc Pro B65 GPUs (PCI `0000:51:00.0`, `0000:93:00.0`), 32,656 MiB physical VRAM each.
- **Serving Daemon**: Podman rootless containers under service account `aihost-runtime`:
  - `vllm-xpu-tp1-worker1` pinned to GPU 0 (PCI `0000:51:00.0`), port `8000`.
  - `vllm-xpu-tp1-worker2` pinned to GPU 1 (PCI `0000:93:00.0`), port `8001`.
- **Proxy Gateway**: `orchestrator_gateway` (PID 742882) on port `8010`, load-balancing between workers.
- **Orchestration Workstation**: Local port `18010` forwarded via SSH tunnel (PID 2093382) to `10.0.8.5:8010`.

---

## 2. Cluster Health & Telemetry Verification

### 2.1 Verifying Physical Accelerators via XPU-SMI
```bash
ssh mike@10.0.8.5 "/usr/bin/xpu-smi discovery && /usr/bin/xpu-smi stats -d 0 && /usr/bin/xpu-smi stats -d 1"
```
Expect: Both devices report `normal` state, core frequency ~400 MHz idle / 2400 MHz active, memory allocation ~27,865 MiB.

### 2.2 Inspecting Podman Inference Containers
```bash
ssh mike@10.0.8.5 "cd /tmp && sudo -u aihost-runtime XDG_RUNTIME_DIR=/run/user/999 podman ps"
```
Expect: `vllm-xpu-tp1-worker1` and `vllm-xpu-tp1-worker2` status `Up`.

### 2.3 Endpoint Responsiveness Probe
```bash
curl -s http://127.0.0.1:18010/v1/models -H "Authorization: Bearer $(cat /home/mike/.config/opencode/t5820-client-token)"
```
Expect: HTTP 200 with model list including `engineering/b0`.

---

## 3. Human-Authorized Procedure: Deploying Topology B (7B Specialist)

*EXECUTE ONLY UPON EXPLICIT HUMAN AUTHORIZATION.*

### Step 1: Pre-Maintenance Health Verification
Confirm Worker 1 on GPU 0 is fully healthy and handling requests:
```bash
ssh mike@10.0.8.5 "curl -s http://127.0.0.1:8000/v1/models"
```

### Step 2: Backup Existing Configuration
```bash
ssh mike@10.0.8.5 "sudo cp /etc/local-ai/vllm/worker2/vllm-config.yaml /etc/local-ai/vllm/worker2/vllm-config.yaml.bak"
```

### Step 3: Deploy Candidate Configuration
```bash
ssh mike@10.0.8.5 "sudo bash -c 'cat <<EOF > /etc/local-ai/vllm/worker2/vllm-config.yaml
model: /models/hub/models--Qwen--Qwen2.5-7B-Instruct-AWQ/snapshots/b25037543e9394b818fdfca67ab2a00ecc7dd641
revision: b25037543e9394b818fdfca67ab2a00ecc7dd641
host: 0.0.0.0
port: 8001
tensor-parallel-size: 1
gpu-memory-utilization: 0.85
max-model-len: 32768
enforce-eager: false
api-key: gzA6fTtFePl9kNlrkEMYA9RCki5U6DjZcm7KcEMnsDY
enable-auto-tool-choice: true
tool-call-parser: hermes
served-model-name: Qwen/Qwen2.5-7B-Instruct-AWQ
EOF'"
```

### Step 4: Restart Worker 2 Container
```bash
ssh mike@10.0.8.5 "cd /tmp && sudo -u aihost-runtime XDG_RUNTIME_DIR=/run/user/999 podman restart vllm-xpu-tp1-worker2"
```

### Step 5: Await Warm-Up and Verify
```bash
ssh mike@10.0.8.5 "curl -s http://127.0.0.1:8001/v1/models -H \"Authorization: Bearer gzA6fTtFePl9kNlrkEMYA9RCki5U6DjZcm7KcEMnsDY\""
```
Expect HTTP 200 with `Qwen/Qwen2.5-7B-Instruct-AWQ`. Verify VRAM allocation drops from 27.8 GiB to ~7.2 GiB via `xpu-smi stats -d 1`.

---

## 4. Emergency Rollback Procedure (Restore Baseline in < 2 Minutes)

If Worker 2 fails to start, throws driver errors, or produces degraded outputs:

```bash
# 1. Stop Worker 2 immediately
ssh mike@10.0.8.5 "cd /tmp && sudo -u aihost-runtime XDG_RUNTIME_DIR=/run/user/999 podman stop vllm-xpu-tp1-worker2"

# 2. Restore verified baseline config
ssh mike@10.0.8.5 "sudo cp /etc/local-ai/vllm/worker2/vllm-config.yaml.bak /etc/local-ai/vllm/worker2/vllm-config.yaml"

# 3. Start baseline Worker 2 container
ssh mike@10.0.8.5 "cd /tmp && sudo -u aihost-runtime XDG_RUNTIME_DIR=/run/user/999 podman start vllm-xpu-tp1-worker2"

# 4. Verify baseline restoration
ssh mike@10.0.8.5 "curl -s http://127.0.0.1:8001/v1/models"
```
Verify port 8001 returns `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`.
