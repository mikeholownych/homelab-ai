# vllm-top

A btop-style terminal monitor for [vLLM](https://github.com/vllm-project/vllm)
usage and performance, written in Rust.

It scrapes vLLM's Prometheus-format `/metrics` endpoint (or queries an existing
Prometheus server) and renders live gauges, graphs and tables. See
`CHANGELOG.md` for release notes.

```
 vllm-top   all   1:local ●  2:gpu-node-09 ●  3:cluster-prom ✕  Connection refused   19:00:34 │ poll 1.0s │ ▶ live
┌  throughput · aggregate  ────────────────────────────┐┌  kv cache  ──────────────────────────────────────────┐
│5.0k│                                                 ││████████████████████████kv cache 50.1% ████████████ │
│    │               ⢀⠤⣄          ⢠⠃⠈⢣         ⡰⠁  ││███████████████████████  prefix hit 55.0%            │
│    │ ⢀⡔⠒⡄         ⢀⠏ ⠈⢆        ⢠⠃   ⢣       ⢠⠃  ││model    unsloth/Llama-3.2-1B-Instruct               │
│2.5k│⡸    ⢱       ⡸     ⠸⡀     ⡸      ⠸⡀    ⡸      ││cached   61.5% of prompt tokens                     │
│    │⠲⢤⡀               ⣠⠴⠒⠒⠒⠤⣀               ││hit rate 55.0%                                      │
│0   │└────────────┘                                   │└────────────────────────────────────────────────────┘
└──────────────────────────────────────────────────────┘
┌  latency  ──────────────────────────────────────┐┌  stats  ──────────────────────────────────────┐
│        p50        p99        avg        samples  ││source  aggregate of 3 instances              │
│ttft    226.0ms    441.9ms    141.2ms    2.0k     ││uptime  5h 00m 00s  (240 polls)               │
│queue   35.7ms     185.9ms    58.4ms     2.0k     ││prompt  1.7M  (+712/s)                         │
│e2e     3.30s      6.84s      4.12s      2.0k     ││output  4.9M  (+3.4k/s)                        │
│itl     19.6ms     40.4ms     31.7ms     2.0k     ││done    2.1k  (abort 15 · length 784 · stop 1.3k)│
└──────────────────────────────────────────────────┘└───────────────────────────────────────────────┘
```

## Build

```sh
cargo build --release          # binary at target/release/vllm-top
cargo install --path .         # install globally as `vllm-top`
cargo uninstall vllm-top       # remove it again
```

`cargo install` puts the binary in `~/.cargo/bin`, which `~/.profile` and
`~/.bashrc` already put on PATH (rustup does this). A small wrapper is also
installed at `~/.local/bin/vllm-top` so the command resolves in
non-interactive shells — scripts, `sh -c`, CI — that never source those files.

```sh
vllm-top --help
```

## Usage

```sh
# no flags: auto-discovers a local vLLM server (see "Auto-discovery" below)
vllm-top

# a specific server
vllm-top -u http://10.0.9.21:8000

# a server that requires an API key
vllm-top -u http://10.0.9.21:8000 --api-key sk-...   # or: export VLLM_API_KEY=sk-...

# several instances: tabs in the header, plus an aggregate "all" view
vllm-top -u http://gpu-01:8000 -u http://gpu-02:8000

# roll your own metrics up through an existing Prometheus
vllm-top --kind prometheus -u http://prometheus:9090

# plain-text snapshot, no TUI (exits non-zero if an instance failed)
vllm-top --once

# render one frame with synthetic data — handy for previewing the layout
vllm-top --demo
```

### Keybinds (btop-style)

