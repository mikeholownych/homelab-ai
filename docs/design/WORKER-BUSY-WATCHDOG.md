# Worker busy-watchdog (design)

Status: design, not implemented. Backlog item: "busy-watchdog keyed on oldest in-flight request; graceful stop then forced kill".

## Problem
A SYCL llama.cpp worker can wedge on a GPU job (the host logs 32 kernel `Timedout job` events since the 2026-11 incidents; one
research harness failure left a worker down for hours because nothing restarted it). `Restart=on-failure` does not help: the
process is alive but making no progress, so systemd sees nothing to restart and the gateway keeps routing to it.

## Signal
"Busy" is keyed on the **oldest in-flight request**, not on process liveness or CPU:
- The gateway already tracks in-flight requests per worker with a start time and streamed-byte counter.
- A worker is **stuck** when its oldest in-flight request has produced no new token/byte for `stuck_after_s`
  (default 120 s of silence for streaming; for non-streaming, `deadline + grace` from the request deadline), while
  worker `/health` may still answer 200.
- Never act on idle workers, on load alone, or on a request that is still streaming.

## Action ladder (per worker, one rung at a time, each recorded in evidence)
1. **Cancel** the stuck request (existing R1 cancellation: close upstream connection); wait `cancel_wait_s` (15 s).
2. If the request is still pinned: mark the worker **draining** in the gateway (no new routes; other pool member or fail-fast
   503 per policy), wait `drain_wait_s` (30 s).
3. **Graceful stop** through the supervisor (`systemctl stop`, SIGTERM, `TimeoutStopSec` bounded).
4. **Forced kill** (`SIGKILL` of the container) only after the graceful stop times out.
5. Restart via the existing unit; the gateway re-admits the worker only after a real readiness probe (a short completion).
Rate limit: at most N restarts per worker per hour (default 3); above that, leave the worker out of rotation and alert.
The action runs from the controller (Ansible/systemd), never from a workload path on the host.

## Safety
- Gateway-only worker access is unchanged: the watchdog reads gateway state and drives systemd; it sends no workload requests to worker ports.
- A worker holding other healthy in-flight streams is not restarted for one stuck request unless the stuck request cannot be cancelled.
- Every rung emits an evidence record (worker, request id hash, age, action, result) and a metric.

## Verification plan
- Unit tests with a fake clock for the ladder and the rate limit.
- Fault injection on a non-production worker: SIGSTOP the container to emulate a wedge; expect cancel, drain, stop, kill, restart, readiness, in that order, and no routing to the worker in between.
- Cancel path already verified on the HEAD image (window-2 failure injection: client abort mid-stream, follow-up request OK).
- Production rollout through Ansible after the idle check, canary worker first.
