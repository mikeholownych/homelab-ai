# Phase 14 Experiment 02: Request Routing and Worker Overlap Analysis

- **Date:** 2026-09-29
- **Scope:** Network routing topologies, dispatch pathways, and engine concurrency during Phase 14 Experiment 02.

---

## 1. Network Routing and Architectural Topology

The experimental campaign and the concurrent OpenCode workload used two entirely disjoint ingress pathways:

```
[Local Host: 10.0.8.95]                                   [Dell Precision T5820: 10.0.8.5]
+------------------------------------+                    +------------------------------------+
| sustained_queue_runner.py          |                    | aihost-orchestrator-gateway        |
|                                    |                    | (port 8010, token: opencode)       |
| Direct Worker 1:                   |                    |                                    |
|   SSH Tunnel (18000 -> 8000) ======> [SSH: 1269920] ===>| Worker 1 Container (vLLM, port 8000)
|                                    |                    |   GPU 0: Intel Arc A770 (Tile 0)   |
| Direct Worker 2:                   |                    |                                    |
|   Direct HTTP (10.0.8.5:8001) =====> [Direct LAN] ======>| Worker 2 Container (vLLM, port 8001)
+------------------------------------+                    |   GPU 1: Intel Arc A770 (Tile 1)   |
                                                          +------------------------------------+
                                                                            ^
[OpenCode Client / External Agent] =========================================+
   (Authenticates to port 8010 via opencode-client-token)
```

### Path Discrepancy & Observability Gap
1. **The Orchestrator Gateway (Port 8010):**
   - The production gateway received requests from the external OpenCode client authenticated via `opencode-client-token`.
   - The gateway routed requests internally to `localhost:8000` (Worker 1) and `localhost:8001` (Worker 2).
   - Because the gateway was bypassed by the experimental runner, it had **zero visibility into experimental requests**.
2. **The Experimental Runner (`sustained_queue_runner.py`):**
   - The runner communicated directly with Worker 1 via the local SSH tunnel port 18000 (landing as `127.0.0.1` inside Worker 1) and directly with Worker 2 on LAN port 8001 (landing as `10.0.8.95`).
   - The experimental runner did not query the gateway and therefore had **zero visibility into concurrent OpenCode requests**.

---

## 2. In-Engine Worker Overlap

Because both pathways terminated at the same underlying vLLM server instances, requests converged inside the vLLM engine cores:

- **Worker 1 (`aihost-vllm-worker1.service`):**
  - Received 90 experimental requests from the sustained campaign (and preflight).
  - Received 12 OpenCode requests routed via the gateway.
  - vLLM continuous batching scheduler interleaved tokens from both sources into the active batch.
  - vLLM engine logs recorded `Running: 2 reqs` at `06:24:32`, `06:25:22`, `06:25:32`, and `06:25:42`, confirming concurrent execution.
- **Worker 2 (`aihost-vllm-worker2.service`):**
  - Received 42 experimental requests from the sustained campaign.
  - Received 2 OpenCode requests routed via the gateway (`06:26:04` and `06:26:17`).
  - Overlap was minimal (<20 seconds) right as Cohort 3 concluded.

---

## 3. Direction and Magnitude of Asymmetry

The table below summarizes the request and token distribution across the four cohorts:

| Campaign Cohort | Window (UTC) | Experimental Requests (W1 / W2) | OpenCode Requests (W1 / W2) | Overlap Status |
|---|---|---|---|---|
| **Regime 1 Config B** | 05:48:39 - 05:57:23 | 12 / 4 | 0 / 0 | Fully Isolated |
| **Regime 1 Config B+** | 05:57:23 - 06:06:07 | 10 / 6 | 0 / 0 | Fully Isolated |
| **Regime 2 Config B+** | 06:06:07 - 06:26:21 | 30 / 18 | 12 / 2 | **Contended (41,853 tokens)** |
| **Regime 2 Config B** | 06:26:21 - 06:48:39 | 36 / 12 | 0 / 0 | Fully Isolated |

**Conclusion:** The concurrent workload landed with 100% asymmetry on Configuration B+. Configuration B ran under pristine isolation conditions.
