# Design 01: gateway engine adapters, live capacity, exact sizing, admission, client-facing limits and capabilities

- **Status:** ACCEPTED (review below), 2026-10-07.
- **Covers todo.md:**
  - "Gateway: live, dynamic limit management per worker" (items 1-7, a-d);
  - capability fields (reasoning_controllable, reasoning_budget, output_contract_compliance);
  - R9 capability-checked routing (the same capability model).
- **Principle:** each layer observes what it doesn't control, exposes what it knows, and takes responsibility for what it does
  control. The gateway controls admission, sizing and routing; it observes workers; it exposes limits and capabilities; it never
  depends on clients ingesting them.

## 1. Engine adapters (`orchestrator_runtime/engines.py`)
One adapter per engine behind a single interface; the worker inventory record names the engine.

| Method | llama.cpp | vLLM |
|---|---|---|
| `observe()` identity/limits | `GET /props`: `default_generation_settings.n_ctx` (per-slot context), `total_slots`, `model_path`, `model_alias`, `model_ftype` (quantization), `build_info` (engine version), `modalities`, `chat_template_caps` | `GET /v1/models`: `max_model_len`, `root`; `GET /version` |
| `live()` | `GET /slots` (busy, n_decoded) + `/metrics` (existing `engine_stats`) | `/metrics` `vllm:num_requests_*`, kv usage (existing) |
| `count_prompt(request)` | `POST /apply-template` (full chat params: messages, tools, tool_choice, chat_template_kwargs) gives the rendered prompt; then `POST /tokenize {content, add_special: true, parse_special: true}` gives the exact count | `POST /tokenize {model, messages, tools, add_generation_prompt: true}` gives `count` |
| `declared_capabilities()` | from `chat_template_caps` and `modalities` (see 4) | `supports_tools` when a tool parser is configured (inventory-declared), vision when multimodal |

- Calls are bounded (2-5 s timeouts), read-only, never inference.
- An adapter failure is an observation ("unknown"), never a fabricated value.
- vLLM is fixture-tested only; there is no live vLLM worker today. This is recorded as a limitation, not claimed verified.

## 2. Live capacity model (`orchestrator_runtime/capacity.py`)
Per worker, a `CapacityState`:
- `ctx_per_slot`, `slots_total`: observed;
- `engine`, `engine_version`, `model_identity` (path, alias, ftype);
- `observed_at`;
- `inflight` (gateway-dispatched, authoritative because the gateway is the only permitted client);
- `concurrency_limit` (adaptive);
- `limits_version`: sha256 of the identity and limits tuple.

Behaviour:
- Refreshed by the HealthManager probe cycle (10 s) using `observe()`. Live slot state comes from the existing 1 s stats loop.
- **Change detection:** any change in identity or limits replaces the state, bumps `limits_version`, and appends evidence
  `worker_capacity_changed` (old → new).
