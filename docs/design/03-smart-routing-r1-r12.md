# Design 03: smart-routing capabilities R1-R12 (design notes and reviews)

- **Status:** ACCEPTED, 2026-10-07. Operator approved all twelve (2026-10-06).
- **Constraints:**
  - routing stays deterministic and auditable;
  - no LLM-based router;
  - no on-demand model loading;
  - the "Future evolution" items stay deferred;
  - R4 is the qualification path;
  - R8 = Design 02;
  - R9 consumes Design 01's capability model;
  - R11 strengthens the existing hash chain.

Shared infrastructure (Design 01): an in-flight registry keyed by request id `{client_id, worker_id, cancel_handle, deadline,
started_at, bytes_sent_to_client}`, plus the per-pool admission queue.

## R1 Cancellation
- **Design:**
  - Each dispatched upstream request runs on a connection the gateway owns (`http.client`), with a cancel handle that closes the
    upstream socket.
  - A watcher polls the client socket (select, 0.25 s) while the request is queued or in flight. Client EOF/reset cancels it:
    a queued request is dequeued; an in-flight one closes the upstream socket.
  - llama.cpp aborts generation when the HTTP connection closes; this is verified per engine in tests and live via `/slots`
    returning to idle.
  - Evidence `request_cancelled{reason: client_disconnect|deadline}`; metric `aihost_requests_cancelled_total{reason,pool}`.
- **Review:** frees scarce single slots (one slot per pool). It is engine-agnostic (any HTTP engine stops or finishes; the gateway
  stops waiting). Deterministic. Accepted.

## R2 Priority and fairness
- **Design:**
  - Header `X-AIHost-Priority: interactive|batch|background`, else the client's default (R6), else `interactive`.
  - Queue order: class (interactive > batch > background), then round-robin across clients within the class (oldest request of
    the next client), then FIFO.
  - No preemption of running work.
  - A client may not use a class above its configured maximum (R6 scope `max_priority`); a higher request is clamped
    (monotonic) and evidenced.
- **Review:** fairness without breaking prefix-cache affinity. Affinity picks the worker within a pool; priority orders the queue.
  Bounded, deterministic. Accepted.

## R3 Deterministic escalation
- **Design:**
  - New route match keys `attempt_gte: int` (header `X-AIHost-Attempt`) and `previous_outcome: [fail,...]` (header
    `X-AIHost-Previous-Request` names an earlier request id whose R10 outcome is looked up).
  - Example rule: `{id: escalate-retry, match: {attempt_gte: 2}, pool: deep, fallback: [lead]}`.
  - Decision evidence names the matched rule and inputs. First-match remains.
- **Review:** no classifier. Inputs are client-declared facts and recorded outcomes. Accepted.

## R4 Shadow and canary (qualification path)
- **Design:**
  - Workers with `role: candidate` (inventory) form candidate pools, never referenced by normal routes.
  - **Explicit alias** `candidate/<name>` is reachable only by clients with scope `qualification` (R6). This is THE
    qualification path: the remote engx client uses the gateway with that alias.
  - **Canary:** a route may set `canary: {pool, percent}`. A deterministic hash of the session/affinity key sends `percent`% of
    that route's requests to the candidate pool (fit- and capability-checked). It is recorded and visible in `X-AIHost-Route`.
  - **Shadow:** `shadow: {pool, percent}`. After the primary response is returned, the same request is dispatched to the shadow
    pool at `background` priority, only when it has free capacity. The output is never returned. The evidence
    `shadow_compared{primary_hash, shadow_hash, finish_reasons, tool_call_names_equal, latency}` is recorded.
  - **Candidate lifecycle:** `playbooks/candidate.yml` (controller-side Ansible). It drains (R5) and stops the production worker
    on a GPU, deploys the candidate worker unit, registers the candidate pool, and gracefully restarts the gateway (R12).
    `state=absent` reverses it.
- **Review:**
  - Satisfies gateway-only (no direct worker access) and remote-origin (the engx client is remote).
  - Canary/shadow are deterministic and evidence-backed.
  - Shadow never affects the response.
  Accepted.

## R5 Drain and safe swap
- **Design:**
  - Admin API (scope `admin`): `POST /admin/workers/{id}/drain`, `POST /admin/workers/{id}/undrain`, `GET /admin/workers`.
  - A drained worker is ineligible for new admissions. In-flight work completes. `/health` shows `drain: {state, inflight,
    since}`.
  - Ansible worker restarts/swaps call drain, wait for inflight == 0 (bounded, default 900 s), restart, wait healthy, then undrain.
    The call goes from the controller over the remote admin listener (Design 05).
  - Drain state is persisted in the gateway state file so it survives a gateway restart (R12).
- **Review:** removes the "stop the worker mid-request" failure mode seen in the evaluation. Accepted.

## R6 Per-client identity, quotas and budgets
- **Design:**
  - The digest-only client registry `/var/lib/aihost-gateway/clients.json` (Ansible-rendered, gateway-readable 0640) holds, per client. It lives in the service's private state directory because `/etc/local-ai` is not traversable by the isolated gateway account:
    `client_id`, `token_sha256`, `scopes ⊆ {workload, qualification, monitoring, admin}`, `max_priority`, `default_priority`,
    `quota: {requests_per_minute, tokens_per_day}`.
  - Tokens are stored only as sha256 in the registry. Plaintext token files are root-only (`/etc/local-ai/orchestrator/clients/
    <id>.token`, 0400) for the operator to deliver to clients.
  - Existing `client-token` / `opencode-client-token` migrate to clients `default` / `opencode` with workload scope, so the
    current tokens keep working.
  - `client_id` is on every evidence record and metric label.
  - Quotas: a token bucket for RPM; a daily token budget counted from usage. Exceeding either gives 429 + `Retry-After`, code
    `quota_exceeded`. Counters persist in the gateway state file.
