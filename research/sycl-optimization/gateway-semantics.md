# Gateway failure semantics (backlog 629)

Read from code on 2026-11-17 and checked against the suites that cover them
(`tests/test_smart_gateway_enterprise.py`, `tests/test_qualification_correctness.py`, `tests/test_gateway_fast_admission.py`,
`tests/test_gateway_platform.py`: all pass, 32 + 50 tests). These are the semantics as implemented; nothing here changes behaviour.

| Concern | Behaviour | Source |
|---|---|---|
| Circuit breaker (per worker/pool) | opens after 5 consecutive failures, or an error rate >= 50% over a 10 s window with at least 4 requests; recovery timeout 15 s; needs 2 successful half-open probes to close | `circuit_breaker.py` (defaults) |
| Admission queue | per-pool bounded queue (32); priority class, then fair share per client, then arrival; waiting ends at admission, the request deadline (504 `deadline_exceeded`), the queue max wait (120 s) or client disconnect | `admission.py` |
| Queue full | 429 `capacity_exhausted` with `Retry-After` = median recent duration x (queue position + 1), clamped 1-120 s (30 s typical if no history) | `admission.py` `_retry_after` |
| Gateway restarting | 503 with `retry_after` 15 | `runtime.py` |
| Worker health | polled; a worker with 3 consecutive failed checks triggers auto-recovery (`ORCHESTRATOR_AUTO_RECOVERY_THRESHOLD`) | `health.py` |
| Retry / fallback | multi-attempt escalation policy with exponential backoff and 20% jitter (`jitter_ratio` 0.2); route rules carry `fallback` and `fallback_on_saturation` | `smart_router.py`, `routing.py` |
| Prefix affinity | rendezvous hash on session or conversation prefix plus a warm-worker map (1024 entries) | `runtime.py` `prefer` |

Live evidence on the deployed build: concurrency 4 on a single-slot worker queued with no errors and TTFT growing roughly linearly
(window3 README); the queue-full and deadline paths are covered by the tests above rather than driven live, because a live run
past 32 queued requests is blocked by the qualification client's 60 rpm quota.

Known gap: the 408 case (client timeout during queueing) maps to the deadline/cancel path, not a distinct 408; no test asserts a 408 status.