| key | action |
| --- | --- |
| `q` / `esc` | quit |
| `tab` / `shift-tab` / `←` / `→` | cycle views |
| `1`-`9` | jump to an instance |
| `a` | aggregate view |
| `p` | pause/resume history |
| `r` | poll now |
| `+` / `-` | faster / slower poll interval (250ms steps, 250ms–10s) |
| `F1`-`F5` | toggle overview / graphs / detail / instances / requests box |
| `s` / `S` | cycle instances-table sort column / reverse direction |
| `/` | filter instances table by name (enter confirms, esc discards) |
| `?` | help overlay |

## Auto-discovery

With no `--url` and no config file, `vllm-top` looks for a vLLM server
running on the local machine instead of just guessing `localhost:8000`.
It never reads another process's config file or environment — those are
routinely permission-restricted on a hardened deployment (a vLLM service
running as its own system user with a `600` config/env file), and asking
for elevated privileges just to monitor metrics would be the wrong
tradeoff. Instead it uses only what's already visible to any local user:

1. **Find the process.** Look for a `vllm.service`-style systemd unit
   (matched by name, e.g. `vllm.service`) or a bare `vllm serve` /
   `python -m vllm.entrypoints.openai.api_server` process via
   `/proc/<pid>/cmdline` (world-readable, unlike `/proc/<pid>/environ` or
   `/fd`, which are never touched).
2. **Find the real port.** Read `/proc/net/tcp`/`tcp6` (the global socket
   table) for the LISTEN sockets owned by that process's user, rather than
   assuming a port — a `--host 0.0.0.0 --port 1234` server is found
   correctly, and so is one behind `--config some.yaml` whose contents
   `vllm-top` has no permission to read.
3. **Validate, don't guess.** A bounded (~1.5s), one-shot `GET /health`
   confirms it's actually answering, and `GET /v1/models` (metadata only —
   never triggers inference) classifies whether auth is required. A
   process's user commonly owns several other listening sockets too (e.g.
   a multi-GPU server's internal worker RPC ports); all candidates are
   probed concurrently so discovery stays fast regardless of how many
   there are.
4. **Never harvest credentials.** An API key is only ever taken from
   `vllm-top`'s *own* `--api-key` flag, `api_key =` in its TOML config, or
   a `VLLM_API_KEY` environment variable read from `vllm-top`'s own
   process — never from the vLLM process's environment or config file.
   Since vLLM only gates `/v1`, `/v2`, `/inference` and `/cohere` (not
   `/metrics` or `/health`), direct-scrape monitoring works with no
   credential at all in most deployments; a key only matters for the
   auth-state check itself and for `--kind prometheus` targets that sit
   behind their own auth.

An explicit `--url` or TOML `[[instances]]` entry always wins over
discovery. If it happens to point at `localhost`/`127.0.0.1`/`::1` and
doesn't set its own `api_key`, the `VLLM_API_KEY`-from-environment /
`--api-key` value is still applied to it — remote instances are left
alone unless they set `api_key =` themselves.

If the locally selected instance goes down, `vllm-top` re-runs discovery
for it (at most once every 30s, not on every poll) to see whether it
reappeared at a different address — matched by a stable identity (the
systemd unit name, or the matched command line for a non-systemd
process), never by PID, since a restart can reuse one.

**Known limitations:** a rootless container running under a different
Linux user than `vllm-top` is invisible beyond what systemd/`cmdline`
already reveal — direct container-runtime inspection isn't attempted. A
firewall that blocks inbound access to the API port only affects other
hosts reaching in; it doesn't affect `vllm-top` probing over loopback on
the same machine. If nothing is found, the old unauthenticated
`http://localhost:8000` default is used as a last resort.

## Configuration

Copy `vllm-top.example.toml` to `./vllm-top.toml` or
`~/.config/vllm-top/config.toml`:

```toml
poll_ms = 1000
history = 240

[[instances]]
name = "local"
url = "http://localhost:8000"
kind = "direct"          # or "prometheus"
# api_key = "sk-..."     # optional; omit to rely on auto-discovery/VLLM_API_KEY
```

`--url`, `--poll-ms`, `--history` and `--api-key` on the command line
override the file.

