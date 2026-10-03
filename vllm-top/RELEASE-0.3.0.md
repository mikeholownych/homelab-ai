# vllm-top 0.3.0 — TTY1 layout/usability redesign report

## 1. Final status

**COMPLETE_WITH_LIMITATIONS.** All implemented changes are live-verified
against the real deployment; the one thing this report cannot close out
is a direct visual inspection of the physical tty1 screen from this
session (see §10).

## 2. Version / installed executable

| | |
|---|---|
| Version | `0.3.0` (was `0.2.0`) — a minor bump per the one established convention so far (0.1.0→0.2.0 was used for feature work; this round adds new panels/telemetry fields, not just fixes) |
| Installed SHA-256 | `8157ca2f25d06de165c607c80c83df538b9377f789a8859d899748f78e5a2691` |
| Previous installed SHA-256 | `eef1da4c20136430548ec1dc45570a9a217b82caa3648ff6c792efdd6f07fe5f` (`rollback/vllm-top.pre-0.3.0`) |
| `--version` / TUI footer / HTTP User-Agent | confirmed consistent (all three read `env!("CARGO_PKG_VERSION")`) |

## 3. Source files changed

`src/ui/mod.rs` (layout engine + all panel drawing — the bulk of this
round), `src/gpu.rs` (static device info: name/total memory/PCIe link),
`src/app.rs` (wiring for `gpu_info`), `Cargo.toml`, plus
`README.md`/`CHANGELOG.md`. No changes to `discover.rs`, `metrics.rs`
core logic, `source.rs`, or `config.rs`.

## 4. Layout and presentation changes

- Replaced fixed/`Min()`-based row heights with `compute_layout`, computed
  from the actual terminal size every frame. Directly fixes the reported
  defect: the latency panel no longer balloons to ~37 near-empty rows on
  a large terminal (verified: capped ≤22 rows at the real TTY1 size,
  regression-tested).
- Split the crowded "stats" panel into three dedicated panels: **service**
  (endpoint/discovery/confidence/auth/vLLM version/model), **gpu**, and
  **session** (monitor-lifetime totals) — each independently legible.
