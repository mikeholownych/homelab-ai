# Changelog

## 0.7.1

**Fixed** — GPU polling no longer rediscovers devices every 5s. `gpu::probe` ran `xpu-smi discovery -j`
on every poll; discovery also queries GPU firmware over the root-only MEI interface, which fails for an
unprivileged monitor and wrote hundreds of `Cannot establish a handle to the Intel MEI driver` /
`IGSC ... Failed to init HECI driver` lines to syslog per minute (and spawned an extra process each poll
on a CPU-starved host). The device list is now taken once at startup and only `xpu-smi stats` is polled.

**Added** — GPU temperature from the kernel's hwmon interface (package and video memory), matched to each
device by PCI address; needs no privileges and no `xpu-smi`. Shown as `temp 42°C (vram 46°C)`, amber at
80°C and red at 90°C; `temp n/a` when a device exposes no package sensor. Utilisation remains `n/a`
(the driver does not report it). 2 new tests (123 total).

## 0.7.0

**Added** — engine-agnostic per-worker view in the orchestrator panel. The gateway already holds each
worker's credential and polls it, so it now republishes the engine's own statistics (vLLM, llama.cpp) in
one neutral shape in `GET /health`; vllm-top reads only the gateway and never needs a worker key:
- per worker: routing pool and engine (`lead/llama.cpp`), running/waiting requests, KV-cache use, and
  prefix-cache hit rate where the engine reports it;
- reset-safe prompt/generation token rates derived from the gateway's own observation clock (the
  gateway refreshes about every 10s, so two polls usually see the same sample and keep the last rate);
- routing decisions by `rule → pool` from `aihost_route_decisions_total`.
Values an engine does not report are shown as `–`, never as zero. A gateway that predates these fields
renders exactly as before. 8 new tests (121 total).

## 0.6.0

**Added** — best-effort local orchestrator gateway integration
(`src/orchestrator.rs`), for hosts running one alongside vLLM (a separate
process/data-shape from a vLLM instance: `GET /health` returns gateway/
scheduler/worker JSON, and its Prometheus `/metrics` uses `aihost_*`
series, not `vllm:*`). Auto-detected the same way GPU telemetry is — try
the well-known local endpoint (`127.0.0.1:8010`, not yet configurable),
stay silently absent if nothing answers:
- A new `orchestrator` panel (only shown once one is actually detected —
  most deployments won't run one, so an always-present "unavailable"
  column would be clutter, unlike the GPU panel) showing gateway process
  liveness *and* overall routing readiness as two distinct facts (the
  same MON/SVC distinction this app already makes about itself — a
  gateway process can be "alive" while unable to route, exactly the real
  idle-staleness failure mode this integration was built against), plus
  scheduler state, per-worker health as the orchestrator itself observes
  it, and a dispatch-rate history graph using the same `gradient_graph_rows`
  btop-style multi-row technique as throughput/latency/requests.
- Reset-safe dispatch-rate derivation (`MetricsTotals::dispatch_rate`),
  the same delta-over-time convention `metrics::derive` already uses for
  vLLM's own rates.
- Parsing verified directly against the real gateway's actual JSON/metrics
  shapes (captured live), not a guessed schema.

**Fixed** — a real discovery false-positive this integration surfaced
live on its very first test: `discover::validate` accepted *any* service
answering `GET /health` with 2xx as "this is a vLLM instance." Combined
with uid-fallback attribution (which can't distinguish sockets owned by
different processes sharing one uid — see 0.3.2), a same-uid, unrelated
service with its own generic `/health` endpoint got listed as a fake
vLLM instance with garbage data (0 tok/s, no model, negative request
counts). Concretely: the new orchestrator integration's own gateway,
which happens to run as the same uid as this host's vLLM workers. Fixed
by requiring real, minimal vLLM-specific evidence — at least one
`vllm:`-prefixed series on `/metrics` (unauthenticated, like `/health`) —
before accepting a discovery candidate, rather than a generic health
check. 3 new tests, including the exact real vLLM and orchestrator
`/metrics` shapes that motivated the fix.

## 0.5.0

Three features pulled directly from btop's real source, in the order
requested, each verified against the actual upstream implementation
rather than approximated:

