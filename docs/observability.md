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
| Grafana Alloy | agent: scrape node + vLLM `/metrics`, GPU textfile dir, remote-write to VictoriaMetrics, forward logs to Loki | **not installed** - requires network-resolved pinned artifacts at commissioning |
| VictoriaMetrics single-node | TSDB store + recording rules for throughput/watt, TTFT trends per tuning profile | **not installed** |
| Grafana | dashboards over VM datasources | **not installed** |
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

### Why the full stack is not in this commit

Repository policy forbids unverifiable pins and curl-install scripts. Alloy /
VictoriaMetrics / Grafana versions must be resolved against current upstream
releases and hash-pinned exactly like every other component - that is a
commissioning-time Git commit, not a guess committed blind.
