# Design 02: bounded reasoning, total generation bounds and termination telemetry

- **Status:** ACCEPTED (review below), 2026-10-07.
- **Covers:**
  - DEFECT `docs/defects/2026-10-07-unbounded-reasoning-deep-route.md` (boundaries 1-4);
  - R8 (reasoning control per route), implemented as the same mechanism, not a second policy;
  - reconciliation finding N1 (finish_reason overwritten).
- **Requirements (operator):**
  - fail closed;
  - no request may obtain unlimited reasoning by omitting a limit;
  - limits are monotonic: a client may request less, never more.

## Layered enforcement (inner layers are the fail-safe; outer layers select within them)

| Layer | Owner | Mechanism | Applies when |
|---|---|---|---|
| L1 worker hard cap | worker config (inventory) | `--reasoning-budget N --reasoning-budget-message "<end instruction>"` on every reasoning-capable llama.cpp worker. N comes from inventory `reasoning_budget` (required; deploy fails if a worker declares reasoning without a budget). | always, including for any client that reaches the worker |
| L2 route policy (= R8) | gateway route table (inventory) | each route has `reasoning: {mode: on\|off, budget: B, answer_allowance: A}`. The gateway sets `chat_template_kwargs.enable_thinking` (on/off) and a per-request budget `min(B, worker cap, client profile)` (`thinking_budget_tokens` and `reasoning_budget_tokens`). | every routed request |
| L2b client profile | client (selection only) | header `X-AIHost-Reasoning: off\|low\|standard\|max` maps to `0 \| B/4 \| B/2 \| B` within the route's B; `enable_thinking=false` for `off`. It can only lower the bound. Unknown values are rejected with 400. | when sent |
| L3 total generation bound | gateway | `max_tokens = min(client max_tokens?, route output cap = budget_effective + A, remaining context)`. This is applied always; omitted max_tokens gets the route cap (Design 01 section 3). | always |
| L4 telemetry | gateway | termination classification on every completion (below) | always |

Monotonicity:
- Each layer takes `min()` of its input and its own limit.
- The client can lower the reasoning profile and max_tokens, never raise them above route and worker caps.
- A client that sends `chat_template_kwargs` that would increase reasoning (e.g. `enable_thinking: true` on an `off` route,
  or a budget field above the effective one) has those fields **overwritten** by the gateway. An attempt to raise the budget
  is recorded as evidence `client_limit_clamped`.

Budget values:
- They are set from bounded evidence (Q-BUDGET: 2048 / 4096 / 8192).
- Until then, the interim containment is L1 = 4096 on the reasoning-capable worker(s) currently in production, with route deep
  `budget 4096, answer_allowance 8192` and route lead `mode off` for Qwen3-Coder (non-reasoning model).
- `answer_allowance` is sized from bounded-run evidence: answer tokens p99 across bounded runs plus margin. It is recorded with
  the value.

## Termination telemetry (L4)
The gateway classifies every completion from the worker response and the effective limits:

| Class | Condition |
|---|---|
| `reasoning_budget_exhausted` | the budget end message is present in `reasoning_content`, OR exact reasoning tokens ≥ effective budget (counted via the worker tokenizer when cheap; message presence is the primary signal) |
| `output_limit` | provider `finish_reason == "length"` (this includes the gateway-applied total bound) |
| `context_limit` | provider rejects for context (pre-dispatch rejections are already `context_length_exceeded`) |
| `timeout` / `cancelled` / `upstream_error` | from R1/R7 and provider errors |
| `stop` / `tool_calls` | normal |

Both may apply: `reasoning_budget_exhausted` is a flag and `finish` is the class. Recorded as:
- evidence `termination` and `reasoning_budget_exhausted` fields on `response_validated`;
- metric `aihost_completion_terminations_total{worker_id,pool,class}` and
  `aihost_reasoning_budget_exhausted_total{worker_id,pool}`;
- response header `X-AIHost-Termination: <class>[;reasoning_budget_exhausted]`.

**Fix N1:** the response `finish_reason` passes through the provider value (`length` stays `length`; `tool_calls` when tool calls
are present). Truncation is never reported as `stop`.

## Not in scope
- Changing clients (Nexus): the client can opt into lower reasoning via the header; it never needs to, because defaults are safe.

## Review (2026-10-07)
- **Fail-closed:**
  - A request with no max_tokens and no headers on the deep route is bounded by L3 (route cap) and L1 (worker budget).
  - If the gateway were bypassed (prevented by Design 04), L1 still bounds reasoning.
  - L1 alone does not bound the answer phase; L3 does. Gateway-only access (Design 04) is what makes L3 unavoidable.
  Passes.
- **Monotonic:** all layers use `min()`; client raises are overwritten and evidenced. Passes.
- **Single mechanism:** R8 is L2. There is no separate policy store; budgets live in the route table and worker inventory.
  Passes.
- **Evidence-based value:** 4096 is interim only; the production value comes from Q-BUDGET. Passes (operator instruction).
- **Verification checkpoints:**
  - (a) Per-request `thinking_budget_tokens` / `reasoning_budget_tokens` is honoured below the server cap. Field names exist in
    the pinned binary (strings: `thinking_budget_tokens`, `reasoning_budget_tokens`, `reasoning_budget_message`). Effectiveness
    must be shown in Q-BUDGET runs. If not honoured, profiles below the cap are enforced by L3 only (answer cap) and
    `enable_thinking`, and the report states that.
  - (b) `enable_thinking=false` is honoured per model; this was verified for the Qwen family. Glimmer is dropped because it ignores
    it (`reasoning_controllable: fail`).
- **Rejected:**
  - Client-only control (violates fail-closed).
  - Gateway-only control without a worker cap (one bypass yields unlimited reasoning).
  - A fixed global budget (the models use reasoning differently; budget is per worker and per route).