- **Inventory as expectation:** the inventory `context_limit`, `max_concurrency` and `model_id` are compared with the observed
  values. A mismatch produces evidence `worker_inventory_mismatch`, metric `aihost_worker_inventory_mismatch{worker_id,field}=1`,
  and a `/health` warning. Policy decided here: a mismatch in **model identity** blocks routing to that worker (fail closed:
  the wrong model must not serve under a pool's name). A mismatch in **numeric limits** does not block; the observed value
  governs (the observed limit is authoritative for sizing).
- **Unknown capacity** (adapter down, never observed): the worker is not eligible (fail closed). The previous last-known state
  is retained for display only.

## 3. Exact sizing and completion bounds (`orchestrator_runtime/sizing.py`)
- `prompt_tokens` comes from `count_prompt()` on the **selected worker** over the fully rendered request (messages, tool calls,
  tools schema, template overhead). Source = `exact`.
- If counting fails, the fallback is a conservative estimate: `ceil(len(canonical_json(request_without_sampling_params)) / 3)`.
  Source = `estimated_conservative`; it over-counts, so it fails safe. Evidence records the source.
- Completion bound for a request:
  `max_completion = min(client_requested?, route_output_cap, ctx_per_slot - prompt_tokens - safety_margin)` with
  `safety_margin = 16`.
  - `route_output_cap` comes from the route's reasoning/output policy (Design 02). It is always finite, and is the
    **default when the client omits max_tokens/max_completion_tokens**.
  - If `ctx_per_slot - prompt_tokens - safety_margin < min_completion` (64), the request is rejected with 400
    `context_length_exceeded`. The JSON body carries
    `{prompt_tokens, context_length, requested_completion, available_completion, worker_id, limits_version}`.
  - The bound is written into the forwarded request as both `max_tokens` and `max_completion_tokens` (monotonic: never
    above what the client asked for).
- **Fit-checked selection:** a worker is eligible for a request only if `prompt_tokens + min_completion + margin <= ctx_per_slot`.
  Counting needs a worker (each engine has its own tokenizer), so selection counts on the first candidate and re-counts on a
  fallback candidate if its `model_identity` differs.
- Remove `WorkerRecord.max_output_tokens` and the `ORCHESTRATOR_MAX_OUTPUT_TOKENS=512` default once this lands (todo item).

## 4. Capabilities with provenance (`orchestrator_runtime/capabilities.py`)
Capability names:
- `tools`, `parallel_tool_calls`, `structured_output`, `vision`, `reasoning`, `reasoning_controllable`, `streaming`;
- `output_contract_compliance` (verified-only);
- `fim` and `embeddings`: always `unavailable`, because the gateway does not expose `/infill` or `/embeddings`. An engine
  feature the gateway does not offer is not a capability of the alias.

Per worker, each capability is `{available: bool, provenance: "declared"|"verified"|"unavailable", evidence: [...], verified_at}`:
- **declared**, from the engine:
  - llama.cpp `chat_template_caps.supports_tool_calls` gives `tools`;
  - `supports_parallel_tool_calls` gives `parallel_tool_calls`;
  - `modalities.vision` gives `vision`;
  - `structured_output` is declared by engine type (llama.cpp grammar / `response_format` support);
  - `reasoning` when the template has reasoning support (`supports_reasoning_effort`, or the gateway knows the worker's
    reasoning budget);
  - `streaming` is always provided by the gateway.
- **verified**: an Ansible-managed evidence registry
  (`orchestrator_gateway_capability_evidence`, keyed by **artifact digest**), written from qualification runs:
  `{capability: {result: pass|fail, evidence_id, date}}`. A `fail` overrides a declaration to `available: false,
  provenance: "verified"` (e.g. Glimmer `reasoning_controllable: fail`).
- **Never assumed:** no declaration and no verification gives `available: false, provenance: "unavailable"`.
- `reasoning_budget` is reported as a limit (number) from the worker config, not as a boolean capability.

**Alias view = intersection** over every worker the alias can reach (pool plus route fallbacks):
- `available` only if all are available;
- provenance is the weakest present (verified > declared);
- numeric limits are the minimum.

This one model drives both `/v1/models` and R9 routing.

## 5. Admission, queueing, backpressure, adaptive concurrency (`orchestrator_runtime/admission.py`)
- Each worker has `concurrency_limit` (initially `slots_total`, bounded to `[1, slots_total]`). A request may dispatch to a
  worker only while `inflight < concurrency_limit` and the worker is eligible.
- **Queue:** one bounded queue per pool (`ORCHESTRATOR_QUEUE_MAX`, default 32).
  - Entries carry priority class, client id, deadline and enqueue time (R2/R7).
  - When a slot frees, the next entry is chosen by priority class, then fair share across clients, then FIFO.
  - A request that cannot be admitted waits until admitted, until `queue_max_wait` (default 120 s), or until its deadline.
  - Queue full or wait exceeded gives **429** with `Retry-After` (seconds, from p50 service time × position, clamped to
    [1, 120]) and code `capacity_exhausted`.
  - Context errors are never 429.
- **Saturation fallback:** a route may set `fallback_on_saturation: true`. Then, if the primary pool cannot admit but a fallback
  pool can (fit-checked), the request goes there. Default `false` (queue first: model quality is a route decision).
- **Adaptive concurrency (AIMD, bounded):**
  - On a success whose TTFT and decode rate are within 2× the worker's rolling median: `+1` (≤ slots_total) after N=5 consecutive
    healthy completions.
  - On a timeout, a 5xx, or TTFT > 3× median: halve (≥1).
  - Exposed as `aihost_worker_concurrency_limit`.
  - With today's `-np 1` workers the limit is 1, and AIMD only matters for multi-slot workers. Tests use multi-slot fakes.
- The worker queue inside llama.cpp is never used: the gateway never sends more than `concurrency_limit`.

## 6. Client-facing surface
- **`GET /v1/models`**, per alias (route aliases and public model ids):
  - `id`, `object`, `owned_by`;
  - `context_length`, `max_model_len` (= context_length), `max_completion_tokens`, `limits_version`;
  - `serving: [{worker_id, model_id, artifact_digest, quantization, engine, engine_version, pool, role}]`;
  - `capabilities: {name: {available, provenance, evidence}}`, `reasoning: {budget, default}`.
  Candidate aliases (R4) are listed only to clients with the `qualification` scope.
- **Response headers** on every completion:
  - `X-AIHost-Context-Limit`, `X-AIHost-Prompt-Tokens` (exact or `~n` when estimated), `X-AIHost-Prompt-Tokens-Source`;
  - `X-AIHost-Context-Remaining`, `X-AIHost-Max-Completion`, `X-AIHost-Limits-Version`;
  - `X-AIHost-Served-Model`, `X-AIHost-Termination` (Design 02), plus the existing `X-AIHost-Route`.
- **`POST /v1/tokenize`** `{model, messages, tools?}` returns `{model, prompt_tokens, source, context_length, limits_version}`.
  It counts on a worker that the alias can reach, using the same `count_prompt()`. Auth: workload scope.
- Rejections are machine-readable (section 3); capacity uses 429 + `Retry-After` (section 5).
- `GET /health` `workers.<id>` gains:
  - `capacity` (ctx_per_slot, slots_total, inflight, concurrency_limit, limits_version, engine_version);
  - `inventory_mismatch`;
  - `capabilities`;
  - `drain` (R5).

## 7. Interaction with other designs
- Design 02 supplies `route_output_cap` and the reasoning policy.
- R1/R7 use the in-flight registry built here for cancellation and deadlines.
- R2/R6 use the queue.
- R4 adds `role: candidate` workers that are excluded from normal routes.
- R5 adds `drain` to eligibility.
- Gateway-only access (Design 04) makes `inflight` authoritative.

## Review (2026-10-07)
- **Principle check:**
  - The gateway enforces bounds with no client cooperation: a default bound exists when max_tokens is omitted.
  - Observed limits override inventory.
  - Capabilities are never assumed.
  - Reporting is an aid, not a requirement.
  Passes.
- **Fail-closed check:**
  - Unknown capacity gives "not eligible".
  - A counting failure gives a conservative over-estimate.
  - A model-identity mismatch blocks routing.
  - There is no code path with an unbounded completion.
  Passes.
- **Determinism/audit:** routing stays first-match over declared features; queue order is deterministic given arrival order.
  Evidence records count source, limits_version and sizing decision. Passes.
- **Cost:** exact counting adds two loopback HTTP calls (apply-template + tokenize) per request: measured at single-digit ms for
  short prompts (to be confirmed in tests at 60K tokens). That is acceptable relative to multi-second prefill. If p95 > 250 ms at
  60K, cache the rendered-prefix count by message-prefix hash (prefix-cache style).
- **Checkpoint passed (2026-10-07, pinned build b11347 on worker1):** `/apply-template` renders the tools schema and the
  tool-call history. A 4-message conversation counts 64 tokens without tools and 301 with one tool definition, so today's
  chars/4-over-content estimate misses the 237 tool-schema tokens entirely. Counting a 30,000-token prompt took 65 ms end to end.
- **Risk:**
  - `/apply-template` must accept `tools`. To be verified against the pinned build before relying on it. If not, render without
    tools and add a tokenized count of the tools block as llama.cpp's template would include it. This is marked estimated unless
    verified.
  - Recorded as an implementation checkpoint.
- **Rejected alternatives:**
  - Static inventory limits (the status quo; they drift).
  - Client-supplied limits as authority (violates monotonicity).
  - Saturation fallback by default (silently degrades model quality).
