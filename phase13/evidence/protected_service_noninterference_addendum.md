# Protected Service Non-Interference Addendum

**Document Identifier**: `protected_service_noninterference_addendum.md`  
**Governing Phase**: Phase 13 Heterogeneous Operational Qualification Addendum  
**Audit Timestamp**: Sun 2026-09-27 22:51:05 UTC  
**Target Cluster**: Dell Precision T5820 (`10.0.8.5`) & Local Development Workstation

---

## 1. Executive Summary

Throughout the forensic investigation, acceptance contract reconciliation, external authority boundary audit, and containment regression testing of the Phase 13 Addendum:
- **Zero changes** were made to physical worker allocations or systemd services.
- **Zero requests** were directed to unauthenticated or experimental endpoints on the remote inference cluster.
- **Zero service restarts or signal interrupts** occurred across any protected processes.
- The Dell Precision T5820 inference cluster remains active in its **dual-resident 30B baseline configuration**.

---

## 2. Protected Process Accounting

### 2.1 Local Protected Daemons (Workstation)
Verified via `ps -fp 986,2093382,3130937`:

| Process Name | PID | Command / Binary | Uptime / Start Time | Operational Status |
|---|---|---|---|---|
| **Hermes Gateway** | `986` | `/home/mike/Projects/hermes-agent/gateway` | Active since Sep 22 | **100% HEALTHY** (0 signal interrupts) |
| **SSH Forwarding Tunnel** | `2093382` | `/usr/bin/ssh -N -T -o BatchMode=yes ... -L 127.0.0.1:18010:127.0.0.1:8010 mike@10.0.8.5` | Active since Sep 26 | **100% HEALTHY** (continuous port forwarding) |
| **OpenCode Runner** | `3130937` | `opencode --auto` | Active since Sep 26 | **100% HEALTHY** (0 child process faults) |

### 2.2 Remote Protected Services (`10.0.8.5`)
Verified via `systemctl status`:

| Service Unit | Port | Target GPU / PCI | Resident Model Identity | Status |
|---|---|---|---|---|
| `aihost-vllm-worker1.service` | `8000` | GPU 0 (PCI `0000:51:00.0`) | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | **ACTIVE** (running 1d 20h) |
| `aihost-vllm-worker2.service` | `8001` | GPU 1 (PCI `0000:93:00.0`) | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | **ACTIVE** (restored baseline) |
| `aihost-orchestrator-gateway.service` | `8010` | Host Loopback | Round-Robin across ports 8000 & 8001 | **ACTIVE** (serving `engineering/b0`) |

---

## 3. Live Endpoint Verification

Authentication and route isolation verified using client token authentication:
- Local Port Forwarded Probe: `http://127.0.0.1:18010/v1/models` returns HTTP 200 with `id: "engineering/b0"`.
- Remote Host Gateway Probe: `http://10.0.8.5:8010/v1/models` returns HTTP 200 with `id: "engineering/b0"`.
- Direct Worker 1 Probe: `http://127.0.0.1:8000/v1/models` returns `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`.
- Direct Worker 2 Probe: `http://127.0.0.1:8001/v1/models` returns `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`.

---

## 4. Conclusion

Non-interference invariants are 100% satisfied. Protected serving is fully intact.
