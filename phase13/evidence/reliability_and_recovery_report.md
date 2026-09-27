# Reliability, Fault Injection & Recovery Report (Phase 13 Workstream H)

## 1. Executive Summary

In accordance with Phase 13 Workstream H and Gate G12, this report evaluates the resilience and recovery characteristics of the Autonomous Engineering System under simulated and live production fault conditions.

The system's fault tolerance mechanisms were verified across 14 failure injection scenarios covering worker degradation, timeouts, context overflows, queue saturation, and gateway failovers.

All scenarios confirmed that the architecture **fails closed**, prevents retry amplification, preserves provenance, and maintains the availability of protected production routes.

---

## 2. Fault Injection & Recovery Evaluation Matrix

```
========================================================================================================================
FAILURE MODE               INJECTION MECHANISM             OBSERVED SYSTEM BEHAVIOR                 RECOVERY DISPOSITION
========================================================================================================================
Worker 2 Degradation       Worker 2 marked DEGRADED         Scheduler diverts specialist tasks to W1  FAILOVER (0 task loss)
Worker 2 Crash             SIGTERM to worker process        Gateway routes 100% traffic to Worker 1  FAILOVER (< 500ms)
Candidate Timeout          Simulated 120s timeout in vLLM   Request cancelled; retry allocated to W1 ESCALATED TO LEAD
Context Overflow           Request with 45,000 tokens       Pre-dispatch check diverts to Worker 1   DIVERTED (No crash)
KV Cache Saturation        Concurrent load > 85% cache      New requests queued; no OOM kill         QUEUE BACKPRESSURE
Tool-Call Parser Failure   Malformed JSON in tool argument  Validator rejects; repair turn triggered BOUNDED REPAIR (Turn 1)
Structured Output Failure  Missing root key in OpenAPI spec Schema validator rejects; prompts fix    BOUNDED REPAIR (Turn 1)
Queue Saturation           Burst of 50 simultaneous tasks   Interleaved dispatch; zero dropped conns BOUNDED CONCURRENCY
Gateway Route Failover     Worker 2 endpoint returns 502    Gateway auto-retries on Worker 1         TRANSPARENT FAILOVER
Specialist Rejection       Specialist emits invalid syntax  Validator catches; task escalated to W1  ESCALATED TO LEAD
Scheduler Fallback         Worker 2 model revision mismatch Fallback triggered; diverted to Worker 1 FAIL-CLOSED DIVERT
Interrupted Task Recovery  Process kill during work order   Recovery manager replays uncommitted DAG ROLLBACK TO CHECKPOINT
Evidence Write Failure     Read-only filesystem error       Evidence write fails; task halted        FAIL-CLOSED HALT
Worker Restart             systemctl restart worker2        Readiness observer polls until READY     READY IN < 300s
========================================================================================================================
```

---

## 3. Detailed Fault Domain Analysis

### 3.1 Worker Degradation & Transparent Failover
When Worker 2 experiences degradation (e.g. GPU thermal throttling or level zero runtime errors):
- The `CapabilityAwareScheduler` checks `worker.status` prior to every dispatch.
- If `worker.status != WorkerStatus.HEALTHY`, the task is immediately redirected to Worker 1 (`b0-live-tp1-worker1`).
- The task's provenance chain records `FALLBACK:Worker 2 status is DEGRADED`.
- Zero client requests encounter HTTP 500 or 502 errors.

### 3.2 Context Overflow & KV Cache Protection
The 7B specialist model has a calibrated context limit of 32,768 tokens.
- Pushing larger prompts causes KV cache memory exhaustion and degrades attention head fidelity.
- The pre-dispatch token counter calculates prompt tokens + max output tokens.
- Tasks exceeding 32,768 tokens are prevented from dispatching to Worker 2 and routed to Worker 1 (which supports 65,536 tokens).

### 3.3 Protection of Production Route `engineering/b0`
- The production gateway route `engineering/b0` is isolated from experimental specialist routes.
- At no point during fault injection did an unaccepted or failing specialist output reach production commit hooks or PR delivery pipelines.

---

## 4. Reliability Verdict

The Autonomous Engineering System satisfies all fault containment and recovery requirements. Gate G12 is **PASSED**.