## What it shows

| panel | source metrics |
| --- | --- |
| throughput graph | deltas of `vllm:prompt_tokens` / `vllm:generation_tokens` per second |
| kv cache gauges | `vllm:kv_cache_usage_perc`, `vllm:prefix_cache_hits`/`_queries`, `vllm:prompt_tokens_cached` |
| latency table | p50/p99 interpolated from `vllm:time_to_first_token_seconds`, `vllm:request_queue_time_seconds`, `vllm:e2e_request_latency_seconds`, `vllm:inter_token_latency_seconds` histogram buckets |
| requests | `vllm:num_requests_running`, `vllm:num_requests_waiting`, `vllm:request_success`, `vllm:num_preemptions` |
| instances table | one row per endpoint, with health (`ok` / `stale` / error) |
| overview strip (wide terminals, ≥100 cols) | model, running/waiting, throughput, KV cache, TTFT p99, total GPU power — the at-a-glance summary |
| service panel | selected endpoint, discovery provenance + attribution confidence, auth status, vLLM version, served model + context length |
| gpu panel | per-device name, memory used/total + utilization, power, PCIe link state when reported |
| session panel | all-time (vLLM server) vs. session (this monitor run) token/request totals |

Notes:

- **Direct mode** hits `<url>/metrics`, so nothing extra needs to be deployed.
- **Prometheus mode** runs one instant-vector query
  (`{__name__=~"vllm:.*"}`) per poll against `/api/v1/query`; rates and
  history are still computed locally, so no recording rules are required.
- Counter resets (a restarting server) are detected and reported as `0/s`
  rather than a negative spike.
- Fetches run on short-lived threads, so a slow or dead endpoint never
  blocks the UI.
- The header's **MON**/**SVC** indicators are deliberately separate: MON
  reflects `vllm-top`'s own render/poll loop (if a frame is drawing, it's
  alive — "paused" is the only other honest state it can report); SVC
  reflects the monitored instance(s). A healthy monitor correctly
  reporting a down service shows `MON ok` next to `SVC down` — never one
  merged "something's wrong" indicator that could be misread either way.
- Meters (kv-cache, prefix-hit, running/waiting) use a continuous
  green→amber→red color gradient — btop's technique, rather than a
  handful of discrete color buckets — so a meter's fill color scales
  smoothly with the actual value, on any truecolor-capable terminal (SSH,
  tmux, any modern GUI terminal emulator).
- The history graphs (throughput, latency, requests) use btop's real
  *multi-row* graph technique, not a single thin chart line: each row is
  colored by its vertical position (top hot/red, bottom cool/green,
  regardless of the data), and the braille glyph in each cell shows how
  far the value reaches into that row's band, so the graph fills its
  panel's full height instead of leaving most of it blank around a couple
  of pixel-thin lines.
- **The physical Linux console (`TERM=linux`, e.g. TTY1) does *not*
  qualify for either of the above** — an earlier version of this file
  wrongly claimed it did. Verified directly against a live console's own
  screen buffer (`/dev/vcsa`): color is hard-capped at a handful of
  palette slots (1 byte of attribute per character cell, the classic VGA
  text-mode model — no font or escape-code choice changes this), and the
  default console font has no Braille glyphs and no rounded box-drawing
  corners, both of which silently collapse to a generic blank/line/block/
  `+` substitute. `vllm-top` detects this (`is_raw_console`,
  `src/ui/mod.rs`) and automatically switches to a console-safe mode:
  plain (non-rounded) borders, four named ANSI colors instead of a
  continuous gradient, and one classic CP437 shade-block glyph
  (` ░▒▓█`) per sample instead of Braille — all individually verified to
  render correctly there. SSH/tmux/GUI terminal sessions are unaffected.
