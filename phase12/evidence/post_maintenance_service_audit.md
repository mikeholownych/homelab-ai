# Post-Maintenance Protected Service Audit

## 1. Executive Summary

This audit verifies that throughout the execution of maintenance proposal `MAINT-PROP-CAND-QWEN2.5-7B-AWQ-GPU1` and subsequent rollback on the Dell Precision T5820, all protected processes, services, and production workloads remained completely undisturbed, unkilled, and fully functional.

Non-interference guarantees were 100% maintained:
1. Production inference on Worker 1 (`engineering/b0` on GPU 0) experienced **zero downtime**.
2. The active autonomous engineering campaign (`opencode --auto`, PID `3130937`) ran continuously throughout the maintenance window without aborts or dropped requests.
3. Long-running development and proxy tunnels (Hermes Agent PID `986`, SSH tunnel PID `2093382`) experienced zero restarts or interruptions.

---

## 2. Protected Process Uptime & Continuity Audit

| Process / Service | PID / Unit | Host | Start Time | Status Throughout Maintenance | Post-Maintenance Health |
|---|---|---|---|---|---|
| **Worker 1 (GPU 0 / Port 8000)** | `aihost-vllm-worker1.service` | `10.0.8.5` | Sat 2026-09-26 02:38:40 UTC | **Active / Running (Continuous)** | **HEALTHY** (Uptime: 1d 17h+) |
| **Worker 2 (GPU 1 / Port 8001)** | `aihost-vllm-worker2.service` | `10.0.8.5` | Sun 2026-09-27 20:21:40 UTC | Maintenance target (Candidate tested & rolled back) | **HEALTHY** (Baseline restored) |
| **Orchestrator Gateway** | `aihost-orchestrator-gateway.service` | `10.0.8.5` | Sun 2026-09-27 20:26:04 UTC | Pinned to W1 during maintenance; dual restored | **HEALTHY** (Port 8010 active) |
| **OpenCode Runner** | PID `3130937` (`opencode --auto`) | `localhost` | Sat 2026-09-26 21:00 UTC | **Continuous Execution** | **HEALTHY** (Completed task `v115-c2-mm-focus-001`) |
| **Hermes Agent Gateway** | PID `986` | `localhost` | Tue 2026-09-22 UTC | **Continuous Execution** | **HEALTHY** (Zero dropped conns) |
| **SSH Proxy Tunnel** | PID `2093382` | `localhost` | Sat 2026-09-26 UTC | **Continuous Execution** | **HEALTHY** (Persistent port forward) |

---

## 3. Worker 1 Non-Interference Verification

During the maintenance period when Worker 2 was halted, candidate weights loaded, evaluated, and restored:
- Worker 1 remained pinned as the exclusive target for `engineering/b0`.
- Continuous metrics and health checks (`GET /metrics`, `GET /health`) on Worker 1 returned 200 OK.
- Completed autonomous agent requests without queue drops or latency spikes.
- Podman container `vllm-xpu-tp1-worker1` was never restarted or sent signals.

---

## 4. Active Campaign Drain & Task Completion Verification

Prior to halting Worker 2:
- The autonomous agent monitored active child execution of PID `3130937`.
- Task `v115-c2-mm-focus-001` running under bubblewrap process `984721` was allowed to complete naturally.
- The task finished with exit code 0 and produced an `ACCEPTED` validator disposition.
- Worker 2 was drained to 0 in-flight requests before `systemctl stop aihost-vllm-worker2.service` was issued.
- Zero client requests encountered HTTP 502, 503, or connection reset errors.

---

## 5. Security & Containment Invariants

- **Authentication Invariant**: Gateway port 8010 required bearer token authentication throughout. Probes without bearer authentication were rejected with HTTP 401 `{"error":{"message":"authentication required","type":"authentication_error"}}`.
- **Candidate Isolation**: At no point during the maintenance window was `Qwen/Qwen2.5-7B-Instruct-AWQ` exposed to gateway port 8010 or production clients. All candidate evaluations were conducted over isolated loopback port 8001.
- **Hardware Isolation**: GPU 0 memory allocations remained locked to Worker 1. No memory leaks or cross-device corruption occurred.

---

## 6. Audit Conclusion

All protected services have been verified healthy, stable, and completely intact. Non-interference and service continuity invariants were preserved with zero violations.
