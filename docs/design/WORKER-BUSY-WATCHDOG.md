# Worker busy-watchdog (design)

Status: implemented, shipped DISABLED (nothing runs it until an operator starts it; see Operation). Backlog item: "busy-watchdog keyed on oldest in-flight request; graceful stop then forced kill".

## Problem
A SYCL llama.cpp worker can wedge on a GPU job (the host logs 32 kernel `Timedout job` events since the 2026-11 incidents; one
research harness failure left a worker down for hours because nothing restarted it). `Restart=on-failure` does not help: the
process is alive but making no progress, so systemd sees nothing to restart and the gateway keeps routing to it.

## Signal (as implemented)
The implementation keys on the **engine's own progress**, not on the gateway's request table: the gateway already scrapes each worker's
stats and now exports `aihost_engine_stalled_seconds{worker_id}` = seconds during which the engine reported running requests while none of
its progress counters (in-flight prompt/generation tokens, completed token totals) changed; 0 when idle, progressing or unknown. This also
catches a worker that stays pinned after the gateway cancelled the request (the gateway then holds no in-flight entry for it), which the
request-age signal below would miss. Logic: `orchestrator_runtime/watchdog.py`; executor: `scripts/worker_watchdog.py`.

### Original design signal
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

## Operation (implemented)
- `scripts/worker_watchdog.py` runs on the controller, reads `aihost_engine_stalled_seconds` from the gateway `/metrics`, and walks the ladder:
  drain (gateway admin API) -> graceful `systemctl stop` -> `systemctl kill -s SIGKILL` only if the stop failed -> restart -> wait for the gateway to
  report the worker ready (300 s, else abandon) -> undrain. A worker whose stall clears while draining is simply undrained. Defaults: stuck after
  120 s, drain wait 30 s, at most 3 restarts per worker per hour; beyond that the worker stays drained and an `alert` record is written once.
  Each rung is one JSON line in `--evidence`. DRY-RUN unless `--apply`.
- Needs: a gateway client with the `admin` scope (token file, never printed), SSH key access to the host, and passwordless `sudo systemctl`
  for the worker units. None of that is provisioned by default, which is why it is disabled.
- Verified: unit tests with a fake clock for the ladder, rate limit and abandon paths; executor tests with fake gateway/systemd (order, kill only
  after a failed stop, no action on other workers, dry run touches nothing, never-ready abandon); gateway stall gauge tested against a fake engine.
  Verified live on production worker2 with real SIGSTOPs (2026-11-17, evidence/window3/watchdog and watchdog-cycles): drain, graceful stop, forced kill after a failed stop, restart, readmit only after a fresh idle reading, and the per-hour restart limit (third stall alerts instead of restarting). Scheduled as a dry-run user service (see Scheduling); acting for real is an explicit operator switch.
- Rollout when wanted: provision the admin client, run `--once` dry-run against production for a day, rehearse with SIGSTOP on a research worker,
  then enable on one worker (canary) before both.

## Scheduling (roles/reconcile_controller)
The executor runs as the controller user service `aihost-worker-watchdog.service`, installed with the reconcile snapshot by
`playbooks/reconcile-controller.yml`. **Operator decision 2026-11-17: it acts** (`reconcile_controller_watchdog_apply: true` is the role default):
drain, graceful stop, forced kill after a failed stop, restart, readmit, with the per-hour restart limit and an `alert` record when it is exhausted.
It runs only while `reconcile_controller_watchdog_token_file` (default `~/.config/aihost/watchdog.token`, mode 0600) exists, because the role never
creates or copies the admin-scope gateway token; the operator provisions it (the `ansible-admin` client's token). Evidence: `<evidence dir>/worker-watchdog.jsonl`.
Stop it: remove the token file (the unit's ConditionPathExists then fails at the next start) or `systemctl --user stop aihost-worker-watchdog`; make it log only:
set `reconcile_controller_watchdog_apply: false` and re-run the playbook. Timings are the role defaults (stuck after 120 s, 3 restarts per hour).
