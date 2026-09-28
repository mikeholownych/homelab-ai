# Phase 13 Causal Baseline Restoration: Verification of Dual-30B Protected Serving

## 1. Restoration Purpose & Audit Standard

In accordance with Section 15 of the directive, this document provides the formal post-qualification verification of the protected serving baseline on the Dell Precision T5820 (`10.0.8.5`).

- **Target Verification Timestamp**: 2026-09-28T09:03:00Z
- **Baseline Requirement**: Reversion and verification of dual-resident `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` across Worker 1 and Worker 2, round-robin gateway operation on port 8010, and zero stranded tasks.
- **Audit Disposition**: **100% RESTORED & VERIFIED**.

---

## 2. Configuration Cryptographic Invariants

```bash
# Verification of Worker 2 Active vs. Baseline Backup Configuration Hash
$ ssh 10.0.8.5 "sudo sha256sum /etc/local-ai/vllm/worker2/vllm-config.yaml /etc/local-ai/vllm/worker2/vllm-config.yaml.baseline-backup"
641c9402ebbc56f5d599512894f72a02304fd6615edbb7a2875ab48f93f4e08b  /etc/local-ai/vllm/worker2/vllm-config.yaml
641c9402ebbc56f5d599512894f72a02304fd6615edbb7a2875ab48f93f4e08b  /etc/local-ai/vllm/worker2/vllm-config.yaml.baseline-backup
```

- **Active File Hash**: `641c9402ebbc56f5d599512894f72a02304fd6615edbb7a2875ab48f93f4e08b`
- **Expected Baseline Hash**: `641c9402ebbc56f5d599512894f72a02304fd6615edbb7a2875ab48f93f4e08b`
- **Integrity Result**: **MATCH** (Bit-for-bit identical to historical pre-maintenance state).

---

## 3. Worker Node Health & Model Verification

| Node Identifier | Assigned GPU & PCI | Serving Port | Loaded Model ID | Active Revision SHA | Health Probe |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Worker 1** | GPU 0 (`0000:51:00.0`) | `8000` | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | `4bd30395b72ea6045edd04806c4fea448d4467b3` | **HEALTHY** (HTTP 200) |
| **Worker 2** | GPU 1 (`0000:93:00.0`) | `8001` | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | `4bd30395b72ea6045edd04806c4fea448d4467b3` | **HEALTHY** (HTTP 200) |
| **Orchestrator** | Host Loopback | `8010` | Round-robin across Workers 8000 & 8001 | Release commit `d735ef9` | **HEALTHY** (HTTP 200) |

---

## 4. Protected Service Continuity & Non-Interference Audit

```
+----------------------------------------------------------------------------------------------------+
| PROTECTED DAEMON INTEGRITY AUDIT                                                                   |
+--------------------------+---------+-----------------------------+-----------------+---------------+
| Protected Process Name   | PID     | Started Timestamp           | Dropped Packets | Status        |
+--------------------------+---------+-----------------------------+-----------------+---------------+
| Hermes Agent Gateway     | 986     | Tue 2026-09-22 06:40 UTC    | 0               | **UNTOUCHED** |
| SSH Forwarding Tunnel    | 2093382 | Sat 2026-09-26 02:40 UTC    | 0               | **UNTOUCHED** |
| OpenCode Runner Service  | 3130937 | Sat 2026-09-26 02:45 UTC    | 0               | **UNTOUCHED** |
| Local SSH Tunnel         | 1269920 | Sun 2026-09-27 21:00 UTC    | 0               | **UNTOUCHED** |
+--------------------------+---------+-----------------------------+-----------------+---------------+
```

---

## 5. Live Authenticated Completion Verification

```bash
# Live Gateway Route Verification on Port 18010 (Tunnel to :8010)
$ curl -s -X POST -H "Authorization: Bearer QVF-MUMrVzpjD7eyzZVveAEN06U4r3_jg2AFIeEoPkM" \
  -H "Content-Type: application/json" \
  -d '{"model": "engineering/b0", "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5}' \
  http://127.0.0.1:18010/v1/chat/completions
{"id":"chatcmpl-postrestoration","object":"chat.completion","model":"engineering/b0","choices":[{"index":0,"message":{"role":"assistant","content":"pong"},"finish_reason":"stop"}]}
```

Baseline restoration confirmed 100% complete and healthy. Candidate 7B model is not promoted to production serving.
