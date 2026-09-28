# Phase 13 Configuration B Preflight Report: Protected-Service & Baseline Audit

## 1. Executive Summary & Verification Purpose

Prior to executing live production promotion of Configuration B scheduling, this preflight audit confirms the operational readiness, route isolation, and configuration baseline of the Dell Precision T5820 host (`10.0.8.5`).

- **Preflight Timestamp**: 2026-09-28T09:40:00Z
- **Target Host**: Dell Precision T5820 (`10.0.8.5`)
- **Governing Baseline**: Commit [`2c677a9`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization) on branch `phase13-heterogeneous-qualification`
- **Preflight Outcome**: **ALL 12 PREFLIGHT GATES SATISFIED** (System Clear for Promotion)

---

## 2. Mandatory Preflight Gate Register (Section 9 Audit)

```
+----------------------------------------------------------------------------------------------------+
| SECTION 9 PROTECTED-SERVICE PREFLIGHT AUDIT                                                        |
+-----+--------------------------------------+--------+----------------------------------------------+
| Gate| Requirement                          | Status | Empirical Verification / Evidence            |
+-----+--------------------------------------+--------+----------------------------------------------+
| P1  | Both 30B Workers Healthy             | PASSED | Worker 1 (:18000) & Worker 2 (:8001) HTTP 200|
| P2  | Authenticated Gateway Healthy        | PASSED | Gateway (:18010) HTTP 200 (engineering/b0)  |
| P3  | Current Routing & Scheduler State    | PASSED | CapabilityAwareScheduler active (Config B)   |
| P4  | No Unexpected Candidate Resident     | PASSED | Both workers serving 30B; 7B not resident    |
| P5  | Preserved Config Hashes              | PASSED | SHA-256: 641c9402ebbc56f5d599512894f72a02... |
| P6  | Verified Rollback Artifact           | PASSED | vllm-config.yaml.baseline-backup identical   |
| P7  | Verified Rollback Procedure          | PASSED | Instant mode reversion to CONFIGURATION_A    |
| P8  | Active Task Drain State              | PASSED | In-flight active_requests == 0               |
| P9  | Safe Transition Boundary             | PASSED | Clean boundary established between runs      |
| P10 | Protected Daemons Untouched          | PASSED | PIDs 986, 2093382, 3130937, 1269920 active   |
| P11 | Baseline Latency & Error Baseline    | PASSED | Turnaround: 196.24s, Errors: 0%              |
| P12 | Abort Safety (Zero Task Loss)        | PASSED | Stateless scheduling transition              |
+-----+--------------------------------------+--------+----------------------------------------------+
```

---

## 3. Physical Node & Model Identities

| Node Identifier | Hardware Address | Serving Port | Model Identifier | Pinned Snapshot Revision | Health Check |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Worker 1** | GPU 0 (`0000:51:00.0`) | `8000` (Tunnel `18000`) | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | `4bd30395b72ea6045edd04806c4fea448d4467b3` | **HEALTHY** (HTTP 200) |
| **Worker 2** | GPU 1 (`0000:93:00.0`) | `8001` | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | `4bd30395b72ea6045edd04806c4fea448d4467b3` | **HEALTHY** (HTTP 200) |
| **Gateway** | Host Loopback | `8010` (Tunnel `18010`) | `engineering/b0` | Round-robin across Workers 1 & 2 | **HEALTHY** (HTTP 200) |

---

## 4. Protected Daemon Status & Continuity

```
+----------------------------------------------------------------------------------------------------+
| PROTECTED DAEMON INTEGRITY AUDIT                                                                   |
+--------------------------+---------+-----------------------------+-----------------+---------------+
| Process Name             | PID     | Started Timestamp           | Dropped Packets | Status        |
+--------------------------+---------+-----------------------------+-----------------+---------------+
| Hermes Agent Gateway     | 986     | Tue 2026-09-22 06:40 UTC    | 0               | **UNTOUCHED** |
| SSH Forwarding Tunnel    | 2093382 | Sat 2026-09-26 02:40 UTC    | 0               | **UNTOUCHED** |
| OpenCode Runner Service  | 3130937 | Sat 2026-09-26 02:45 UTC    | 0               | **UNTOUCHED** |
| Local SSH Tunnel         | 1269920 | Sun 2026-09-27 21:00 UTC    | 0               | **UNTOUCHED** |
+--------------------------+---------+-----------------------------+-----------------+---------------+
```

---

## 5. Live Endpoint Response Verification

```bash
# Worker 1 Authoritative Model Response
GET http://127.0.0.1:18000/v1/models
HTTP/1.1 200 OK
{"object":"list","data":[{"id":"cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit","root":".../snapshots/4bd30395b72ea6045edd04806c4fea448d4467b3"}]}

# Worker 2 Physical Model Response
GET http://10.0.8.5:8001/v1/models
HTTP/1.1 200 OK
{"object":"list","data":[{"id":"cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit","root":".../snapshots/4bd30395b72ea6045edd04806c4fea448d4467b3"}]}

# Gateway Authenticated Response
POST http://127.0.0.1:18010/v1/chat/completions
HTTP/1.1 200 OK
{"id":"chatcmpl-...","model":"engineering/b0","choices":[{"message":{"content":"pong"}}]}
```

Preflight audit confirms 100% compliance with Section 9. Promotion may proceed.
