# Design 06: vllm-top engine-agnostic continuous discovery

- **Status:** ACCEPTED (review below), 2026-10-07.
- **Covers:** todo.md "Follow-up: vllm-top engine-agnostic discovery and monitoring", and the detection part of Design 04.
- **Target end state (operator):** whatever inference server is running (vLLM, llama.cpp, something else) is picked up and
  monitored automatically. That holds whether it is a gateway worker, a systemd unit or an ad-hoc process/container, and whether it
  started before or after the console.
- **Principle:** vllm-top observes and reports, including policy violations. It never acts on processes or servers.

## Current state (vllm-top 0.9.2)
- `discover.rs` finds candidates from systemd units and `/proc/*/cmdline` matching vLLM only, attributes sockets via
  `/proc/net/tcp` + `/proc/<pid>/fd`, and validates with `/health`, `/metrics`, `/v1/models`.
- Discovery runs once at startup (`config::resolve`).
- The gateway is read via `orchestrator.rs`, with workers as entries from the gateway `/health` engine_stats.
- GPU stats come from sysfs (`gpu.rs`), engine-independent already.

## Design
1. **Socket-driven discovery** (`discover.rs` rework, keeping its no-harvest rules):
   - Every `rediscover_interval` (default 5 s), read `/proc/net/tcp{,6}` LISTEN sockets on loopback, wildcard and host addresses.
   - Excluded ports:
     - the configured gateway monitoring port;
     - well-known non-inference ports (22, 53, 9100, 631; configurable `ignore_ports`);
     - sockets already classified within `fingerprint_ttl` (60 s; a closed socket is removed immediately).
   - Each new socket is fingerprinted with at most 3 bounded GETs (500 ms connect, 1 s read, 64 KiB cap, no redirects, no
     POST, no inference):
     - `GET /props` → llama.cpp (`build_info`/`default_generation_settings`);
     - `GET /version` + `/metrics` with `vllm:` → vLLM;
     - `GET /api/version` → Ollama;
     - `GET /get_server_info` → SGLang;
     - `GET /info` with `model_id` + `router` fields → TGI;
     - `GET /v1/models` with an OpenAI list shape → generic OpenAI-compatible;
     - otherwise not inference (cached as such for `fingerprint_ttl`).
   - A 401/403 on these paths with an OpenAI-shaped error is classified as **auth-required inference endpoint** (engine
     `unknown`, state `auth_required`). It is not dropped.
   - Process attribution (pid, uid, unit, container name) uses the existing `/proc/<pid>/fd` → inode method when permitted, else
     uid association. It is never read from env or config files.
2. **Engine adapters** (`engines/`), one trait `EngineAdapter { fingerprint(), poll() -> EngineSample }`. All of them normalise to
   the existing `Sample` model (model id, running/queued requests, prompt/decode tok/s, KV/context use, health, auth state). Each
   adapter declares which fields it can supply; missing fields render as `n/a`, never 0.

   | Adapter | Fingerprint | Live metrics |
   |---|---|---|
   | vLLM | `/version`, `vllm:` in /metrics | /metrics `vllm:*` (existing mapping) |
   | llama.cpp | `/props` | /metrics `llamacpp:*`, `/slots`, `/props` (n_ctx, slots) |
   | Ollama | `/api/version` | `/api/ps` (loaded models, size, expiry); no token rates (documented `limited`) |
   | SGLang | `/get_server_info` | /metrics `sglang:*` (num_running_reqs, num_queue_reqs, token_usage, gen_throughput) |
   | TGI | `/info` | /metrics `tgi_*` (tgi_queue_size, tgi_batch_current_size, tgi_request_*) |
   | Generic OpenAI | `/v1/models` | model list only; state `limited metrics` |

3. **Continuous lifecycle:**
   - Instances have states `up`, `down` (socket gone or polls failing for ≥ 3 intervals, kept visible for 5 min with
     last-seen), `auth_required`, and `limited`.
   - New instances appear without restart. Gateway workers flip to `down` when the gateway reports them unhealthy or their socket
     disappears.
4. **Gateway dedupe and policy:**
   - The gateway `/health` lists workers with `endpoint` (port). A directly discovered socket whose port matches a
     gateway-registered worker endpoint is **merged** into that gateway worker entry: one row, source `gateway+direct`. Direct
     polling of a gateway worker is not attempted, because Design 04 rejects non-gateway uids; the socket's presence is used for
     liveness only.
   - Any discovered inference server that is not gateway-registered and is not the gateway itself is flagged
     `POLICY: outside gateway`, with a distinct colour and a count in the header.
   - The gateway itself (the monitoring port) is recognised by its `/health` schema and shown as the orchestrator, not as a
     worker.
5. **Engine-independent GPU activity:** the existing sysfs GPU panel stays and is shown even when no inference server is
   recognised. The header shows "GPU busy, no recognised server" when GT activity > 20% and there are no active instances.
6. **CLI and config:** `--rediscover <secs>` (0 disables), `--ignore-port`. The existing `-u` endpoints still work and are merged
   by URL.
7. **Tests:** recorded fixtures under `vllm-top/tests/fixtures/<engine>/` (props/metrics/version/info JSON and text) drive
   fingerprint and normalisation unit tests per adapter, plus:
   - `/proc/net/tcp` parsing fixtures;
   - dedupe (gateway + direct same port gives one row);
   - lifecycle (socket gone → down → expired);
   - auth-required classification;
   - policy-violation flag.
8. **Versioning and deploy:** bump to 1.0.0; `vllm_top_console_min_version: "1.0.0"`; deploy via the `vllm_top_console` role
   (the binary is built on the controller).

## Review (2026-10-07)
- **Principle:**
  - Observes only: GETs, bounded, no inference, no env/config/credential reads.
  - Reports policy violations without acting.
  Passes.
- **Target coverage:**
  - Any engine on any port, including after start (socket-driven + rediscovery).
  - Unknown OpenAI-compatible servers are visible as `limited`.
  - Auth-protected endpoints are visible as `auth_required`.
  Passes.
- **Gateway-only interaction:**
  - vllm-top runs as the console user, so its direct polls of worker ports are rejected by Design 04.
  - Gateway workers are therefore observed via the gateway (authoritative) and socket presence.
  - Unregistered servers are polled directly (they are outside policy and on unreserved ports) and flagged.
  Consistent with Design 04. Passes.
- **Risk:**
  - Probing arbitrary local ports could disturb non-HTTP services. Mitigation: TCP connect plus one GET with a tight timeout; the
    `ignore_ports` default; non-HTTP sockets cached as non-inference for the TTL.
  - Acceptable.
