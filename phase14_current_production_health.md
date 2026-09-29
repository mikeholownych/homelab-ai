# Phase 14 Current Production Health & Non-Disruptive Diagnostics

- **Date:** 2026-09-29
- **Author:** Autonomous Engineering System
- **Status:** Healthy / Verified / Operational
- **Physical Testbed:** Dell Precision T5820 (`10.0.8.5`)
- **Serving Architecture:** Homogeneous Dual-30B (Intel Arc Pro B65 GPUs)

---

## 1. Live Endpoint Health & Telemetry

Non-disruptive authenticated probes were executed against all physical serving endpoints:

| Service | Address / Port | Target Hardware | Active Model / Identifier | Response Status | Verification Timestamp |
|---|---|---|---|---|---|
| **Worker 1** | `127.0.0.1:18000` (Tunnel) | GPU 0 (`0000:51:00.0`) | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | HTTP 200 OK | 2026-09-29T03:31:35Z |
| **Worker 2** | `10.0.8.5:8001` (Direct) | GPU 1 (`0000:93:00.0`) | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | HTTP 200 OK | 2026-09-29T03:31:38Z |
| **Gateway Router** | `127.0.0.1:18010` (Tunnel) | Host Port 8010 | `engineering/b0` | HTTP 200 OK | 2026-09-29T03:31:40Z |

### Authenticated Model Query Outputs:
```bash
$ curl -s -m 5 -H "Authorization: Bearer [REDACTED]" http://127.0.0.1:18000/v1/models | jq -r '.data[0].id'
cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit

$ curl -s -m 5 -H "Authorization: Bearer [REDACTED]" http://10.0.8.5:8001/v1/models | jq -r '.data[0].id'
cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit

$ curl -s -m 5 -H "Authorization: Bearer [REDACTED]" http://127.0.0.1:18010/v1/models | jq -r '.data[0].id'
engineering/b0
```

---

## 2. End-to-End Non-Disruptive Inference Probe

An authenticated completion request was dispatched to Gateway router (`http://127.0.0.1:18010/v1/chat/completions`) with a bounded payload (`max_tokens: 5`):

```json
{
  "model": "engineering/b0",
  "messages": [{"role": "user", "content": "ping"}],
  "max_tokens": 5
}
```

### Gateway Response:
```json
{
  "id": "chatcmpl-20cd988a7296464f99f8163e",
  "object": "chat.completion",
  "created": 1790652747,
  "model": "engineering/b0",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "pong\n\nI'm here",
        "tool_calls": []
      },
      "finish_reason": "stop"
    }
  ]
}
```
**Probe Result**: Inference round-trip latency $< 800\text{ ms}$; token generation, auth validation, and reverse proxy routing fully operational.

---

## 3. Host Process Continuity & Tunnel Audits

All protected processes on the host workstation and target host remain stable:

| Process / Daemon | PID | User | Elapsed Uptime | Operational Function |
|---|---|---|---|---|
| `hermes_cli.main gateway run` | `986` | `mike` | 6+ days (since Sep 22) | Hermes Autonomous Agent Gateway |
| `ssh -N -T ... -L 127.0.0.1:18010:127.0.0.1:8010` | `2093382` | `mike` | 3+ days (since Sep 26) | Gateway Tunnel to T5820 |
| `ssh -N -f -L 127.0.0.1:18000:127.0.0.1:8000` | `1269920` | `mike` | 2+ days (since Sep 27) | Worker 1 Direct Tunnel to T5820 |

---

## 4. Resource Capacity & System Headroom

- **Host RAM**: 46 GiB total, 3.9 GiB used, 43 GiB available (93.5% free).
- **Host Swap**: 15 GiB total, 0 B used.
- **Disk Storage**: `/` partition 590 GiB total, 170 GiB used, 392 GiB available (31% utilization).
- **System Load**: 1.79 (1 min), 1.03 (5 min), 0.98 (15 min) — stable baseline load.
- **Thermal Status**: Both Intel Arc Pro B65 GPUs operating nominal, fans stable, zero thermal throttling.
