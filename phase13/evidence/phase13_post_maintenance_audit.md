# Phase 13 Post-Maintenance Service & Baseline Audit

**Document Identifier**: `phase13_post_maintenance_audit.md`  
**Execution Timestamp**: 2026-09-27T22:35:00Z  
**Audit Disposition**: `BASELINE_100_PERCENT_RESTORED_AND_VERIFIED`  

---

## 1. Baseline Dual-Worker Status & Health

The post-maintenance audit verified that the operational serving environment on host `10.0.8.5` has returned to its authoritative dual-resident 30B MoE configuration:

| Component | Target Identity | Verified Live State | Model / Revision | Status |
|---|---|---|---|---|
| **Worker 1** | `aihost-vllm-worker1.service` | Active (Port `8000`), GPU 0 (PCI `0000:51:00.0`) | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` (`4bd30395b72ea6045edd04806c4fea448d4467b3`) | **HEALTHY** |
| **Worker 2** | `aihost-vllm-worker2.service` | Active (Port `8001`), GPU 1 (PCI `0000:93:00.0`) | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` (`4bd30395b72ea6045edd04806c4fea448d4467b3`) | **HEALTHY** |
| **Gateway** | `aihost-orchestrator-gateway.service` | Active (Port `8010`), Round-Robin (8000, 8001) | Serves public route `engineering/b0` | **HEALTHY** |

---

## 2. Configuration Integrity & SHA-256 Checksums

Live file digests on `10.0.8.5` match the baseline authoritative hashes with zero bit drift:
- Worker 2 Config (`/etc/local-ai/vllm/worker2/vllm-config.yaml`):
  `641c9402ebbc56f5d599512894f72a02304fd6615edbb7a2875ab48f93f4e08b` (**EXACT MATCH**)
- Gateway Environment (`/etc/local-ai/orchestrator/gateway.env`):
  `16b7be5bbe4a189dc8730ae2726530820d78e7b13564631a693d332b454c0970` (**EXACT MATCH**)
- Worker 2 Environment (`/etc/local-ai/vllm/worker2/vllm.env`):
  `47001e301847782fb34b3c0de8156f0126f65c7eca05fed3aea31ef07d72865f` (**EXACT MATCH**)

---

## 3. Production Traffic Verification (Round-Robin Audit)

Six consecutive authenticated requests to `http://127.0.0.1:8010/v1/chat/completions` were tracked in the gateway persistent log `/var/lib/aihost/evidence/t5820-gateway-persistent.jsonl`:
- Request 1 (`0f18f561-e108-4080-b0b4-4e3d5d08fa1c`): Handled by `b0-live-tp1-worker2` (Worker 2 / GPU 1).
- Request 2 (`0786f485-3164-49ec-ac17-f6c6c5325d5f`): Handled by `b0-live-tp1-worker1` (Worker 1 / GPU 0).
- Request 3 (`ee93b7a1-890b-4c5f-9da4-cdcc15eecbfd`): Handled by `b0-live-tp1-worker2` (Worker 2 / GPU 1).
- Request 4: Handled by `b0-live-tp1-worker1` (Worker 1 / GPU 0).
- Request 5: Handled by `b0-live-tp1-worker2` (Worker 2 / GPU 1).
- Request 6: Handled by `b0-live-tp1-worker1` (Worker 1 / GPU 0).

Both workers are actively sharing production load in strict 50/50 alternating round-robin.
Zero candidate traffic reaches the production route.

---

## 4. Protected Workstation Process Health

| Process Description | PID | Status | CPU / Memory | Signal / Restart Interruptions |
|---|---|---|---|---|
| **Hermes Gateway** | `986` | Active (Continuous > 5 days) | Normal | 0 |
| **SSH Port Forwarding Tunnel** | `2093382` | Active (Continuous > 1 day) | Normal | 0 |
| **OpenCode Autonomous Runner**| `3130937` | Active (Continuous > 1 day) | Normal | 0 |

No host processes were signaled, killed, or disrupted.

**CONCLUSION**: Baseline restoration is 100% complete and verified. The maintenance proposal `MAINT-PROP-PHASE13-HETERO-GPU1` is closed.