- **Review:** least privilege (scopes), no plaintext tokens in gateway-readable config, monotonic priority. Accepted.

## R7 Deadlines and safe retries
- **Design:**
  - Header `X-AIHost-Deadline-Ms` (relative), capped at the gateway's upstream timeout.
  - Queued requests are dropped at the deadline with 504 `deadline_exceeded`.
  - Upstream timeout = min(upstream_timeout, remaining deadline). On expiry the in-flight request is cancelled (R1 mechanism).
  - **Safe retry:** retry/fallback only when (a) no byte was sent to the client and (b) the failure happened before
    generation: connection refused/reset before response headers, worker unhealthy, or 503. Never retry after a timeout, after the
    worker produced output, or mid-stream. At most one retry, to the next fit- and capability-checked candidate. Evidenced.
  - Streaming (amended during implementation, 2026-10-07): the gateway now streams for real. It reads the worker's SSE and
    forwards each delta as it arrives (fix for N3), keeping a full copy of the response for validation, termination
    classification and evidence. "Before the first streamed token" is the point where the gateway sends its response
    headers (`on_stream_start`):
    - a pre-generation failure before it may be retried;
    - nothing after it is retried;
    - a client write failure mid-stream is a cancellation (R1), never a worker failure.
    The termination class travels in the final SSE frame (`x_aihost.termination`), because the headers have already gone out.
- **Review:** no duplicate generation billed or emitted. Deterministic. Accepted.

## R8 Reasoning control per route
- Implemented as Design 02, layer L2. Route `reasoning` policy; client profile header; defaults from evidence.
- **Review:** the single mechanism shared with the defect remediation. Accepted.

## R9 Capability-checked routing
- **Design:**
  - Requirements are derived from the request:
    - `tools` → `tools`;
    - more than one tool call expected (`parallel_tool_calls: true`) → `parallel_tool_calls`;
    - `response_format` json_schema/json_object → `structured_output`;
    - image content parts → `vision`;
    - `X-AIHost-Reasoning` not `off` on a reasoning route → `reasoning`;
    - prompt size → fit check.
  - A worker is eligible only if every requirement is `available` in the Design 01 capability model (declared or verified).
  - Nothing eligible: 422 `capability_unsupported` with the missing capability names.
- **Review:** one source of truth with `/v1/models`. Accepted.

## R10 Outcome feedback loop
- **Design:**
  - `POST /v1/outcomes {request_id, outcome: pass|fail|partial, detail?}` (workload scope, own requests only; the request id must
    belong to the same client_id).
  - Evidence `outcome_reported` links the route rule, pool, worker and model artifact.
  - Metric `aihost_outcomes_total{rule,pool,model,outcome}`.
  - `GET /v1/outcomes/summary` gives success rates per route/pool/model.
  - Route rules gain optional `evidence: [ids]`, shown in `/v1/routes`. A route change commit must cite outcome or qualification
    evidence (doc rule).
- **Review:** the gateway reports what clients assert, labelled as client-reported (it does not claim to know correctness).
  Accepted.

## R11 Evidence integrity and data handling
- **Design:**
  - **Chain continuity:** on start, the gateway reads the persisted evidence file, verifies the chain, and continues from the last
    `record_hash`. Fix for N2.
  - A broken chain gives evidence `chain_break_detected{at_line}`, metric `aihost_evidence_chain_valid 0`, and health degraded.
    The gateway keeps serving and appends from the break with an explicit link record, so it does not rewrite history.
  - **Anchor:** every 100 records or 5 minutes, the chain head hash is logged to the journal (`evidence_anchor head=<hash>
    count=<n>`; journald is not writable by the gateway user). An attacker editing the file cannot also rewrite the journal.
  - **Verifier CLI:** `python3 -m orchestrator_runtime.evidence verify <file> [--anchors-from-journal]`.
  - **Data policy:** `ORCHESTRATOR_PROMPT_POLICY = hash` (default) | `redact` | `store`.
    - `hash`: evidence carries the request content sha256, message count, roles, token counts, and tool names only.
    - Provider error bodies (which can echo prompt text) are hashed plus their first 120 characters with long tokens masked.
    - `store` must be explicitly configured.
- **Review:** strengthens the existing chain without breaking its format (`previous_hash` and `record_hash` unchanged). The
  default is hash-only plus metadata. Accepted.

## R12 Graceful gateway restart
- **Design:** on SIGTERM:
  1. Stop accepting new connections.
  2. `/health` reports `draining` (503 for readiness).
  3. Queued requests get 503 `gateway_restarting` with `Retry-After: 15`.
  4. In-flight requests complete up to `ORCHESTRATOR_SHUTDOWN_GRACE_SECONDS` (default 600, matching the longest bounded
     generation), then are cancelled (R1).
  5. Persist state (drain flags, quota counters).
  6. Exit 0.
  - systemd `TimeoutStopSec = grace + 30`, `KillMode=mixed`.
  - Ansible `Restart gateway service` stays a restart. Systemd waits for the graceful stop.
- **Review:** no in-flight loss on redeploy. Bounded by grace. Accepted.

## Explicitly excluded (unchanged)
- An LLM-based prompt classifier.
- On-demand model loading per request.
- Embeddings/rerank endpoints.
- The "Future evolution" section (async job API, model switching, packing).
