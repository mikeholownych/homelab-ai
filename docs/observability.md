# Observability Architecture

Two layers with different jobs:

## 1. Operational failure monitoring (implemented)

- `aihost-alert@.service`: OnFailure hook on every lifecycle timer; local log +
  optional argv-only forwarding command.
- Evidence durability: append-only rsync mirror behind a feature flag.
- Drift/validation status artifacts consumed by the alert path.

## 2. Continuous performance/optimization layer (designed; partially implemented)

Target architecture agreed for this host:

| Component | Role | Status |
|---|---|---|
| Grafana Alloy | agent: scrape node + vLLM `/metrics`, GPU textfile dir, remote-write to VictoriaMetrics, forward logs to Loki | **role provided, hash-pinned** (`v1.19.2`) - install gated at commissioning |
| VictoriaMetrics single-node | TSDB store + recording rules for throughput/watt, TTFT trends per tuning profile | **role provided, hash-pinned** (`v1.150.0`) - install gated at commissioning |
| vmalert | evaluates recording rules, writes derived series back to VictoriaMetrics | **role provided** (from the pinned `vmutils` tarball) |
| Grafana | dashboards over VM datasources | **role provided, hash-pinned** (`13.2.0`) - install gated at commissioning |
| Loki | local log aggregation fed by Alloy | **role provided, hash-pinned** (`v3.7.6`) - install gated at commissioning |
| xpumd / Level Zero telemetry | GPU utilisation, VRAM, clocks, thermals into textfile dir | **pending hardware** |
| vLLM metrics endpoint | already exposed by the service; scraped by Alloy once deployed | available when service runs |
| Prometheus textfile collector dir | offline-provable bridge today | **implemented below** |

### Implemented today: textfile metrics bridge

`monitoring_metrics_textfile_enabled` writes a node_exporter-compatible
textfile (`/var/lib/local-ai/metrics/gpu.prom`) every minute via systemd timer,
sampling the same hwmon sources the benchmark harness uses plus reconciliation
status. This gives any future Alloy deployment an immediate scrape target and
gives cron-level history even before the full stack lands.

GPU sampling is **per device**: both B65 cards contribute their own
labeled series (`aihost_gpu_temperature_celsius{device="hwmon1/xe"}`) plus an
unlabeled cross-device peak. The thermal gate in benchmark fixtures reads the
peak across both devices, so neither card can hide a hotspot behind the other's
nominal temperature.

The metrics writer also runs a debounced **GPU thermal severity guard**
(`aihost_gpu_thermal_severity` 0/1/2 from ok/warning/critical). Thresholds
default to `monitoring_gpu_temp_warn_threshold_c: 75` and
`monitoring_gpu_temp_crit_threshold_c: 85` — deliberately below the benchmark
abort guardrail (`benchmarking_abort_temperature_c: 90`) so an operator is
alerted before a workload would be killed. A critical transition is written to
the alert log and forwarded through `AIHOST_ALERT_COMMAND` on both GPU cards'
behalf with context `state=critical temperature_c=<peak>`; recovery to ok after
critical logs a `state=recovered` line.

**Scheduled drift alerting**: `aihost-reconcile.timer` runs the snapshot runner
for `site.yml --validate-after-site` and then a second snapshot run for
`drift-check.yml`, so every scheduled reconciliation classifies drift.
`playbooks/drift-check.yml` raises an operator alert through the local alert
hook when classification is `blocking_drift` or `unknown_drift`, passing the
classification as alert context. Drift is classified fail-closed: a missing or
`NOT_TESTED` validation outcome (explicit `unknown_drift`) is never reported as
`no_drift`.

Scripts are installed via `copy` and are Jinja-free: runtime values (paths,
thresholds) are read from `/etc/local-ai/monitoring.env`, a role-templated
config file, so no literal `{{ }}` markers can leak into installed artifacts.

### Deployed as the `observability` role

The continuous layer lives in `roles/observability` (included from `site.yml`
behind `features.observability`, default off). It fetches every upstream
artifact via `get_url` with an exact `sha256` pin and never runs unverifiable
install scripts; all binaries, configs and systemd units are laid down by the
role. Services bind loopback only.

Install is **fail-closed and commissioning-gated**, mirroring the Intel GPU
role: `observability_stack_status` defaults to `pre_verification_fail_closed`
and `observability_install_enabled` to `false`. Nothing downloads or starts
until the commissioning run on physical hardware flips both to
`commissioned` / `true`. The Grafana admin password is read from Vault
(`secret/local-ai/observability/grafana-admin`) into a mode-0600 env file; no
credential is committed. The vLLM dependence in the throughput recording rules
stays disabled (`observability_vllm_recording_rules_enabled: false`) until the
live `/metrics` series names are validated against the running service and that
check is recorded in `observability_verification_checklist`; host-level series
(textfile GPU thermals/severity) are always synthesized.

**Verification checklist (run at commissioning, before enabling install):**
1. Physical dual-B65 host is present with runtime account and filesystems.
2. Grafana admin secret exists in Vault at `secret/local-ai/observability/grafana-admin`.
3. vLLM `/metrics` endpoint responds on the configured port; validate recording-rule expressions.
4. VM `/api/v1/status/active_tsdb` returns after first scrape cycle; Alloy `/metrics` shows textfile series.
5. Recording rule output `aihost:gpu_temperature_celsius:peak` present in VM.

Install all five components together (Alloy, VictoriaMetrics, vmalert, Loki,
Grafana) or prune individual ones via `observability_*_enabled` flags before
launch. In check mode the role is fully inert: it renders every config/unit
template and records `observability_validation_status: NOT_TESTED`, but never
downloads, extracts, verifies, or starts services (see
`tests/integration/observability_gate_check.yml`, wired into `make check`), so
a CI/controller check run never touches the network.

### Why the full stack is not installed yet

Physical B65 hardware has not arrived. Per repository policy, an install that
cannot be converged on the real target is never claimed as verified: the role
is pinned, committed and linted, but its download/start steps only execute once
the commissioning checklist above has passed on the host.