**Fixed** — console-safe graph glyphs corrected against btop's real
`tty_mode` (`src/btop_draw.cpp`: `tty_up`, byte-for-byte identical to
`tty_down` there):
- The previous fallback used 5 self-invented levels (` ░▒▓█`) at one
  sample per character. Real btop uses only 4 distinct glyphs (no `▓`)
  arranged as a 25-entry previous→current *transition* table — the same
  technique as the truecolor/Braille path (`TTY_LEVELS`, `src/ui/mod.rs`),
  not a flattened one-glyph-per-sample approximation. This restores the
  2x horizontal density the truecolor path already had, using glyphs
  individually confirmed (by writing them to a live TTY1 and reading back
  its screen buffer) to render correctly there.

**Added** — box visibility toggles, mirroring btop's digit-key box toggle
(`src/btop_input.cpp`; vllm-top uses **F1-F5** instead since 1-9 already
select instances): F1 overview, F2 graphs, F3 detail (service/gpu/session),
F4 instances, F5 requests. Hiding a box gives its height to the graphs
row automatically (falling back to detail if graphs itself is hidden) —
the same "no dead margin" mechanism 0.4.4 already established, not a
separate code path. (Not implemented: btop's saved-preset cycling through
multiple layouts — this round only adds the individual toggles, which are
the higher-value half of that feature.)