- Row heights are computed from the actual terminal size every frame
  (`compute_layout`, `src/ui/mod.rs`), not fixed — graphs are capped so a
  very tall terminal doesn't turn extra height into empty chart space.
  Verified against both the real TTY1 console (240×67) and the enforced
  minimum (90×35).

### Statistics semantics

Two different kinds of "cumulative" number appear side by side in the
stats panel, and they are deliberately never conflated:

- **All-time**: vLLM's own server-lifetime counters (`vllm:prompt_tokens`
  etc.), read fresh from `/metrics` every poll. These only reset when the
  vLLM *server* restarts — `vllm-top` restarting has no effect on them.
- **Session**: work `vllm-top` itself has observed since *it* started
  watching this instance (`SessionTotals`, `src/metrics.rs`). Computed as
  the running sum of reset-safe per-poll deltas — the same `delta()` logic
  already used for rates — so a vLLM server restart mid-session
  undercounts by at most one poll interval rather than going negative or
  crediting the server's pre-existing total as work done this session.
  Resets to zero whenever `vllm-top` restarts, by construction (it's
  in-memory state with no persistence — no database is used or needed).

### Aggregation semantics (aggregate view)

Every metric in the aggregate view has one explicit rule, applied in
`Snapshot::merge` / `merge_derived` / `SessionTotals::merge`
(`src/metrics.rs`) — nothing is combined ad hoc:

| metric | rule |
| --- | --- |
| token/request counters, session totals, preemptions, prefix hits/queries | sum |
| KV-cache usage, latency quantiles (p50/p99) | averaged, weighted by each instance's sample/request count |
| running/waiting requests | sum |
| discovery/connection status | not merged — shown as a per-state count ("2 ok · 0 stale · 1 down"), since "auto-discovered via X" or an auth state isn't meaningful summed across different instances |

## GPU telemetry

Where a GPU telemetry tool is available locally, `vllm-top` shows a
dedicated **gpu** panel with per-device name, memory (used/total GiB +
utilization), power draw, and PCIe link state when reported. Two calls
feed it, on different cadences: static identity (name, total memory,
PCIe generation/width — `xpu-smi discovery -d <N> -j`) is fetched once at
startup, since a GPU's name and installed memory can't change during a
session; live counters (power, used memory, memory utilization —
`xpu-smi stats -d <N> -j`) are refreshed on their own ~5s cadence,
independent of the metrics poll interval so it never adds load to that
hot loop. One device's probe failing never hides another's — each row is
built independently.

Today that means Intel's `xpu-smi` — chosen because it's what's actually
installed on the hardware this was built against, not because of any
hard dependency on Intel specifically. No NVIDIA-specific tooling is
required or assumed; if `xpu-smi` isn't present, this degrades to
"unavailable" immediately and cheaply, every time, rather than erroring.

**Known limitations, verified directly (not assumed):**
- On the Intel Arc Pro B65 deployment this was built against, `xpu-smi`
  itself reports GPU utilization, temperature and memory bandwidth as
  absent — not present in its own JSON output — while power draw and
  memory usage/utilization are available.
- **PCIe link negotiation**: `xpu-smi`'s own detailed device query
  reports `pcie_generation` and `pcie_max_link_width` as the literal
  string `"N/A"` on this deployment (normalized here to a real absent
  value, never displayed as the text "N/A") — confirmed by direct query,
  not assumed from the earlier, less specific report of a "known PCIe
  limitation."