- New **overview** KPI strip (wide terminals, ≥100 cols).
- Header now shows **MON** (monitor's own health) and **SVC** (monitored
  service's health) as two distinct, separately colored indicators —
  directly implements "a healthy monitoring application reporting an
  unavailable inference service must not appear equivalent to a healthy
  inference service."
- Minimum terminal size held at 90×35 (unchanged) — verified the new
  layout still renders correctly there, not just at the large end.

## 5. Metrics and telemetry presentation

GPU panel: device name, memory used/total + utilization (preferring
`xpu-smi`'s own reported percentage over a derived one), power, PCIe
generation/link width when reported. Static identity is fetched once at
startup (`gpu::discover_static`); live counters stay on the existing 5s
cadence. One device's failed probe never hides another's (tested).

**Newly verified, not previously confirmed:** `xpu-smi`'s detailed
per-device query reports `pcie_generation`/`pcie_max_link_width` as the
literal string `"N/A"` on this hardware — direct evidence for the PCIe
link negotiation limitation mentioned in earlier requirements text, which
I had not independently confirmed before this round.

## 6. Automated test results

`cargo test`: **56/56 passing** (was 44 at the start of this round — 12
new UI rendering tests). `cargo clippy --all-targets`: clean.

Covered from the requested list: actual TTY1 dimensions (240×67), 80×24
too-small, zero-size, standard/intermediate sizes (90×35, 110×40, 140×42,
200×60), a resize sequence, long model identifiers (panel-corruption
check), multiple GPUs with one probe "failing", missing GPU telemetry,
unavailable inference service (down vs. MON/SVC distinction), auth
failure (distinct from metrics health), multi-instance aggregate view,
empty graph history.

**Not covered**, explicitly: large cumulative counters and zero-valued
measurements as dedicated new tests (existing `util::tests::si_suffixes`
covers the formatting half of this already); genuine Unicode-width edge
cases beyond what real model names already exercise; a snapshot/golden
image test (see §7 — deterministic buffer captures were used instead).

**Bugs this test suite caught in its own new code, before install:**
1. Discovery text truncating mid-word, potentially losing the confidence
   label, when three panels replaced two wider ones.
2. A GPU device name + PCI address line hard-clipping instead of
   truncating cleanly.
3. The test suite's own panel-locating helper always finding the first
   bordered panel on a header row shared by three panels — meaning an
   earlier version of it silently checked the wrong panel's content.

All three fixed and re-verified before this binary was built.

## 7. Visual regression evidence

Deterministic `ratatui::TestBackend` buffer captures (`render_text`), not
screenshots — this sandbox has no way to produce an actual image, stated
here explicitly rather than implied. Representative states captured via
the test suite: healthy single-instance, healthy aggregate, service down,
auth failure, GPU telemetry partially available (one device missing),
narrow (90×35) and large (240×67) terminals, long model identifier.
Compared against the *textual description* of the original layout's
problems (no photograph was ever actually attached to this conversation,
despite the request text referring to one — flagged plainly rather than
fabricating an analysis of an image I never received).

## 8. Live inference-service validation

Re-ran the full regression battery against the real `vllm.service` after
every rebuild this round (zero-flag discovery, no-credential, explicit
URL, TOML config, `--demo`) — all still correct. `vllm.service` was never
restarted (`ActiveEnterTimestamp` unchanged at `2026-09-24 14:46:54 UTC`
throughout this entire round). GPU configuration untouched.

## 9. TTY1 deployment status

`vllm-top-console.service` active, enabled, `Main PID` is
`/home/mike/.cargo/bin/vllm-top` directly, attached to `/dev/tty1`
(`ps -o tty=` confirms). `getty@tty1.service` remains masked/inactive.
Deployment architecture unchanged from the prior round — only the
executable was replaced and the service restarted, exactly as scoped.

## 10. Physical-console validation status

**Not performed from this session** — I have no mechanism to view the
physical screen or a KVM/IPMI console from here. Everything above (v9,
stability) is verified from the shell: correct process, correct terminal
ownership, correct rendered output via deterministic buffer capture — not
a claim that the physical display looks correct. If you can look at the
physical screen, that closes the one gap this report can't.

## 11. Resource and stability observations

Zombie-reaping fix from the previous round (`gpu.rs::run_bounded`)
preserved and re-verified: zombie count flat at 1 (a single pre-existing,
unrelated `[local-ai-vllm-r] <defunct>` from the `vllm.service` podman
tree) across a 60-second observation window spanning multiple 5s GPU-poll
cycles after this round's redeploy. Console `Tasks:` flat at 2, memory
flat (~19MB after restart). No restart loop (`NRestarts=0`, `Result=success`).

## 12. Rollback

Binary checkpoints in `rollback/`: `vllm-top.pre-0.3.0` (immediately
prior), plus the two from earlier rounds
(`vllm-top.pre-0.2.0-monitoring-console`,
`vllm-top.pre-discovery-hardening`, `vllm-top.pre-zombie-fix`). Service
rollback procedure unchanged, documented in `deploy/DEPLOYMENT.md`,
requires no tty1 access.

## 13. Remaining defects and limitations

- No photograph was ever attached to this conversation despite the
  request referring to one — I worked from the textual problem
  description only, and am flagging that gap rather than fabricating a
  visual analysis.
- Physical-console rendering is unverified from this session (§10).
- The instances table still uses percentage-based column widths that
  stretch with extra terminal width without adding information (visible
  padding in wide cells at 240 cols) — a genuine, minor, lower-priority
  residual of the same "excessive empty space" class of issue, not
  addressed this round given the scope already covered.
- The overview KPI strip's line isn't independently width-budgeted per
  tile — at exactly the 100-column threshold where it first appears, its
  trailing tile(s) (least important — total GPU power) could clip at the
  panel's right edge before more important tiles do; not observed in
  practice at the tested sizes, not covered by a dedicated test.
- A snapshot/golden-image regression mechanism wasn't set up — assertions
  on rendered text are used instead, per the instructions' own allowance
  for deterministic buffer captures when screenshot tooling isn't
  available.
