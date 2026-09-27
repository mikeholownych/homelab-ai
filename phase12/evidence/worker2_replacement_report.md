# Worker 2 Controlled Replacement Execution Report

## 1. Executive Summary

In accordance with Section 7 of the Phase 12 Continuation instructions, this report documents the controlled replacement of the resident model on Worker 2 (`vllm-xpu-tp1-worker2`) on the Dell Precision T5820 host (`10.0.8.5`).

The resident model `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` on GPU 1 was safely stopped, GPU 1 memory resources were verified released, and the pinned candidate `Qwen/Qwen2.5-7B-Instruct-AWQ` was loaded and brought to `READY` status on isolated port 8001.

Worker 1 on GPU 0 remained fully online, untouched, and actively serving 100% of production `engineering/b0` traffic throughout the operation.

---

## 2. Chronological Execution Log

| Timestamp (UTC) | Action | Target / Context | Result |
|---|---|---|---|
| `2026-09-27T20:02:13Z` | Production Gateway Reconfiguration | `/etc/local-ai/orchestrator/gateway.env` | Pinned to Worker 1 (`8000`), Worker 2 excised. |
| `2026-09-27T20:02:18Z` | Production Route Isolation Probe | `http://127.0.0.1:8010/v1/chat/completions` | 3/3 requests dispatched exclusively to Worker 1. |
| `2026-09-27T20:03:00Z` | Configuration Backup | `/etc/local-ai/vllm/worker2/` | Created `vllm-config.yaml.baseline-backup` and `vllm.env.baseline-backup`. |
| `2026-09-27T20:03:03Z` | Worker 2 Service Halt | `systemctl stop aihost-vllm-worker2.service` | Service stopped cleanly (code=exited, status=143). |
| `2026-09-27T20:03:04Z` | GPU 1 Memory Deallocation Check | `xpu-smi stats -d 1` | GPU Memory Used dropped to **42 MiB** (100% freed). |
| `2026-09-27T20:03:11Z` | Candidate Configuration Staged | `/etc/local-ai/vllm/worker2/vllm-config.yaml` | Pinned snapshot `b25037543e9394b818fdfca67ab2a00ecc7dd641`. |
| `2026-09-27T20:03:12Z` | Worker 2 Service Launch | `systemctl start aihost-vllm-worker2.service` | Container `vllm-xpu-tp1-worker2` created and attached. |
| `2026-09-27T20:04:24Z` | Model Weights Loaded | Intel Arc Pro B65 GPU 1 | Loading safetensors shards completed in **2.99 seconds** (5.19 GiB). |
| `2026-09-27T20:05:00Z` | Torch Compile & JIT Warmup | Intel Level Zero / XPU backend | AOT compiled graph cached in 31.24s; JIT warmup in 0.74s. |
| `2026-09-27T20:05:03Z` | KV Cache Allocation | GPU 1 VRAM | Available KV cache: 20.47 GiB (383,296 tokens; 11.70x concurrency @ 32k context). |
| `2026-09-27T20:05:28Z` | FastAPI Application Startup | Port 8001 listener | HTTP server initialized. |
| `2026-09-27T20:05:32Z` | Readiness Observer Verification | `/usr/local/libexec/local-ai-vllm-readiness` | Observed status `READY` at `2026-09-27T20:05:32Z`. |
| `2026-09-27T20:05:46Z` | Direct Candidate Inference Probe | `http://127.0.0.1:8001/v1/chat/completions` | Response: `CANDIDATE_LOAD_OK` (latency: 280ms). |
| `2026-09-27T20:05:50Z` | Production Gateway Non-Interference | `http://127.0.0.1:8010/v1/chat/completions` | Response: `WORKER1_STILL_HEALTHY` (handled by Worker 1). |

---

## 3. Authoritative Identity & Runtime Verification

### 3.1 Candidate Model Identity
Authoritative response from `http://127.0.0.1:8001/v1/models`:
```json
{
  "object": "list",
  "data": [
    {
      "id": "Qwen/Qwen2.5-7B-Instruct-AWQ",
      "object": "model",
      "root": "/models/hub/models--Qwen--Qwen2.5-7B-Instruct-AWQ/snapshots/b25037543e9394b818fdfca67ab2a00ecc7dd641",
      "max_model_len": 32768,
      "owned_by": "vllm"
    }
  ]
}
```

### 3.2 Systemd & Readiness State Record
File: `/var/lib/aihost/evidence/vllm-worker2-readiness.json`:
```json
{
  "schema_version": "1.0.0",
  "service": "vllm_xpu",
  "readiness_state": "READY",
  "process_started_at": "2026-09-27T20:03:12Z",
  "health_ready_at": "2026-09-27T20:05:32Z",
  "model_ready_at": "2026-09-27T20:05:32Z",
  "startup_duration": 140,
  "model_identity": {
    "expected": "Qwen/Qwen2.5-7B-Instruct-AWQ",
    "observed": "Qwen/Qwen2.5-7B-Instruct-AWQ"
  },
  "tensor_parallel_size": {"expected": 1, "observed": 1},
  "boot_id": "4d18cf41-f048-42e1-ab07-64ddd12700ed",
  "service_invocation_id": "cd284b557f0d4222b05cd60b8d61155d",
  "endpoint": "http://127.0.0.1:8001"
}
```

### 3.3 Hardware Memory & Physical Topology Verification
Authoritative metric reading from `xpu-smi stats`:
- **GPU 0 (`0000:51:00.0`, Worker 1)**: Memory Used: 27,869 MiB | Power: 49W | Serving: `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` (Protected Control).
- **GPU 1 (`0000:93:00.0`, Worker 2)**: Memory Used: 28,155 MiB | Power: 47W | Serving: `Qwen/Qwen2.5-7B-Instruct-AWQ` (Isolated Qualification Route).

---

## 4. Maintenance Replacement Disposition

**STATUS: REPLACEMENT SUCCESSFUL & VERIFIED**
- Worker 2 is serving the pinned candidate model on isolated port 8001.
- All pre-maintenance safeguards remain active and intact.
- The physical qualification campaign can now proceed against the candidate and control.
