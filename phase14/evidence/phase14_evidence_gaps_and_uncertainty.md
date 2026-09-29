# Phase 14 Experiment 02: Evidence Gaps and Uncertainty

- **Date:** 2026-09-29
- **Scope:** Precise identification of telemetry gaps, unmeasured variables, and remaining experimental uncertainty.

---

## 1. Identified Telemetry Gaps

The forensic investigation identified the following observability limitations in the existing environment:

1. **Suppressed Gateway HTTP Access Logging:**
   - The production gateway implementation in `/var/lib/aihost/releases/t5820-gateway-e523f9a/orchestrator_gateway/server.py` explicitly suppresses standard HTTP logging via:
     ```python
     def log_message(self, format: str, *args: Any) -> None:
         return
     ```
   - Standard NGINX- or Apache-style request logs with client IP and request duration were not written to journald. All gateway activity had to be reconstructed from evidence hashes and vLLM server access logs.
2. **Independent Request Ingress (No Global Admission Queue):**
   - The experimental runner connected directly to the container ports (`18000` via SSH tunnel and `8001` via direct LAN), bypassing the port 8010 gateway.
   - Consequently, neither the gateway nor the runner maintained an authoritative, unified scheduling queue across both workloads.
3. **Coarse-Grained Token Telemetry:**
   - vLLM engine statistics are logged periodically every 10 seconds (`[loggers.py:310]`).
   - Continuous per-iteration execution logs (microsecond-level scheduling decisions) are not persisted to journald to prevent disk flooding.
   - As a result, the exact millisecond-by-millisecond GPU cycle interleaving between individual OpenCode tokens and experimental tokens cannot be observed directly.

---

## 2. Characterization of Remaining Uncertainty

1. **Exact Uncontended Turnaround for Projects 5 and 6:**
   - While Projects 1–4 under Configuration B+ demonstrated a clean mean turnaround of **236.95s** with **0.00s queue wait**, the exact turnaround Projects 5 and 6 would have achieved without the 14 OpenCode requests cannot be precisely calculated without re-executing those specific projects under guaranteed single-tenant conditions.
2. **Steady-State Queue Clearance at Exactly 19.5 proj/hr:**
   - Because the queue wait growth on Projects 5 and 6 was confounded by external load, we cannot distinguish whether an uncontended B+ run of 20+ projects at $\lambda = 19.5\text{ proj/hr}$ would remain flat at zero wait or slowly drift upwards due to higher-order variance in project service demands.
3. **Cross-Workload Preemption Dynamics:**
   - Because vLLM prioritizes batch throughput rather than priority class scheduling, high-prompt OpenCode requests (up to 3,165 tokens) dynamically delay ongoing decodes. The precise impact of prompt chunking configuration (`--max-num-batched-tokens`) was not varied or isolated during the run.
