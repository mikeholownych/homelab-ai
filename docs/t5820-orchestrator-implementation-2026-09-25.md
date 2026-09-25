# T5820 Orchestrator Implementation Record

Date: 2026-09-25
Status: software-only implementation validated; live dual-worker integration blocked

## Implemented

- `orchestrator_runtime`: evidence-backed worker registry, exact model identity, expiry and health gating, append-only hash-linked evidence, provider adapter protocol, recorded adapter, OpenAI-compatible adapter, dependency-gated task graph, serial/parallel scheduler, external validation hook, and authority-separated tool execution.
- `orchestrator_gateway`: localhost-capable authenticated `/v1/models` and `/v1/chat/completions` endpoint with OpenAI response shapes, request IDs, body limits, SSE responses, unsupported-route rejection, and client/worker credential separation.
- `evaluations/run_contracts.py`: deterministic network-free runner for all 11 declared cooperative cases.
- `tools/t5820_dual_worker_preflight.py`: inspection-only fail-closed preflight for B0 state, worker path ownership, memory reserve, process residue and GPU discovery.

## Validated

- Runtime, gateway, offline evaluation and preflight tests pass.
- Full repository test run: `468 passed, 1 skipped, 2 unrelated failures`.
- The two unrelated failures are the pinned Ubuntu Docker package build and the pre-existing monitoring configuration-directory contract.
- Existing TP=2 B0 mode remains unchanged and supported.

## Live Behavior

- No authoritative orchestrator endpoint was deployed.
- The stdlib OpenAI provider adapter is implemented but has not been promoted against B0.
- No valid concurrent dual-worker runtime was established. Worker 2 and live cooperative execution remain untested.

## Limitations

- The current runtime ledger is in-memory; the evidence store is durable JSONL but task graph recovery/persistence is not yet a database-backed service.
- Tool execution requires an injected external executor and state-bound authority; the gateway exposes model tool calls as proposals only.
- Hardware validation remains blocked until a clean B0-to-experiment state transition can be proven by the preflight on the target host.
