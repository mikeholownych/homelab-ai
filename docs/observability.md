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
| Grafana Image Renderer | standalone headless Chrome image rendering service on port 8081 for panel PNG snapshots | **role provided, hash-pinned** (`4.1.5`) - install gated at commissioning |
| Loki | local log aggregation fed by Alloy | **role provided, hash-pinned** (`v3.7.6`) - install gated at commissioning |
| Tempo | distributed tracing backend for OTLP spans and Grafana Traces Drilldown | **role provided, hash-pinned** (`v3.1.0`) - install gated at commissioning |
| xpumd / Level Zero telemetry | GPU utilisation, VRAM, clocks, thermals into textfile dir | **pending hardware** |
| vLLM metrics endpoint | already exposed by the service; scraped by Alloy once deployed | available when service runs |
| Prometheus textfile collector dir | offline-provable bridge today | **implemented below** |

### Implemented today: textfile metrics bridge

`monitoring_metrics_textfile_enabled` writes a node_exporter-compatible
textfile (`/var/lib/local-ai/metrics/gpu.prom`) every minute via systemd timer,
sampling the same hwmon sources the benchmark harness uses plus reconciliation
status. This gives any future Alloy deployment an immediate scrape target and
gives cron-level history even before the full stack lands.

GPU sampling is **per device and per sensor**: every temperature sensor on each B65 card is its own series,
`aihost_gpu_temperature_celsius{gpu="0",bdf="0000:51:00.0",sensor="pkg"}`. `gpu` is the ordinal by PCI address
(it matches the workers' `gpu_assignment`) and `bdf` is the stable PCI address; the unstable `hwmonN` name is never
used as a label. `aihost_gpu_temperature_max_celsius{gpu,bdf}` is the hottest sensor on each card, and
`aihost_gpu_temperature_limit_celsius{gpu,bdf,sensor}` is the critical limit the kernel reports for that sensor
(headroom = limit - temperature). The same file also carries cumulative energy
(`aihost_gpu_energy_joules_total`), graphics-tile idle residency (`aihost_gpu_gt_idle_residency_seconds_total`),
power cap, frequency, fan speed and `aihost_metrics_last_success_timestamp_seconds`. The benchmark harness reads
the hwmon files directly and takes the hottest sensor across both devices, so neither card can hide a hotspot
behind the other's nominal temperature.

The metrics writer also runs a debounced **GPU thermal severity guard**
(`aihost_gpu_thermal_severity` 0/1/2 from ok/warning/critical). Thresholds
default to `monitoring_gpu_temp_warn_threshold_c: 75` and
`monitoring_gpu_temp_crit_threshold_c: 85` — deliberately below the benchmark
abort guardrail (`benchmarking_abort_temperature_c: 90`) so an operator is
alerted before a workload would be killed. A sensor that publishes its own kernel limit is judged against
`min(configured threshold, limit - margin)`, so a kernel limit can only tighten alerting (margins 25/15 C, role
variables `monitoring_gpu_temp_warn_margin_c` / `_crit_margin_c`). Every transition is written to the alert log,
naming the sensor that set the severity (`sensor=gpu1/vram`). A critical transition is also forwarded through
`AIHOST_ALERT_COMMAND` with context `state=critical temperature_c=<peak>`; recovery to ok after
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

Install all components together (Alloy, VictoriaMetrics, vmalert, Loki, Tempo,
Grafana, Grafana Image Renderer) or prune individual ones via `observability_*_enabled` flags before
launch. In check mode the role is fully inert: it renders every config/unit
template and records `observability_validation_status: NOT_TESTED`, but never
downloads, extracts, verifies, or starts services (see
`tests/integration/observability_gate_check.yml`, wired into `make check`), so
a CI/controller check run never touches the network.

### Distributed Tracing & Service Graph Correlation

Grafana Tempo operates as the trace backend with the embedded `metrics_generator` processor enabled:
- **OTLP Ingestion:** Receivers listen on gRPC (`:4317`) and HTTP (`:4318`) for trace spans.
- **Log Correlation:** The Loki datasource provisions `derivedFields` matching `(?:traceID|trace_id)=(\w+)` with a direct link (`urlDisplayLabel: "View Trace"`) to Tempo (`uid: tempo`), enabling 1-click drilldowns from log entries to span traces.
- **Service Graphs & Span Metrics:** Tempo's metrics-generator processes span relationships (`nexus-client` -> `orchestrator-gateway` -> `b0-live-llama-worker1`) and writes `traces_service_graph_request_total` and `traces_spanmetrics_*` series directly into VictoriaMetrics via Prometheus remote-write (`http://127.0.0.1:8428/api/v1/write`), populating Grafana's Service Map and Node Graph.

**Verification Disposition & Scope Boundary:**
Backend telemetry pipeline readiness (OTLP span ingestion, Loki log ingestion with derived field correlation, Tempo trace retrieval via datasource proxy, and VictoriaMetrics service graph metric generation) is proven using live inference coupled with a constructed telemetry demonstration. Native in-process instrumentation (automatic trace context propagation across the client, gateway, and worker processes) and end-user browser click-through remain unproven.
