# Phase 12 Controlled Maintenance and Rollback Plan

## 1. Maintenance Scope & Executive Authorization Policy

This maintenance plan defines the controlled, non-disruptive procedure to transition the Dell Precision T5820 system from its current homogeneous serving topology (dual `engineering/b0`) into the qualified heterogeneous Topology B (`engineering/b0` on GPU 0 + `Qwen2.5-7B-Instruct-AWQ` on GPU 1).

### Mandatory Governance Policy:
In strict compliance with Operating Authority (Section 2) and Workstream H:
> **DO NOT EXECUTE THIS MAINTENANCE PROPOSAL WITHOUT EXPLICIT HUMAN AUTHORIZATION.**
> Approval to investigate candidate models does NOT constitute authorization to replace a resident model.
> The maintenance operation is **STOPPED PENDING EXPLICIT HUMAN AUTHORIZATION**.

---

## 2. Maintenance Specification & Target Artifact Identity

```
+---------------------------------------------------------------------------------------------------+
| MAINTENANCE PROPOSAL SPECIFICATION                                                               |
+------------------------------------+--------------------------------------------------------------+
| Proposal Identifier                | MAINT-PROP-CAND-QWEN2.5-7B-AWQ-GPU1                          |
| Target Accelerator                 | GPU 1 (Intel Arc Pro B65 Graphics, PCI 0000:93:00.0)         |
| Target Worker Service              | vllm-xpu-tp1-worker2 (Container ID: ce07755841bf)            |
| Target Model Identifier            | Qwen/Qwen2.5-7B-Instruct-AWQ                                 |
| Immutable Snapshot Revision        | b25037543e9394b818fdfca67ab2a00ecc7dd641                    |
| Local Model Disk Path              | /var/lib/local-ai/models/hub/models--Qwen--Qwen2.5-7B-Instruct-AWQ |
| Configuration Digest (config.json) | ec0c1f5f875ad8bc1f78c5140c22dbdde1b55478442ad358e7a4d9ecf947a327 |
| Expected Target Port               | 8001 (Internal container binding 0.0.0.0:8001)               |
| Expected VRAM Allocation           | 7,185.0 MiB (5,427 MiB weights + 1,024 overhead + 734 KV)    |
| Maximum Allowed Maintenance Window | 15 minutes                                                   |
| Current Operational Status         | STOPPED_PENDING_AUTHORIZATION                                |
+------------------------------------+--------------------------------------------------------------+
```

---

## 3. Service Interruption Scope & Protected Baseline Non-Interference

The maintenance procedure modifies **only GPU 1 and Worker 2**:
1. **Worker 1 (GPU 0) Invariant**: Worker 1 (`vllm-xpu-tp1-worker1` on port 8000) remains untouched, running continuously on GPU 0.
2. **Production Alias Preservation**: `orchestrator_gateway` (PID 742882) continues serving `engineering/b0` through Worker 1 without dropping client requests.
3. **Local Daemon Isolation**: Hermes Gateway (PID 986), OpenCode (PID 3130937), and the SSH forwarding tunnel (PID 2093382) experience zero downtime.

---

## 4. Pre-Maintenance Health Checks

Prior to executing any maintenance steps, the operator or automated gate must verify:
1. `GET http://127.0.0.1:18010/v1/models` returns HTTP 200 with `engineering/b0`.
2. GPU 0 memory allocation is stable at ~27,869 MiB with 0 errors.
3. Worker 1 process (`conmon` PID 2764, EngineCore PID 3389) is responsive.
4. Target model weights snapshot on disk matches SHA-256 digest `ec0c1f...`.
5. Backup configuration `/etc/local-ai/vllm/worker2/vllm-config.yaml.bak` is verified present.

---

## 5. Step-by-Step Deployment Procedure

*Note: Execution strictly contingent upon human authorization.*

### Step 1: Drain & Quiesce Worker 2
Notify orchestrator gateway to route 100% of traffic to Worker 1 on port 8000:
```bash
# On 10.0.8.5
sudo systemctl stop local-ai-vllm-worker2.service || sudo -u aihost-runtime XDG_RUNTIME_DIR=/run/user/999 podman stop vllm-xpu-tp1-worker2
```

### Step 2: Backup Existing Baseline Configuration
```bash
sudo cp /etc/local-ai/vllm/worker2/vllm-config.yaml /etc/local-ai/vllm/worker2/vllm-config.yaml.baseline-backup
```

### Step 3: Deploy Candidate Configuration
Update `/etc/local-ai/vllm/worker2/vllm-config.yaml` to configure `Qwen2.5-7B-Instruct-AWQ`:
```yaml
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
```

### Step 4: Restart Worker 2 Container
```bash
sudo systemctl start local-ai-vllm-worker2.service
```

### Step 5: Post-Deployment Verification Probe
Poll target endpoint until healthy (max 120s):
```bash
curl -s http://127.0.0.1:8001/v1/models -H "Authorization: Bearer gzA6fTtFePl9kNlrkEMYA9RCki5U6DjZcm7KcEMnsDY"
```
Expect HTTP 200 with model ID `Qwen/Qwen2.5-7B-Instruct-AWQ`.

### Step 6: Post-Deployment Physical Qualification
Execute the 4 calibration tasks against Worker 2. If all 4 pass automated unit tests, maintenance is marked **COMPLETED**.

---

## 6. Rollback Triggers & Immediate Recovery Procedure

### 6.1 Deterministic Rollback Triggers
Execution MUST immediately halt and initiate rollback if ANY of the following occur:
1. Container exits with non-zero status or fails to start within 120 seconds.
2. GPU 1 throws Level Zero driver error or out-of-memory exception.
3. VRAM allocation exceeds 12,000 MiB (indicating memory leak or unquantized weights).
4. Independent engineering acceptance rate on calibration tasks is $< 90\%$.
5. Total maintenance duration exceeds 15 minutes.

### 6.2 Step-by-Step Rollback Execution
```bash
# 1. Stop candidate container
sudo systemctl stop local-ai-vllm-worker2.service

# 2. Restore verified baseline configuration
sudo cp /etc/local-ai/vllm/worker2/vllm-config.yaml.baseline-backup /etc/local-ai/vllm/worker2/vllm-config.yaml

# 3. Restart resident worker
sudo systemctl start local-ai-vllm-worker2.service

# 4. Confirm baseline restoration
curl -s http://127.0.0.1:8001/v1/models -H "Authorization: Bearer gzA6fTtFePl9kNlrkEMYA9RCki5U6DjZcm7KcEMnsDY"
```
Verify port 8001 returns `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`.
Restore dual-worker routing in orchestrator gateway.

---

## 7. Current Governance Disposition

- **Proposal Status**: **STOPPED PENDING HUMAN AUTHORIZATION**
- **Physical Host Safety**: Fully preserved; zero changes applied to host runtime files.
- **Rollback Feasibility**: Non-destructive, 100% reversible within 2 minutes.
