# vllm-top requirements audit — 2026-09-24

Read-only investigation. No source was modified, nothing was rebuilt or
reinstalled, and no version metadata or services were changed while
producing this document.

## 1. Running-process / deployment finding (do this first, per the request)

**There is no `vllm-top` process running anywhere on this host right now**,
on tty1 or elsewhere, and no login session is currently attached to any
terminal (`who` returns empty; `getty@tty1.service` shows only the bare
`agetty` login prompt, no shell or application beneath it).

Earlier in this same engagement (before any install/build work), a real,
long-running interactive `vllm-top` process *was* observed:

```
mike  3863  ... pts/1  Sl+  00:49  13:28  /home/mike/.cargo/bin/vllm-top
```

— started 00:49, 13m28s of accumulated CPU time, on `pts/1`. As of this
audit, PID 3863 no longer exists (`ps -p 3863` reports nothing); there is
no journal entry, crash log, or core dump explaining why. Whatever ended
it happened without leaving diagnostic evidence I can inspect.

This matters because of ordinary POSIX behavior: `cargo install` replaces
`~/.cargo/bin/vllm-top` by writing a new file and swapping it in — it does
**not** affect a process that already had the old file open. If PID 3863
was still running at the moment of installation, it would have kept
running the pre-discovery, pre-hardening binary in memory, completely
unaffected by the replacement on disk, and anyone looking at that
session's screen would have seen no changes at all, regardless of what
had just been installed. I can't confirm this was what the user was
looking at — I have no timestamp for when they observed "still v0.1"
relative to when PID 3863 exited — but it is a real, mechanically valid
explanation, and it's the kind of gap this investigation was asked to
surface rather than paper over.

**Executable identity, independent of the above:** the binary currently
at `~/.cargo/bin/vllm-top` (reached via the unchanged
`~/.local/bin/vllm-top` wrapper on `PATH`) is confirmed to be the one
installed at the end of the previous engagement
(sha256 `162efdd1b73a5f8f49157313bd6a022cce2a8a81a93f77deb622be291f0b6d53`),
and it does contain the discovery/hardening source (confirmed by grep for
`Confidence`, `resolve_unique`, `mod discover` in the built source tree).
A **freshly started** `vllm-top` today would run this code. Whether that
resolves the user's report depends on section 5 below — it does not,
fully, because of a separate, real defect found there.

## 2. Requirements recovery — evidence gap, stated explicitly

I searched every source I have access to for the broader requirements
listed in the request (persistent TTY1 console, a separate authenticated
admin terminal, cumulative-statistics semantics, GPU telemetry):

- This repository: `README.md`, all `src/*.rs`, `Cargo.toml`,
  `vllm-top.example.toml` — no mention of TTY1, an admin-terminal
  requirement, or GPU/VRAM/power telemetry anywhere. (`grep` hits on
  "GPU"/"cumulative" in the source are incidental — a comment about
  "multi-GPU server... RPC ports" I wrote this session, and the word
  "cumulative" used in histogram-interpolation math — not features.)
- My own persistent memory (`~/.claude/projects/-home-mike/memory/`):
  **empty**. No prior record of this project exists there.
