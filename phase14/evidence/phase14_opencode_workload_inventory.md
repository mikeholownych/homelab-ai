# Phase 14 Experiment 02: OpenCode Workload Forensic Inventory

- **Date:** 2026-09-29
- **Investigation Window:** `2026-09-29T05:48:38Z` to `2026-09-29T06:48:39Z`
- **Reconstruction Sources:**
  - `/var/lib/local-ai/evidence/t5820-v128-control-cooperative-generation-003/gateway-evidence.jsonl`
  - `/var/lib/local-ai/evidence/t5820-v128-control-cooperative-generation-004/gateway-evidence.jsonl`
  - `journalctl -u aihost-vllm-worker1.service`
  - `journalctl -u aihost-vllm-worker2.service`

---

## 1. Executive Summary of OpenCode Activity

During the 1-hour execution window of the Phase 14 Experiment 02 campaign, exactly **14 inference requests** were submitted by an autonomous OpenCode agent through the T5820 Orchestrator Gateway (`aihost-orchestrator-gateway.service`, port 8010).

- **Total Requests:** 14
- **Worker Allocation:** 12 requests dispatched to Worker 1 (`b0-live-tp1-worker1`), 2 requests dispatched to Worker 2 (`b0-live-tp1-worker2`)
- **Total Prompt Tokens:** 39,966 tokens
- **Total Completion Tokens:** 1,887 tokens
- **Total Tokens Processed:** 41,853 tokens
- **Arrival Distribution:** Occurred in two concentrated bursts:
  - **Burst 1:** `06:19:19.834Z` to `06:20:28.194Z` (6 requests, 18,012 tokens, 100% to Worker 1)
  - **Burst 2:** `06:24:29.000Z` to `06:26:17.084Z` (8 requests, 23,841 tokens; 6 to Worker 1, 2 to Worker 2)

---

## 2. Exhaustive Request-by-Request Inventory

The table below records all 14 identified OpenCode requests, reconstructed directly from gateway event stream hashes and vLLM API completions:

| # | Request ID | Timestamp (UTC) | Target Worker | Tool Executed | Prompt Tokens | Compl. Tokens | Total Tokens | Duration (ms) | HTTP Status |
|---|---|---|---|---|---|---|---|---|---|
| **1** | `528b26fb-986c-45bf-81a6-bfa7ab69de56` | 2026-09-29T06:19:22.996Z | `b0-live-tp1-worker1` | `t5820repo_read_role_artifact` | 2,582 | 54 | 2,636 | 3,161.8 | 200 OK |
| **2** | `6fbe0c4e-7d06-4803-bf48-04961359aff0` | 2026-09-29T06:19:38.771Z | `b0-live-tp1-worker1` | `t5820repo_read_role_artifact` | 2,876 | 259 | 3,135 | 15,775.3 | 200 OK |
| **3** | `80324082-8408-4fa4-85e0-d5899d811a33` | 2026-09-29T06:19:44.865Z | `b0-live-tp1-worker1` | `t5820repo_read_role_artifact` | 3,154 | 85 | 3,239 | 6,093.3 | 200 OK |
| **4** | `556513be-9def-4ee8-9bca-a8d3cd167dab` | 2026-09-29T06:20:01.495Z | `b0-live-tp1-worker1` | `t5820repo_read_role_artifact` | 2,582 | 54 | 2,636 | 16,630.6 | 200 OK |
| **5** | `5da67116-49c5-46bb-a695-8a21031428aa` | 2026-09-29T06:20:21.035Z | `b0-live-tp1-worker1` | `t5820repo_read_role_artifact` | 2,876 | 264 | 3,140 | 19,539.4 | 200 OK |
| **6** | `7d9eeb06-dab9-46f1-b42f-e6decb257b9f` | 2026-09-29T06:20:28.194Z | `b0-live-tp1-worker1` | `t5820repo_read_role_artifact` | 3,159 | 72 | 3,231 | 7,159.0 | 200 OK |
| **7** | `2643ce87-4b65-4bc1-ab98-39c268cce173` | 2026-09-29T06:24:32.679Z | `b0-live-tp1-worker1` | `t5820repo_read_role_artifact` | 2,582 | 54 | 2,636 | 3,679.8 | 200 OK |
| **8** | `c4d402d4-96c8-41b3-929c-85cc9a7e7832` | 2026-09-29T06:24:51.597Z | `b0-live-tp1-worker1` | `t5820repo_read_role_artifact` | 2,876 | 213 | 3,089 | 18,918.0 | 200 OK |
| **9** | `e020a71c-3984-4102-86ac-d00fdb850315` | 2026-09-29T06:25:05.414Z | `b0-live-tp1-worker1` | `t5820repo_read_role_artifact` | 3,108 | 153 | 3,261 | 13,816.6 | 200 OK |
| **10** | `97629065-934d-4869-8ef8-c8fbf4313298` | 2026-09-29T06:25:22.118Z | `b0-live-tp1-worker1` | `t5820repo_read_role_artifact` | 2,582 | 59 | 2,641 | 16,704.0 | 200 OK |
| **11** | `92b3cfd8-cef7-4d5b-ae7d-5db2dc6f0097` | 2026-09-29T06:25:37.902Z | `b0-live-tp1-worker1` | `t5820repo_read_role_artifact` | 2,881 | 265 | 3,146 | 15,783.7 | 200 OK |
| **12** | `b6c81930-2129-4d18-ba4c-1087d0846d66` | 2026-09-29T06:25:48.989Z | `b0-live-tp1-worker1` | `t5820repo_read_role_artifact` | 3,165 | 181 | 3,346 | 11,087.7 | 200 OK |
| **13** | `bd105ad4-f8ac-4e84-8e3d-69a9c6945299` | 2026-09-29T06:26:04.981Z | `b0-live-tp1-worker2` | `t5820repo_read_role_artifact` | 2,489 | 38 | 2,527 | 3,981.7 | 200 OK |
| **14** | `ee9222e7-6d2d-4e4e-91e9-84d4e53139e2` | 2026-09-29T06:26:17.084Z | `b0-live-tp1-worker2` | `t5820repo_read_role_artifact` | 3,054 | 136 | 3,190 | 12,103.0 | 200 OK |

---

## 3. Redaction and Privacy Protection

In compliance with human direction, all bearer tokens, credential secrets (`opencode-client-token`), and specific prompt instruction text have been scrubbed. The tool invocations represent read queries against the repository artifact inspection interface (`t5820repo_read_role_artifact`).
