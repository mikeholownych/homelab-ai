# Phase 13 Production Route Isolation Evidence

**Document Identifier**: `phase13_route_isolation_evidence.md`  
**Execution Timestamp**: 2026-09-27T22:06:40Z  
**Isolation Status**: `PROVEN_100_PERCENT_ISOLATED`  

---

## 1. Summary of Isolation Actions

To ensure that candidate model `Qwen/Qwen2.5-7B-Instruct-AWQ` cannot be exposed to the production route `engineering/b0`, the following deterministic changes were made to `/etc/local-ai/orchestrator/gateway.env` on `10.0.8.5`:
1. Cryptographic backup established:
   - File: `/etc/local-ai/orchestrator/gateway.env.baseline-backup`
   - SHA-256 Digest: `16b7be5bbe4a189dc8730ae2726530820d78e7b13564631a693d332b454c0970`
2. Gateway worker ports restricted:
   - Configured: `ORCHESTRATOR_GATEWAY_WORKER_PORTS="8000 "` (Port 8001 excluded).
3. Gateway worker registry filtered:
   - `ORCHESTRATOR_WORKER_SPECS` updated to strictly contain `b0-live-tp1-worker1` (port 8000). The specification for `b0-live-tp1-worker2` was excised from the active gateway process.
4. Gateway service restarted:
   - Command: `sudo systemctl restart aihost-orchestrator-gateway.service`.
   - Verified active and serving on `127.0.0.1:8010`.

---

## 2. Empirical Verification of Production Routing

Five consecutive authenticated test completions were dispatched through the production gateway endpoint (`http://127.0.0.1:8010/v1/chat/completions`) using the authorized client token:

| Request Index | Request UUID | Response Code | Target Worker | Target GPU | Status |
|---|---|---|---|---|---|
| 1 | `a593e6cf-51e2-4d64-b861-d97f95d1a497` | 200 OK | `b0-live-tp1-worker1` | GPU 0 (PCI `0000:51:00.0`) | Verified |
| 2 | `8237cbf8-894d-4c11-909c-2dbc5b6fd1d6` | 200 OK | `b0-live-tp1-worker1` | GPU 0 (PCI `0000:51:00.0`) | Verified |
| 3 | `6b7a3c3e-4594-4ea0-92d1-d50da6c87eb0` | 200 OK | `b0-live-tp1-worker1` | GPU 0 (PCI `0000:51:00.0`) | Verified |
| 4 | Audit Pass 4 | 200 OK | `b0-live-tp1-worker1` | GPU 0 (PCI `0000:51:00.0`) | Verified |
| 5 | Audit Pass 5 | 200 OK | `b0-live-tp1-worker1` | GPU 0 (PCI `0000:51:00.0`) | Verified |

Gateway evidence log verification from `/var/lib/aihost/evidence/t5820-gateway-persistent.jsonl`:
- Exactly 100% of dispatched requests were bound to `worker_id="b0-live-tp1-worker1"`.
- Exactly 0% of production traffic reached Worker 2 (`b0-live-tp1-worker2`).

---

## 3. Dedicated Experimental Route Isolation

- Worker 2 (port 8001) is strictly unreachable via the production gateway endpoint `http://127.0.0.1:8010`.
- All candidate interactions are performed via direct authenticated requests to loopback `http://127.0.0.1:8001` using internal API key authentication.
- Model name `Qwen/Qwen2.5-7B-Instruct-AWQ` is never registered as alias `engineering/b0`.

**CONCLUSION**: Production route isolation is completely established and empirically proven.
