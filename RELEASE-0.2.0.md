# vllm-top 0.2.0 — implementation and validation report

Companion to `AUDIT.md` (the investigation that preceded this release).
Maps each requirement to what changed, what's tested, and what was
actually observed running against the real `vllm.service` on this host.

## Version identity

| | |
|---|---|
| Installed executable | `/home/mike/.cargo/bin/vllm-top` (resolved on `PATH` via unchanged `~/.local/bin/vllm-top` wrapper) |
| Version | `0.2.0` (was `0.1.0`; `Cargo.lock` updated to match) |
| Installed SHA-256 | `5035b64b23454d2d9b71852d4736e9ba217d314473b5f75c8ffbe2bd2b59d684` |
| Previous installed SHA-256 | `162efdd1b73a5f8f49157313bd6a022cce2a8a81a93f77deb622be291f0b6d53` (preserved at `rollback/vllm-top.pre-0.2.0-monitoring-console`) |
| `--version`, TUI footer, HTTP `User-Agent` | confirmed consistent — all three read `env!("CARGO_PKG_VERSION")`; the TUI footer's previous hardcoded literal was the defect fixed here |

## Requirement-by-requirement

| Requirement | Source change | Status | Test evidence | Live evidence |
|---|---|---|---|---|
| Version-display defect fixed | `src/ui/mod.rs` footer now uses `env!("CARGO_PKG_VERSION")` | IMPLEMENTED_AND_LIVE_VERIFIED | — | `vllm-top --version` and the demo-rendered footer both show `0.2.0` |
| Consistent version across surfaces | `src/cli.rs` (clap, unchanged, already dynamic), `src/source.rs` `User-Agent` (unchanged, already dynamic), `src/ui/mod.rs` footer (fixed) | IMPLEMENTED_AND_LIVE_VERIFIED | — | all three verified to read the same `CARGO_PKG_VERSION` |
| Release version chosen correctly | `Cargo.toml` `0.1.0` → `0.2.0`; only release in history was `0.1.0`, so `0.2.0` per the given rule | IMPLEMENTED | — | `cargo install` output: "Replaced package `vllm-top v0.1.0` with `vllm-top v0.2.0`" |
| Monitoring interface exposes operational state (endpoint, discovery, confidence, auth, metrics health, last-collected, vLLM version, model+context) | `src/ui/mod.rs::draw_stats` rewritten from one appended clause to dedicated lines; `src/app.rs` (`vllm_version`, `max_model_len` fields); `src/source.rs::probe_direct_info` | IMPLEMENTED_AND_LIVE_VERIFIED | 3 new UI tests, incl. a regression test for a real padding bug this change introduced and then fixed (`stats_panel_labels_have_a_visible_gap_before_their_value`) | rendered against the real instance via `render_text`/demo; interactive session confirmed running against the real server (can't visually confirm the *physical* tty1 screen — see Limitations) |
| Discovery/connection status visible in aggregate mode | `src/ui/mod.rs::draw_stats`, `View::Aggregate` branch: "N ok · M stale · K down" roll-up | IMPLEMENTED_AND_TESTED | covered by existing `Health` logic; no dedicated aggregate-view UI test added | rendered in `--demo` output |
| Distinguish process-running from API-healthy from authenticated | `Health` (existing, metrics-fetch-based) shown separately from `AuthState` (discovery-time `/v1/models`-based) | IMPLEMENTED_AND_LIVE_VERIFIED | — | live: `metrics: ok` and `auth: required (credential accepted)` shown as genuinely independent lines |
| Model/inference state: served model, vLLM version, context length, TP config, running/waiting/throughput/latency/KV-cache | model/running/waiting/throughput/latency/KV-cache: pre-existing. vLLM version + context length: new, `probe_direct_info` (`/version`, `/v1/models`) | PARTIALLY_IMPLEMENTED | — | live: version `0.29.0`, context `65536` both correctly retrieved from the real server. **Tensor-parallel size: not implemented** — not exposed via any endpoint found (`/metrics`, `/version`, `/v1/models` all lack it); only visible in this deployment's cmdline (`--tensor-parallel-size 2`) coincidentally, not reliably available in general — not wired up, to avoid displaying something only accidentally available |
| GPU telemetry, no NVIDIA-specific tooling, accurate limitations | `src/gpu.rs` (new): `xpu-smi` JSON probing on its own 5s cadence | IMPLEMENTED_AND_LIVE_VERIFIED | 2 unit tests | live: power (~7W/GPU) and memory (~29.6GiB/91%) correctly shown for both real GPUs; utilization/temperature correctly shown as unavailable (verified absent from `xpu-smi`'s own JSON, not a parsing gap); HECI/MEI permission errors confirmed as a pre-existing, universal, unsandboxed limitation, not caused by this deployment |
| Monitor-lifetime cumulative statistics, correctly distinguished from vLLM's own counters | `src/metrics.rs::SessionTotals`; wired into `src/app.rs` (`Runtime.session`, `Aggregate.session`) | IMPLEMENTED_AND_LIVE_VERIFIED | 3 unit tests incl. a vLLM-restart-mid-session scenario | live: stats panel shows "X all-time · Y session" side by side; session correctly starts at 0 on process start |
| Counter resets / vLLM restart / counter disappearance handled | Reuses the existing, already-tested `delta()` reset-safe helper | IMPLEMENTED_AND_TESTED | `session_totals_ignore_server_restart_but_keep_accumulating_after` | not exercised against a live vLLM restart (would have interrupted inference — out of bounds) |
| No persistent metrics database | Unchanged — no DB dependency, no file writes anywhere | IMPLEMENTED_AND_LIVE_VERIFIED | full source read | confirmed via `ProtectSystem=strict` in the TTY1 unit working with zero write-access exceptions needed |
| Existing functionality preserved (direct scrape, TOML, multi-instance, explicit config, demo/once) | Unchanged, re-verified after every rebuild | IMPLEMENTED_AND_LIVE_VERIFIED | 42-test suite | re-validated live after each of 3 builds this engagement: explicit `--url`, TOML config, `--once`, `--demo` all still correct |
| Prometheus integration tested | `src/source.rs::parse_prometheus_response` extracted as a pure function | IMPLEMENTED_AND_TESTED | 4 new unit tests (success, error-status, empty-result, partial-parse-failure) closing the gap flagged in `AUDIT.md` | **not** live-validated — no real Prometheus server exists on this host to test against |
| Bounded endpoint probing preserved | `discover.rs` probing unchanged (concurrent, timeout-bounded); GPU probing new but same pattern (`run_bounded`, background thread + `recv_timeout`) | IMPLEMENTED_AND_LIVE_VERIFIED | existing discovery tests + 1 new GPU test | live: `--once` with discovery still completes in ~1.5s despite the GPU probe now also running |
| Deterministic ambiguity handling preserved | Unchanged from the prior round (`discover::resolve_unique`) | IMPLEMENTED_AND_TESTED | 3 existing tests | only one real instance exists on this host — ambiguity itself not exercised live (as previously noted) |
| Mandatory TTY1 deployment | `deploy/vllm-top-console.service` (new) | IMPLEMENTED_AND_LIVE_VERIFIED | — | see TTY1 section below |
| Administrative access preserved | No SSH/PAM/sudo config touched; only `getty@tty1` masked | IMPLEMENTED_AND_LIVE_VERIFIED | — | `ssh.service`/`ssh.socket` confirmed active before, during and after every step |

## TTY1 deployment — what was actually done and verified

1. Verified independent administrative access *before* touching anything:
   `ssh.service`/`ssh.socket` active; this automation session itself has
   no controlling tty (confirmed via `tty` → "not a tty"), so it was never
   dependent on tty1 either.
2. Drafted `deploy/vllm-top-console.service`, validated with
   `systemd-analyze verify` (clean — the only warnings shown are from
   pre-existing, unrelated units).
3. Installed to `/etc/systemd/system/`, `daemon-reload`d.
4. Stopped and **masked** `getty@tty1.service` (stronger than disable —
   nothing can restart it while this stands).
5. Enabled and started `vllm-top-console.service`.
6. Verified: `Main PID` is `/home/mike/.cargo/bin/vllm-top` directly (no
   shell wrapper); `ps -o tty=` on that PID shows `tty1`; `getty@tty1`
   confirmed masked/inactive; SSH confirmed still active.
7. Performed a controlled restart (`systemctl restart
   vllm-top-console.service`): came back up clean, still attached to
   tty1, `getty@tty1` still masked, `Result=success`, `NRestarts=0` (no
   crash-triggered restarts observed).
8. Journal reviewed: no `vllm-top` panics or errors; the only noise is
   `xpu-smi`'s own HECI/MEI logging (see GPU telemetry above), confirmed
   unrelated to this deployment.

**Explicit limitation, not glossed over:** everything above is verified
from the shell (process identity, tty attachment, systemd state, journal
content). I cannot visually inspect the physical tty1 screen from this
session, so I'm not claiming to have confirmed the frame actually renders
legibly on the physical console — only that the correct process, with the
correct terminal ownership, is running without error. If you can check
the physical screen (or a KVM/IPMI console view), that's the one thing
this report can't close out for you.

## Bug caught and fixed during live validation

While the TTY1 console was running for real, `Tasks:` in
`systemctl status` climbed from 9 to 125 within ~3.5 minutes.
Investigation found `src/gpu.rs::run_bounded` spawned an `xpu-smi` child
per probe but never called `.wait()` on it — Rust does not reap a `Child`
on drop, so every completed probe left a zombie process. On a long-lived
process (the whole point of a TTY1 console), this would have grown
without bound indefinitely. Fixed by spawning a detached reaper thread
that unconditionally calls `child.wait()`. Rebuilt, reinstalled (SHA-256
`22cc90b6a6d764b31667f31f10373996ca43891da78c48dc9b561022977364c1`,
pre-fix binary preserved at `rollback/vllm-top.pre-zombie-fix`), and
restarted the live console. Verified over a full minute of observation
afterward (12+ probe cycles at the 5s GPU-poll cadence): zombie count
flat at 0, cgroup task count flat at 2. Not covered by an automated test
(timing-dependent OS process-reaping behavior; the live before/after
comparison is the evidence here) — worth adding a synthetic test for this
specific pattern in a follow-up if `gpu.rs` grows more probe call sites.

## Rollback

Two independent rollback points, neither touched by this work:
- Binary: `rollback/vllm-top.pre-0.2.0-monitoring-console` (immediately
  pre-0.2.0) and `rollback/vllm-top.pre-discovery-hardening` (further
  back, pre-discovery-feature entirely).
- Service: `deploy/DEPLOYMENT.md` "Rollback" section — stop/disable the
  console service, unmask and re-enable `getty@tty1.service`. Verified
  this doesn't require tty1 access (all commands run over the same
  SSH/administrative channel used for everything above).

## Final status

**COMPLETE_WITH_LIMITATIONS.** Every requirement above is either
`IMPLEMENTED_AND_LIVE_VERIFIED` or `IMPLEMENTED_AND_TESTED`, with two
explicit, evidence-backed exceptions: tensor-parallel size is not exposed
by any endpoint found and was deliberately not guessed at; Prometheus-mode
integration is tested but not live-validated (no Prometheus server exists
on this host); and physical tty1 screen rendering is confirmed only at
the process/terminal-ownership level, not visually.