**Added** — instances table sort and filter, mirroring btop's process list
(`src/btop_input.cpp`: `proc_sorting`, `Proc::filter`): **s** cycles the
sort column (name/run/wait/kv/gen tok/s/req/s/ttft p99, plus the default
"natural" config order), **S** reverses direction, **/** opens live
filter-text entry (matched case-insensitively against instance name;
Enter confirms, Esc discards). The active sort column is marked in the
header (`gen tok/s*`); the panel title shows the active sort/filter state.
The "#" column always shows each row's *original* index regardless of
sort order, so the existing 1-9 instance-select keys keep working exactly
as before no matter how the table is currently sorted.

**Fixed** (found by this round's own sort-indicator test) — the "gen
tok/s" column was exactly 9 characters wide, the same length as the
column header text itself; appending the new `*` sort marker made it 10,
which silently truncated off every render. Widened to 10.

9 new tests (93 → 102) covering the tty glyph transition table,
box-toggle state and layout redistribution, sort/filter behavior, and the
truncation fix above.

## 0.4.4

**Fixed**
- The graphs and detail (service/GPU/session) rows were each independently
  height-capped in `compute_layout`, and their sum could fall short of the
  terminal's actual height — verified live at the real TTY1's 240×67: 5
  rows of dead blank space sat between the requests panel and the footer,
  which itself didn't reach the terminal's actual last row. Now the detail
  row is still capped (its content is short, static text that doesn't
  benefit from more height), but the graphs row takes 100% of whatever
  height detail doesn't use, so the two always sum to exactly the
  available space — the footer now lands on the terminal's true last row
  at any size. This also gives the throughput/latency/requests graphs
  more height on large terminals than before, which is a genuine
  improvement now that they're real multi-row `gradient_graph_rows`
  graphs (0.4.2) that render meaningfully at any height, rather than the
  old thin `Chart` lines this cap was originally designed around.
- New regression test (`layout_fills_the_full_terminal_height_leaving_no_dead_margin_before_the_footer`)
  checks the footer sits on the terminal's actual last row at four sizes,
  not just the one real TTY1 size the bug was first found at.

## 0.4.3

Root-causes why 0.4.2 (real braille technique, real per-row btop
algorithm, all verified against btop's own source) still looked "VERY
blocky" on the physical TTY1 console specifically. It wasn't a rendering
technique bug — checked directly against the live console rather than
guessed at further:

- **Color**: read the console's own screen buffer (`/dev/vcsa1`) while
  vllm-top was running on it. It stores exactly **1 byte of color
  attribute per character cell** — the classic VGA text-mode model, only
  a handful of palette slots (12 were in use, live). Every `Color::Rgb`
  gradient value this renderer sends gets silently quantized by the
  kernel's own VT layer to the nearest of those slots — this is
  documented Linux console behavior (`man console_codes`), not something
  fixable by emitting different escape codes.
- **Glyphs**: read the actual glyph-slot buffer in the throughput graph's
  screen region and found only 3 distinct glyphs ever appear there —
  blank, a thin line, and a solid square — regardless of which of the 256
  real Braille dot-patterns the code requested. `/etc/default/console-
  setup`'s own comments confirm why: Braille needs a dedicated special
  font (`brl-8x8.psf`) that isn't loaded. Separately, `BorderType::Rounded`'s
  corners (╭╮╰╯) all collapse to a generic `+` there too.
  Directly tested candidate fallback glyphs against a live TTY1 the same
  way (write, then read back `/dev/vcsa1`): the classic CP437 shade
  blocks `░▒▓█`, `■`, and `BorderType::Plain`'s box-drawing set
  (`┌┐└┘─│`) all map to correct, distinct native glyphs there.
- Corrects a wrong claim in 0.4.0's own changelog and this file's
  previous README note, both of which asserted the physical console
  "qualifies" for the truecolor assumption — it doesn't; that was never
  verified against the real device, only assumed.

**Fixed** — a raw-console-safe rendering mode, used automatically when
`TERM=linux` (`is_raw_console`, `src/ui/mod.rs`; SSH/tmux/GUI terminals
are unaffected and keep the existing truecolor+Braille rendering
unchanged):
- Panel borders use `BorderType::Plain` instead of `Rounded`.
- `gradient_color` picks from four named ANSI colors (`Green`/`Yellow`/
  `LightRed`/`Red`) at fixed thresholds instead of interpolating `Rgb` —
  deterministic, correctly-ordered steps instead of whatever the kernel's
  own nearest-color quantizer happens to produce for an arbitrary value.
- History graphs (`shade_graph_rows`/`shade_sparkline`) use one verified-
  safe shade-block glyph (` ░▒▓█`) per sample instead of a Braille
  previous→current transition — honest 1x horizontal resolution instead
  of a 4x claim that was never actually reaching the screen.
- The existing truecolor/Braille code paths are unchanged and unrenamed
  in behavior — only split out into their own functions
  (`braille_sparkline`, `braille_graph_rows`) so both modes are
  independently unit-tested (7 new tests) without depending on the test
  process's own `TERM`.

## 0.4.2

Addresses feedback that 0.4.1 was still "not there, marginal improvement"
despite fixing the meter/sparkline glyph techniques. What 0.4.1 didn't
touch was the single biggest, most visually dominant element on screen:
the throughput panel's ratatui `Chart`/`Dataset` widget, which drew two
thin single-pixel-wide braille lines with axis labels inside a panel tall
enough for a real graph — most of that panel was blank space around a
couple of squiggles. The latency and requests panels had the same defect
in miniature: a single-row sparkline squeezed into a `Min(1)` area that
could be several rows tall, with the extra rows going unused.

- **Throughput panel**: the `Chart`/`Dataset`/`Axis` widget is gone.
  Replaced with `gradient_graph_rows()` — btop's actual *multi-row*
  `Graph::_create` algorithm (`src/btop_draw.cpp`, verified against the
  real source, not approximated): each row is colored by its vertical
  position (top hot/red, bottom cool/green), and the value's braille
  glyph shows how far it reaches into that row's band. gen tok/s and
  prompt tok/s each get their own full-height graph block with a small
  header (current + peak), stacked top and bottom of the panel, instead
  of sharing a handful of chart rows with axis labels.
- **Latency** (e2e p99) and **requests** (running/waiting) history graphs
  now also use `gradient_graph_rows()` at their full allocated row height,
  instead of a single-row `gradient_sparkline` that left unused blank
  rows below it whenever the panel had more than one row to spare.
- `gradient_graph_rows()` correctly falls back to `gradient_sparkline`'s
  by-value coloring when given exactly one row — btop's own `height == 1`
  case is a genuinely different algorithm (no "row position" exists for a
  single row), not the banded one degenerated to one band.
- Removed now-dead code this exposed: the y-axis `nice_ceiling()` rounding
  helper and `Ring::points()` (both were Chart-only).

## 0.4.1

Corrects the 0.4.0 gradient rendering against btop's actual source
(`aristocratos/btop`, `src/btop_draw.cpp`/`btop_theme.cpp`), after
feedback that it still looked "blocky and clunky." It did — the previous
version approximated the *idea* of gradients without checking the real
implementation. Two concrete, verified corrections:

- **Meters** (`gradient_meter`): btop's meter is a solid glyph (`"■"`,
  literally `const string meter = "■";` in its source) drawn as a
  *foreground* color, both for filled and unfilled cells — not a
  background-colored blank space. A background-filled space renders as
  an edge-to-edge slab in every terminal font; the repeated glyph reads
  as a row of discrete meter segments, which is what actually looks like
  btop. Label/percentage text is now a plain prefix before the bar,
  rather than characters overlaid on top of it.
- **History graphs** (`gradient_sparkline`): replaced the previous
  8-level block-character approach (▁▂▃…█, one flat height per sample,
  no relation between adjacent characters) with btop's real technique —
  each braille character encodes the *transition* between the previous
  and current sample using btop's own 25-entry `braille_up` lookup table,
  giving 4x the effective vertical resolution per character and a
  visibly connected line rather than isolated bars.
- Colors themselves are unchanged (0.4.0 already used btop's real
  `cpu_start`/`cpu_mid`/`cpu_end`/`meter_bg` values) — this release fixes
  *how* those colors get applied to the screen, not what they are.

## 0.4.0

Rendering redesign toward an actual btop look, prompted directly by user
feedback that the previous rendering was "rather basic" despite the
0.3.0 information-architecture redesign already being in place. What was
actually missing was btop's signature *technique* — continuous,
per-value color gradients on every meter and history graph — not the
panel layout.

**Changed**
- Panel borders: sharp corners → rounded (`BorderType::Rounded`),
  everywhere, via the shared `panel()` helper.
- All meters (kv-cache, prefix-hit, running/waiting request gauges) are
  now custom-rendered gradient bars (`gradient_meter`, `src/ui/mod.rs`)
  instead of ratatui's flat-colored `Gauge` widget: a fixed
  green→amber→red gradient spans the bar's full width, and only the
  filled portion is revealed — a half-full meter shows just the
  green-to-amber half, not a solid green bar re-colored by its overall
  level. Label and percentage are overlaid directly on the bar.
- Both history sparklines (latency's e2e p99, requests' running/waiting)
  are now custom-rendered gradient graphs (`gradient_sparkline`) instead
  of ratatui's flat-colored `Sparkline` widget — each sample's block-
  height character is colored by its own value, so spikes visibly shift
  toward red rather than the whole graph being one flat color regardless
  of how high it's spiking.
- `gauge_color()` and `color_for_p99()` keep their existing signatures
  and call sites (kv% coloring, latency coloring throughout the instances
  table and elsewhere) but are now thin wrappers over the shared
  `gradient_color()` function — smooth coloring everywhere those were
  already used, with no call-site changes required.

**Not changed this round** (explicitly deferred, not silently dropped):
the throughput/latency line `Chart`s (multi-series, axis-labeled) still
use ratatui's built-in `Chart`/`Dataset` — a gradient area-fill treatment
for those would require replacing the widget essentially from scratch,
a larger and riskier undertaking than the rest of this work.

**Assumes a truecolor-capable terminal** (`Color::Rgb`) for the new
gradients — the same assumption btop itself makes by default. No 256-
color fallback is implemented.

## 0.3.2

**Fixed**
- Discovery identity mislabeling when two or more vLLM-looking processes
  run as the *same* system uid — a real scenario, not hypothetical: this
  host now runs two independent single-GPU vLLM workers
  (`aihost-vllm-worker1`/`worker2`) under one service account. Since
  uid-association attribution can't tell same-uid processes' sockets
  apart, the previous code let whichever candidate was processed first
  silently claim every port for that uid, mislabeling worker2's port as
  belonging to worker1. Now reports an honest combined identity ("uid 999
  shared by systemd aihost-vllm-worker1.service +
  aihost-vllm-worker2.service") instead of a false specific claim. Both
  workers' actual endpoints were always discovered correctly — only the
  "discovered via" label was wrong.

## 0.3.0

Layout and presentation redesign, prompted by the physical TTY1 console
(240×67) making it obvious that the previous fixed/`Min()`-based layout
let the latency panel balloon to ~37 rows of near-empty space, while the
crowded "stats" panel crammed service, discovery, GPU and session
information into one place.

**Changed**
- Row heights are now computed from the actual terminal size every frame
  (`compute_layout`, `src/ui/mod.rs`) instead of a fixed `Min()`/`Length()`
  mix — graphs are capped at a sensible height regardless of how much
  extra room the terminal has, so extra space no longer becomes empty
  chart area.
- The "stats" panel is split into three dedicated panels — **service**
  (endpoint, discovery source, attribution confidence, auth, vLLM
  version, model), **gpu** (see below), and **session** (monitor-lifetime
  totals) — each with room to be legible instead of crowded together.
- New KPI **overview** strip (wide terminals only, ≥100 cols): model,
  running/waiting, throughput, KV cache, TTFT p99, total GPU power at a
  glance.
- The header now shows **MON** (the monitor's own render/poll loop) and
  **SVC** (the monitored instance(s)' health) as two explicit, separately
  colored indicators — a healthy monitor correctly reporting a dead
  service no longer looks like the monitor itself is broken.
- Minimum terminal size unchanged at 90×35; the new layout was verified
  down to that size and up to the real TTY1's 240×67 without panicking or
  corrupting panel borders (56 rendering tests, several exercising this
  directly).

**Added**
- GPU panel now shows device name, total memory (used/total GiB with a
  utilization percentage — preferring `xpu-smi`'s own reported percentage
  over a derived one when both are available), and PCIe generation/link
  width when the driver reports them (`src/gpu.rs::GpuInfo`, fetched once
  at startup — these are static properties, not re-polled every cycle).
  **Verified live**: this deployment's PCIe generation/link width are
  themselves reported as unavailable by `xpu-smi` (the "N/A" string,
  normalized to a real absent value here) — direct evidence of the PCIe
  link negotiation limitation, not an assumption.
- One GPU's telemetry failing no longer hides another's — each device
  row is built independently (regression-tested).

**Fixed** (found during this round's own testing, not previously reported)
- A truncation bug: with three narrower panels instead of two wider ones,
  the discovery-method-plus-confidence text could truncate mid-word,
  potentially cutting off the confidence label entirely. Split onto two
  lines instead of one.
- A hard-clipping bug: a long GPU device name plus its PCI address could
  overflow its panel's width and get clipped by the terminal buffer
  instead of ending cleanly with "…". Now truncated against the actual
  panel width before rendering.
- A test-quality bug in the new UI test suite itself: an early version of
  the panel-content test helper always located the *first* bordered panel
  on a shared header row, so assertions aimed at the "gpu" panel were
  silently checking the "service" panel instead. Fixed to locate the
  specific panel a title fragment belongs to.

## 0.2.0

**Fixed**
- The TUI footer's version string was a hardcoded literal (`vllm-top 0.1`)
  independent of the actual build. It now reads `env!("CARGO_PKG_VERSION")`,
  the same source `--version` and the HTTP `User-Agent` already used, so
  all three are guaranteed consistent.

**Added**
- Automatic local vLLM discovery (systemd unit + `/proc` scan + socket-table
  port resolution + bounded `/health`/`/v1/models` probing), with
  exact-socket (`Verified`) vs. same-uid (`UidAssociation`) attribution
  confidence, and deterministic ambiguity handling — never guesses when
  more than one live candidate claims the same identity.
- API key support: `--api-key` / `api_key =` in TOML / `VLLM_API_KEY`
  environment variable, sent as `Authorization: Bearer`. Never read from
  another process's environment or config file.
- A materially expanded stats panel: which endpoint is selected, how it
  was found (discovery vs. explicit config) and with what confidence,
  auth status, vLLM version, served model + context length, and
  distinguishing "the process answers" (health) from "the API is
  authenticated" (auth) from "we're currently collecting metrics"
  (last-collected time).
- Monitor-lifetime cumulative statistics (`SessionTotals`): tokens/requests
  observed since `vllm-top` itself started, shown alongside vLLM's own
  server-lifetime totals rather than conflating the two. Resets whenever
  `vllm-top` restarts; correctly ignores (rather than negatively
  crediting) a vLLM server restart mid-session.
- Best-effort local GPU telemetry via `xpu-smi` (Intel), on its own 5s
  cadence, never blocking the render loop. Fields the tool doesn't report
  are shown as unavailable, never fabricated as zero.
- A dedicated systemd service, `vllm-top-console.service`, to run
  `vllm-top` as the persistent monitoring console on TTY1 — see
  `deploy/DEPLOYMENT.md`.

**Changed**
- Minimum terminal size raised from 90×28 to 90×35 to fit the expanded
  stats panel.

## 0.1.0

Initial release: direct vLLM `/metrics` scraping, Prometheus-mode
querying, multiple simultaneous instances with an aggregate view, TOML
configuration, `--once`/`--demo` modes.