- Several of `xpu-smi`'s firmware-version queries fail with `Permission
  denied` on `/dev/mei*` (Intel ME/HECI interface, `root`-only on this
  host for *any* user — confirmed by reproducing the identical failure
  with a plain interactive, unsandboxed call, i.e. this is not caused by
  `vllm-top`'s own systemd sandboxing). This doesn't affect the fields
  `vllm-top` actually reads.

Whichever fields aren't available are shown as unavailable; none are ever
fabricated as zero.

## Orchestrator gateway

Some deployments run a separate orchestrator/gateway process in front of
their vLLM workers (auth boundary, request routing, scheduling) — a
genuinely different thing from a vLLM instance: its own process, its own
`GET /health` shape (gateway/scheduler/per-worker JSON, not vLLM's
metrics-only surface), and its own Prometheus `/metrics` series
(`aihost_*`-prefixed, not `vllm:*`). `vllm-top` auto-detects one the same
way it handles GPU telemetry — try the well-known local endpoint
(`127.0.0.1:8010`, not yet configurable) and stay silently absent if
nothing answers, no configuration required.

When detected, a dedicated **orchestrator** panel shows:
- The gateway **process's** own liveness and the **overall routing
  readiness** as two distinct facts, not one collapsed indicator — the
  same MON/SVC distinction `vllm-top` already makes about itself. This
  matters concretely: a real failure mode is the gateway process staying
  alive while its worker-health dependency goes stale and it stops being
  able to route, which looks identical to "everything's fine" if you only
  check whether the process is running.
- Scheduler state (ready/blocked, queued/active work, available workers)
  and per-worker health **as the orchestrator itself observes it** —
  useful to cross-check against `vllm-top`'s own direct worker discovery
  elsewhere on screen; the two are independent views and can legitimately
  disagree during a transition.
- A dispatch-rate history graph, using the same real btop multi-row
  `gradient_graph_rows` technique as the throughput/latency/requests
  graphs — not a separate, simpler rendering path.

Most deployments won't run one of these at all, so its absence is the
normal, silent default (no "orchestrator: unavailable" placeholder like
the always-present GPU panel) — the detail row stays its usual 3 columns
until one is actually found.

**A same-uid gotcha this surfaced and fixed**: if the orchestrator (or any
other unrelated local service) runs as the same system uid as the vLLM
workers, `vllm-top`'s discovery previously had no way to tell their
sockets apart by uid alone (a known, documented limitation — see
[Auto-discovery](#auto-discovery)) *and* accepted any `GET /health` 2xx as
sufficient proof of being vLLM. That combination meant a same-uid,
unrelated service with its own generic `/health` endpoint got listed as a
fake vLLM instance with garbage data. Discovery now additionally requires
real evidence — at least one `vllm:`-prefixed series on `/metrics` — before
accepting a candidate.

## Development

```sh
cargo test                      # parser / metrics / formatting tests
cargo run -- --demo             # text render of one frame (no server needed)
python3 tools/mock_vllm.py 8000 # fake vLLM with moving counters, for manual testing
cargo run -- -u http://127.0.0.1:8000
```

`tools/mock_vllm.py` serves both `/metrics` and `/api/v1/query`, so it can be
used to exercise either source kind.

Requires a terminal of at least **90×35**.

## TTY1 deployment

`vllm-top` can run as the persistent monitoring console on a physical
console (TTY1), started automatically at boot, alongside normal
interactive use from SSH/other terminals — see `deploy/DEPLOYMENT.md` for
the systemd unit, install/upgrade/rollback procedure and troubleshooting.
Administrative access is unaffected: this only ever touches `getty@tty1`,
never SSH, PAM or sudo.

## Layout

```
src/main.rs      CLI entry, --once/--demo modes, terminal restore on panic
src/cli.rs       clap definitions
src/config.rs    CLI + TOML merging, instance naming
src/discover.rs  local vLLM discovery: systemd/proc, socket table, auth probing
src/gpu.rs       best-effort local GPU telemetry via xpu-smi
src/promparse.rs Prometheus text exposition parser
src/source.rs    MetricsSource: direct scrape and Prometheus query
src/metrics.rs   sample -> Snapshot extraction, histograms, rate derivation, session totals
src/history.rs   fixed-size rings feeding the graphs
src/app.rs       per-instance runtimes, aggregate view, polling threads, keys
src/ui/mod.rs    btop-style panels
src/util.rs      number/latency/duration formatting
```