- Other Claude Code sessions on this project: **none exist.** There is
  exactly one session transcript under this project
  (`021aa9b7-2429-4fcf-bf79-296e3e70c1ff.jsonl`), and it is this current
  conversation (same UUID as this session's own scratchpad path).
- Other files on this host that could plausibly contain this
  (`~/local-ai-host-tuning.md`, `~/vllm-tuning/METHODOLOGY.md`,
  `~/vllm-tuning/RESULTS.md`): real, detailed, and about *this* box, but
  about OS/CPU/systemd tuning and model/runtime benchmarking — none
  mention `vllm-top`'s TUI, TTY1, or an admin-terminal requirement.

**Finding:** the first and only place items like "persistent TTY1
console," "separate authenticated administrative terminal," and
"resetting cumulative statistics on restart" appear, in anything I can
inspect, is the pasted specification text earlier in *this same
conversation*, presented as "previously established." I found no
independent, earlier source establishing them. I can't prove they were
never discussed anywhere (e.g. verbally, or in a channel outside this
machine) — that's outside what I can verify — but within the evidence
available to me, there is no corroboration. I'm reporting this as an
explicit gap rather than treating the assertion as confirmed history, and
rather than assuming it's false.

## 3–4. Requirements traceability matrix

Classifications used: `IMPLEMENTED_AND_LIVE_VERIFIED`,
`IMPLEMENTED_AND_TESTED`, `IMPLEMENTED_NOT_VALIDATED`,
`PARTIALLY_IMPLEMENTED`, `NOT_IMPLEMENTED`, `BLOCKED`,
`REQUIREMENT_NOT_RECOVERABLE`.

| ID | Requirement | Source | Implementation | Status | Test evidence | Live evidence | Gap | Remediation |
|---|---|---|---|---|---|---|---|---|
| R1 | Persistent monitoring console on TTY1 | Asserted in-conversation only (§2) | None | REQUIREMENT_NOT_RECOVERABLE | — | `getty@tty1.service` is a bare `agetty` login prompt; no autologin, no ExecStart of `vllm-top`, confirmed via `systemctl status`/`cat` | No deployment mechanism exists to put `vllm-top` on tty1 at all | If genuinely wanted: an `agetty --autologin` + a shell profile or dedicated `getty@tty1.service` override that execs `vllm-top`. Needs explicit user confirmation before touching a login service. |
| R2 | Separate authenticated admin terminal remains available | Asserted in-conversation only (§2) | N/A — property of not touching sshd/other ttys | REQUIREMENT_NOT_RECOVERABLE (as a stated requirement) | — | SSH/other ttys untouched by this or the prior engagement | None found | None needed unless R1 is implemented, at which point this becomes the reason tty1 must not be the only access path |
| R3/R4 | Statistics scoped to monitor lifetime; reset on restart | Asserted in-conversation only (§2) | `app.rs` `App::new`/`Runtime` set `started: Instant::now()`; `prev` rate-derivation baseline starts `None` each run | PARTIALLY_IMPLEMENTED | `metrics::tests::counter_reset_yields_zero_rate` covers counter-reset math, not process-restart semantics directly | Confirmed by code read this session | Uptime/poll-count/rates reset on `vllm-top` restart, **but** the absolute totals shown (prompt/output tokens, `done` counts) are vLLM's own server-side Prometheus counters, read fresh each poll — they reflect the vLLM *server's* lifetime, not `vllm-top`'s, and `vllm-top` has no mechanism to rebase them | If "scoped to monitor lifetime" must also apply to absolute totals, `vllm-top` would need to snapshot first-poll values and display deltas from them — not built, and arguably undesirable (loses "total since server start" context) |
| R5 | No persistent metrics database | Asserted in-conversation only (§2) | Absence — no DB crate in `Cargo.toml`, no file/db writes anywhere in `src/` | IMPLEMENTED_AND_LIVE_VERIFIED | Full source read, this session and prior | Confirmed | None | — |
| R6 | Direct vLLM `/metrics` scraping | Pre-existing, README | `src/source.rs::DirectSource` | IMPLEMENTED_AND_LIVE_VERIFIED | `promparse`/`metrics` unit tests | Repeatedly verified against the real `vllm.service` this session | None | — |
| R7 | Prometheus-mode integration | Pre-existing, README | `src/source.rs::PrometheusSource` | IMPLEMENTED_NOT_VALIDATED | No dedicated unit test for `PrometheusSource`'s request/response handling (only shared `promparse` parsing is tested) | Not exercised against a real Prometheus server this session | Test and live-validation gap, not a code gap | Add a `PrometheusSource`-specific test (mock JSON response); validate against a real Prometheus instance if one becomes available |
| R8 | Multiple simultaneous target monitoring | Pre-existing, README | `config::resolve` → `Vec<InstanceDef>`, `app.rs` tabs/aggregate | IMPLEMENTED_AND_TESTED | Exercised via `--demo`'s 3 synthetic instances | Not live-tested with 2+ *real* vLLM servers this session (only one exists on this host) | "Multiple real instances" specifically unverified live | None required unless a second real instance becomes available to test against |
| R9 | TOML configuration | Pre-existing, README | `src/config.rs::load_file`/`FileInstance` | IMPLEMENTED_AND_LIVE_VERIFIED | — | Verified this session with a real TOML file against the real server | None | — |
| R10 | Automatic local vLLM discovery | Requested this engagement | `src/discover.rs` | IMPLEMENTED_AND_LIVE_VERIFIED | 30 unit tests | Verified: finds `vllm.service`, resolves port 8000 via socket table, ~1.5s bounded | None outstanding | — |
| R11 | Host/port/API-capability detection | Requested this engagement | `src/discover.rs` (`/proc/net/tcp{,6}`, `/health`, `/v1/models`) | IMPLEMENTED_AND_LIVE_VERIFIED | Unit tests for parsing/classification | Verified against real endpoint | None | — |
| R12 | Authentication handling | Requested this engagement | `src/discover.rs`, `src/source.rs` (`bearer_auth`), `src/config.rs` | IMPLEMENTED_AND_LIVE_VERIFIED | Unit tests for `classify_auth` | Verified: accepted / rejected / no-credential all exercised live | None | — |
| R13a | Inference performance telemetry | Pre-existing, README | `src/metrics.rs::Snapshot` (throughput, KV-cache, latency, requests) | IMPLEMENTED_AND_LIVE_VERIFIED | `metrics::tests::*` | Verified against real server | None | — |
| R13b | GPU hardware telemetry (VRAM/power/utilization) | Asserted in-conversation only, framed there as a *known limitation to work around*, not a build target | None | NOT_IMPLEMENTED | — | Confirmed absent: no `gpu`/`vram`/`power`/`utilization` field anywhere in `Snapshot` or any struct | vLLM's own `/metrics` doesn't expose GPU hardware counters; this would need a separate source (e.g. `xpu-smi`, present on this host, or an exporter) merged in as a new metric source | Out of scope for `vllm-top` as built; would be a genuinely new feature (new `MetricsSource` impl, new UI panel), not a fix |
| R14 | Terminal interface changes/presentation | Requested this engagement | `src/ui/mod.rs::draw_stats` (appended text on the "source" line), `src/main.rs::once` (extra printed line) | PARTIALLY_IMPLEMENTED | — | Verified: the discovery/auth/confidence text renders in `--once` output; visually confirmed in code for the interactive stats panel (not captured live — see §4 note) | The change is a small appended clause on one existing line, only in the single-instance view, easy to miss; no new panel/screen was added | If more visible presentation is wanted (e.g. its own line, or shown in aggregate view too), that's a UI design decision, not implemented yet |
| R15 | Version string reflects actual build | Implicit / found during this audit | `src/cli.rs` (`clap`'s `version` flag, dynamic, reads `Cargo.toml`) **vs.** `src/ui/mod.rs:221`, a **hardcoded literal** `" vllm-top 0.1 "` in the TUI footer | NOT_IMPLEMENTED (defect) | — | `vllm-top --version` → `vllm-top 0.1.0` (correct, dynamic); the interactive TUI footer will print "vllm-top 0.1" **regardless of any future change**, because it is not derived from `CARGO_PKG_VERSION` or anything else at all | This is a real, verifiable, always-true bug: the footer can never show anything but "0.1" as written, independent of features shipped. Separately, `Cargo.toml`'s `version = "0.1.0"` was never bumped despite two rounds of real feature work | Fix `src/ui/mod.rs:221` to use `env!("CARGO_PKG_VERSION")` (already available via the `version` crate feature used in `cli.rs`); consider bumping `Cargo.toml` to `0.2.0` to reflect the discovery feature. **Not done — investigation only, per instructions.** |
| R16 | Socket-attribution confidence (Verified vs. UidAssociation) | Requested previous round | `src/discover.rs::attribute_sockets`, `Confidence` | IMPLEMENTED_AND_TESTED overall; `Verified` branch specifically is IMPLEMENTED_NOT_VALIDATED | 2 dedicated unit tests (`attribution_prefers_verified_when_fds_known`, `attribution_falls_back_to_uid_when_fds_unreadable`) | `UidAssociation` branch is live-verified (it's what fires on this box, since the vLLM process runs as a different uid); `Verified` branch has never been exercised against a real same-uid process | Structural: this box's real deployment is cross-uid by design, so `Verified` can't be live-exercised here | None — this is an accurate limitation of the environment, not a code gap |

## 5. Deployment / version identity — direct answers

- **Does TTY1 launch the same executable validated via `--once`?** N/A —
  nothing launches anything on tty1; it's a bare login prompt (§1).
- **Do the interactive TUI and `--once` share the same discovery/metrics
  path?** Yes, verified by code structure: `main()` calls
  `config::resolve(&cli)` exactly once, and both the `--once` branch and
  the interactive `App::new` branch consume the same resulting
  `Vec<InstanceDef>` — there is no second, divergent code path.
- **Hardcoded version strings?** Yes — found one, `src/ui/mod.rs:221`
  (R15 above). `clap`'s `--version` output is *not* hardcoded (reads
  `Cargo.toml` via the `version` attribute).
- **Does the TUI display the Cargo package version?** No — it displays an
  unrelated hardcoded literal that happens to currently read the same
  ("0.1") coincidentally, since `Cargo.toml` was also never bumped past
  0.1.0.

## 6. Actual cause — verified vs. hypothesis

**Verified, not a hypothesis:** the TUI footer's version string is a
hardcoded literal (`src/ui/mod.rs:221`) that will print "vllm-top 0.1" no
matter what code is installed, today or after any future change, until
that line itself is edited. This alone fully and mechanically explains
"the application still displays v0.1," independent of timing, process
liveness, or which binary is actually running.

**Verified, contributing:** the actual interface changes made this
engagement are small — one appended clause on one existing stats line,
visible only in single-instance view — and easy to read past even when
running the correct, updated binary.

**Verified, contributing:** two broader requirements the reconciliation
request describes as "previously requested" (GPU/VRAM/power telemetry;
a TTY1-resident console with a separate admin terminal) were never
implemented and have no recoverable specification trail anywhere I can
inspect (§2). If the user's expectation includes either of these, that
expectation was never met because the work was never started — not
because it broke.

**Plausible, not verified:** an already-running `vllm-top` process
(PID 3863, observed earlier this engagement, since exited without a
diagnostic trace) may have been the specific session the user was
looking at, which — if still running at the time — would have kept
executing the pre-install binary regardless of what was installed
underneath it. I cannot confirm or rule this out; I'm flagging it as a
real mechanism, not a conclusion.

**Mapping to the seven listed candidate causes:** (1) partially, only as
a historical/unconfirmed factor, not the current state; (2) no — the
installed and resolved executable are confirmed identical and current;
(3) no specific mismatch found beyond R1/R2 never having existed; (4) no;
(5) yes, partially (R14 — implemented but easy to miss); (6) yes (R13b,
R1/R2, R15); so overall: **a combination**, with the hardcoded version
string (R15) as the single most direct, fully-verified explanation.

## 7. Status

Per the instructions for this phase: not reporting COMPLETE. This is an
investigation and audit; the remediation items above (R15's hardcoded
string being the most consequential) have **not** been applied.
