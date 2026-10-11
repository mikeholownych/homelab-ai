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

## 3. Operational Dashboards Suite

The operational observability stack provisions four dedicated, inter-linked Grafana dashboards organized into high-level overview and focused drilldowns:

| Dashboard Name | UID | Usable URL | Scope & Focus |
|---|---|---|---|
| **aihost Appliance & GPU Telemetry** | `aihost-appliance-telemetry` | `/d/aihost-appliance-telemetry/aihost-appliance-and-gpu-telemetry` | High-level appliance overview, worker/gateway availability, real-time KPIs, active workload, GPU thermals/power, single-thread CPU saturation, telemetry freshness, active alerts, and Loki logs. |
| **AIHost - inference** | `aihost-inference` | `/d/aihost-inference/aihost-inference` | Deep inference performance drilldown: prompt evaluation & decode speeds, generated tokens/s, prefix-cache hit ratio, p50/p95 duration, queue latency, outcome classification, KV cache occupancy, routing decisions (`engineering/lead-reasoning` at 8192 vs general routes), dispatches, authority validations, and release lifecycle. |
| **AIHost - host and GPU** | `aihost-host` | `/d/aihost-host/aihost-host-and-gpu` | Deep hardware & system drilldown: dual Intel Arc B65 GPU frequencies, power vs caps, energy per token, thermals vs kernel limits, throttle triggers, PCIe link width/speed, per-core CPU decode saturation, memory & swap, Linux PSI pressure stalls, disk throughput/IOPS, network bandwidth/errors, and model page-cache residency. |
| **Observability Stack Infrastructure Health** | `observability-stack-health` | `/d/observability-stack-health/observability-stack-infrastructure-health` | Observability backend health: Alloy target scrapes & remote-write, VictoriaMetrics ingestion & storage, Loki logs ingestion & WAL, Tempo trace ingestion & service graphs (with fixed query), vmalert iteration/errors, active firing alerts, and scope boundary notices. |

All dashboards include top-level cross-navigation links enabling immediate drilldown and return.

### Telemetry Pipeline & Collection Paths

1. **Host & GPU Hardware Telemetry:** Collected every 60 seconds by `roles/monitoring/files/write-textfile-metrics.sh` (triggered by `aihost-metrics.timer`).
   - Reads hwmon per-sensor temperatures (`pkg`, `vram`, `pcie`, `mctrl`), limits, energy counters, and RC6 idle residency.
   - Reads GPU tile throttling status (`aihost_gpu_throttle_status`, thermal, power) from `/sys/bus/pci/devices/$bdf/tile0/gt0/freq0/throttle/`.
   - Reads PCIe link width and speed (`aihost_gpu_pcie_link_width`, `max_link_width`, `link_speed_gts`) from sysfs.
   - Evaluates thermal severity guards (0=OK, 1=WARN, 2=CRIT).
2. **Gateway Metrics Loopback Bridge:** The orchestrator gateway listens on `127.0.0.1:8010/metrics` in `local` mode.
   - `write-textfile-metrics.sh` polls `http://127.0.0.1:8010/metrics` and writes `/var/lib/local-ai/metrics/gateway.prom` atomically via tempfile rename.
   - Bridging preserves gateway security (no remote network exposure) while exposing worker health, routing decisions, dispatches, request durations, and authority validations to `node_exporter`.
3. **Model Weights Page-Cache Residency:** Calculated via `fincore` on mapped GGUF model files:
   - `aihost_llama_model_file_cached_bytes` / `aihost_llama_model_file_size_bytes` (`aihost:llama_model_file_cache_residency:ratio`).
   - Major page fault rates from worker procfs stat (`aihost:llama_worker_major_faults:rate5m`).
4. **Alloy Ingestion & TSDB Storage:**
   - Grafana Alloy scrapes `10.0.8.5:9100` (`node_exporter` + textfiles) and forwards to VictoriaMetrics at `http://127.0.0.1:8428`.
   - `vmalert` evaluates recording rules every 15s and writes derived series back to VictoriaMetrics.

### Operational Coverage Matrix

| Area | Operational Question | Telemetry Metric(s) | Dashboards & Panels | Verification Status |
|---|---|---|---|---|
| **1. Appliance Overview** | Worker & gateway operational availability | `node_systemd_unit_state`, `aihost_worker_health_status` | Appliance Overview: Panels 4-6; Inference: Panel 2 | Verified live (`worker1`, `worker2`, `gateway` active; health status = 1). |
| | Active workload & in-flight requests | `aihost_http_requests_in_flight`, `aihost_engine_requests_running` | Appliance Overview: Panel 21; Inference: Panel 14 | Verified live (0 in idle; increments during traffic). |
| | Request & token throughput | `aihost_inference_requests_total`, `aihost_engine_generation_tokens_total` | Appliance Overview: Panels 22-23; Inference: Panels 3, 9 | Verified live. |
| | Latency p95 / queue latency | `aihost:inference_duration_seconds:p95_5m`, `aihost_scheduler_queue_wait_seconds_*` | Appliance Overview: Panel 24; Inference: Panels 11-12 | Verified live. |
| | GPU peak temps & power draw | `aihost_gpu_temperature_celsius`, `aihost_gpu_energy_joules_total` | Appliance Overview: Panels 1-3, 9-11 | Verified live (GPU 0 & 1 sensors active). |
| | Telemetry freshness | `time() - aihost_metrics_last_success_timestamp_seconds` | Appliance Overview: Panel 20; Host: Panel 5 | Verified live (<60s freshness). |
| | Actionable alerts list | `ALERTS{alertstate="firing"}`, `alertlist` | Appliance Overview: Panels 8, 18 | Verified live. |
| **2. GPU Health & Capacity** | Utilization (awake share) | `aihost:gpu_utilization_ratio:rate5m` | Host & GPU: Panel 8; Appliance: Panel 12 | Verified live (1 - RC6 idle residency). |
| | Memory allocation | `aihost_llama_model_file_cached_bytes`, `aihost_llama_worker_resident_file_bytes` | Host & GPU: Panel 17; Appliance: Panel 14 | **Known Limitation:** Kernel `xe` driver does not support driver-level VRAM allocation without xpumd. Memory is authoritatively tracked via mapped page cache and RSS. |
| | Power, energy, and caps | `aihost:gpu_power_watts:rate5m`, `aihost_gpu_power_cap_watts`, `aihost:joules_per_generated_token_incl_idle:rate15m` | Host & GPU: Panels 9-10; Appliance: Panel 3 | Verified live. |
| | Per-sensor temps & limits | `aihost_gpu_temperature_celsius`, `aihost_gpu_temperature_limit_celsius`, `headroom` | Host & GPU: Panels 3, 11; Appliance: Panels 1-2, 10 | Verified live across pkg, vram, pcie, mctrl. |
| | Hardware throttling | `aihost_gpu_throttle_status`, `throttle_reason_thermal`, `throttle_reason_power` | Host & GPU: Panels 7, 13; Appliance: Panel 25 | Verified live from sysfs tile registers. |
| | PCIe link state | `aihost_gpu_pcie_link_width`, `max_link_width`, `link_speed_gts` | Host & GPU: Panel 14 | Verified live (x16 width, 16 GT/s link). |
| **3. Host Health** | CPU per-core decode saturation | `aihost:cpu_core_busy_ratio:rate5m`, `aihost:cpu_busiest_core_ratio:rate5m` | Host & GPU: Panels 4, 15; Appliance: Panels 7, 16 | Verified live (identifies single-thread decode bottleneck). |
| | Memory & swap allocation | `node_memory_MemAvailable_bytes`, `node_memory_Swap*` | Host & GPU: Panel 16; Appliance: Panels 17, 26 | Verified live. |
| | Linux PSI pressure stalls | `node_pressure_cpu_*`, `node_pressure_memory_*`, `node_pressure_io_*` | Host & GPU: Panel 17 | Verified live across CPU, memory, and I/O. |
| | Disk throughput & I/O busy % | `node_disk_read_bytes_total`, `node_disk_written_bytes_total`, `node_disk_io_time_*` | Host & GPU: Panels 19-20 | Verified live across block devices. |
| | Model page cache & faults | `aihost:llama_model_file_cache_residency:ratio`, `aihost:llama_worker_major_faults:rate5m` | Host & GPU: Panel 18; Appliance: Panels 14-15 | Verified live via fincore and procfs. |
| | Network bandwidth & errors | `node_network_receive_bytes_total`, `node_network_receive_errs_total` | Host & GPU: Panels 21-22 | Verified live on physical interfaces. |
| | Host uptime | `node_boot_time_seconds` | Host & GPU: Panel 6 | Verified live. |
| **4. Inference Performance** | Prompt eval & decode speed | `aihost:engine_prompt_eval_tokens_per_second:rate5m`, `aihost:engine_decode_tokens_per_second:rate5m` | Inference: Panels 7-8 | Verified live (measures busy-second throughput). |
| | Active / queued requests | `aihost_engine_requests_running`, `aihost_engine_requests_waiting`, `aihost_worker_inflight` | Inference: Panels 14-16 | Verified live. |
| | Latency (duration & queue wait) | `aihost:inference_duration_seconds:p50_5m`, `p95_5m`, `aihost_scheduler_queue_wait_seconds_*` | Inference: Panels 11-12 | Verified live. **Note:** TTFT & ITL are unmeasurable upstream due to non-streaming execution. |
| | Cache reuse | `aihost:engine_prefix_cache_hit_ratio:rate1h`, `aihost_engine_kv_cache_usage_ratio` | Inference: Panels 10, 15 | Verified live. |
| | Request outcomes & rejections | `aihost:inference_completions:rate5m`, `outcome="rejected"`, `error_ratio` | Inference: Panels 4, 6, 13 | Verified live. Caller faults are isolated from provider errors. |
| | Termination reasons | `aihost_completion_terminations_total` | Inference: Panel 14 | Verified live (stop vs length). |
| **5. Gateway Routing & Policy** | Worker eligibility & health | `aihost_worker_health_status`, `aihost_worker_drained` | Inference: Panels 2, 24 | Verified live. |
| | Route matching & destinations | `aihost_route_decisions_total` | Inference: Panel 17 | Verified live. Distinguishes `engineering/lead-reasoning` at 8192 from reasoning-off lead routes. |
| | Worker dispatches & fallback | `aihost_inference_dispatches_total` | Inference: Panel 18 | Verified live. |
| | Client authority & auth | `aihost_authority_validations_total` | Inference: Panel 19 | Verified live (allow vs deny tracked without exposing secrets). |
| | HTTP response codes | `aihost_http_requests_total` | Inference: Panel 20 | Verified live. |
| **6. Production Lifecycle** | Deployed release identity | Deployed tag (`t5820-gateway-6a3a52e`), manifest verification | Inference: Description & metadata | Verified live. |
| | Evidence chain validity | `aihost_evidence_chain_valid`, `aihost_evidence_verification_failures_total` | Inference: Panels 21-22 | Verified live (valid = 1). |
| | Reconciliation timer status | `aihost_reconciliation_timer_active` | Inference: Panel 23 | Verified live (0 indicates intentional operational pause during GPU sweeps). |
| **7. Logs & Correlation** | Multi-service journal ingestion | Loki `{job="systemd-journal"}`, `{instance="ai-5820-01"}` | Appliance: Panel 19; Stack Health: Panel 15 | Verified live rows from journal and ingress services. |
| | Trace correlation | Derived field `TraceID` matching `(?:traceID\|trace_id)=(\w+)` | Grafana Loki Datasource | Verified live (direct 1-click drilldown into Tempo). |
| **8. Tracing** | OTLP span ingestion & Tempo | `tempo_receiver_accepted_spans`, `tempo_live_store_traces_created_total` | Stack Health: Panel 11 | Verified live (pipeline demonstrated; query defect fixed). |
| | Service graph flow | `traces_service_graph_request_total` | Stack Health: Panel 12 | Verified live. |
| | Scope boundary documentation | Explicit Markdown panel | Stack Health: Panel 13 | Documented on dashboard and operational architecture. |
| **9. Stack Infrastructure Health** | Scrape target freshness | `up`, `count(up == 1)` | Stack Health: Panels 1, 7 | Verified live (all targets UP). |
| | VictoriaMetrics ingestion/storage | `vm_rows_inserted_total`, `vm_free_disk_space_bytes`, `vm_http_requests_total` | Stack Health: Panels 2-3, 9-10 | Verified live. |
| | Loki ingestion & log volume | `loki_log_messages_total`, `loki_ingester_wal_logged_bytes_total` | Stack Health: Panels 4, 15 | Verified live. |
| | vmalert evaluation health | `vmalert_iteration_total`, `vmalert_execution_errors_total` | Stack Health: Panel 5 | Verified live (zero execution errors). |
| **10. Alerting** | Active & pending alerts | `ALERTS{alertstate="firing"}`, `vmalert_alerts_firing`, `vmalert_alerts_pending` | Appliance: Panel 8; Stack Health: Panel 6 | Verified live. |
| | Missing telemetry alerts | `AihostMetricsFileStale`, `AihostWorkerEngineStatsMissing`, `AihostTargetDown` | `vmalert` rule engine | Verified live in rule evaluations. |
| | Notification delivery path | Explicit Markdown panel | Stack Health: Panel 14 | Rule evaluation verified active; delivery routed to local audit logs. |

### Operational Boundaries & Limitations

1. **GPU Driver VRAM Telemetry (Intel Arc B65) vs Host DRAM:**
   - The Linux kernel `xe` driver does not provide driver-level VRAM allocation statistics via sysfs or Level Zero without `xpumd` (Intel XPU Manager).
   - *Host vs GPU Memory Qualification:* Dashboards observe host system DRAM occupancy (where mmap'd GGUF weights reside and get mapped into SYCL Level Zero USM device memory) via OS page-cache residency (`aihost:llama_model_file_cache_residency:ratio`) and worker RSS (`aihost_llama_worker_resident_file_bytes`). These host metrics do **not** measure device-local GPU VRAM allocation or on-card memory bus saturation. GPU VRAM occupancy remains an explicit hardware/driver observability gap.
2. **PCIe Link Capabilities, Upstream Topology & Negotiated Status:**
   - Raw PCI tree inspection (`lspci -tv`) reveals a multi-tier topology:
     - *Host Root Ports:* `0000:4e:00.0` (for GPU 0) and `0000:90:00.0` (for GPU 1) are Dell Precision 5820 C422/Skylake-E root ports operating at **Speed 8GT/s, Width x16** (PCIe Gen3 x16).
     - *Card Onboard PCI Switch:* Devices `0000:4f:00.0` and `0000:91:00.0` (Intel `8086:e2ff` bridge) connect to the host root port at **Speed 8GT/s, Width x16**.
     - *Internal Downstream Switch Ports:* Switch downstream ports `0000:50:01.0` and `0000:92:01.0` (Port #8 on bridge `8086:e2ff`) report capability and status: **Speed 2.5GT/s, Width x1**.
     - *Inspected Graphics Endpoints:* Battlemage G31 graphics tiles `0000:51:00.0` and `0000:93:00.0` report `LnkCap: Speed 2.5GT/s, Width x1` and `LnkSta: Speed 2.5GT/s, Width x1`.
   - *Conclusion:* The physical slot link operates at **Gen3 x16 (8 GT/s)**. The 1x width at 2.5 GT/s reported by `aihost_gpu_pcie_link_width` reflects the **internal downstream link from the onboard bridge `8086:e2ff` to the graphics tile endpoint**, rather than a degradation of the physical PCIe card slot.
3. **Alloy Internal Metrics (Closed Collection Gap):**
   - Configured `prometheus.scrape "observability_self"` in `config.alloy` to scrape `127.0.0.1:12345` (`job="alloy"`).
   - Metrics are active in VictoriaMetrics: `up{job="alloy"} = 1`, `prometheus_remote_storage_samples_total`.
   - Stack Health Panel 8 queries `rate(prometheus_remote_storage_samples_total[1m])` and `rate(prometheus_remote_storage_samples_failed_total[1m])`, providing live remote-write egress visibility.
4. **Distributed Tracing Pipeline Boundary:**
   - The backend tracing pipeline (Alloy OTLP ingestion on `:4317`/`:4318`, Tempo storage on `:3200`, and VictoriaMetrics service graph generation) is verified.
   - *Operational Consequence:* In-process instrumentation across Nexus, the orchestrator gateway, and llama.cpp workers remains an unproven boundary. Telemetry spans demonstrate backend pipeline and correlation capability, not native production inference tracing. Trace panels remain unpopulated during normal production inference.
5. **Alert Notification Delivery:**
   - Alerts are actively evaluated in `vmalert` every 15s and queryable via `ALERTS`.
   - *Operational Consequence:* Notifications are dispatched solely to local audit logs (`/var/log/local-ai/alerts/`) and loopback endpoints. External paging integrations (PagerDuty, Slack, SMTP) are intentionally unconfigured to prevent false-alarm pages during automated GPU baseline sweeps and stress benchmarks. Consequently, firing alerts will **not** page on-call personnel; alerting requires operators actively monitoring Grafana dashboards or inspecting local alert logs.
6. **Reconciliation Timer Pause Authorization & Resumption:**
   - `aihost_reconciliation_timer_active` reporting `0` indicates that `scheduled_ansible_reconcile_enabled` is set to `false` in `inventory/production/host_vars/ai-5820-01.yml`.
   - *Authorization:* Configured by Mike Holownych (commit `6a039cca`) to protect the live dual-worker inference topology and long-running GPU evaluations against unintended configuration overwrites from unconstrained `site.yml` runs.
   - *Resumption Criteria:* The reconciliation timer should resume only after: (a) a repository snapshot is deployed to `/opt/local-ai`, (b) the reconciliation unit is scoped specifically to `playbooks/inference.yml` and matching validate plays, and (c) active GPU benchmarking sweeps conclude.
7. **Availability, Administrative Drain, and Metric Absence:**
   - Dashboards maintain explicit separation between:
     - *Administrative Routing State:* `aihost_worker_drained = 0` means "not drained" (traffic routing permitted), distinct from health or active execution.
     - *Health Probe Availability:* `aihost_worker_health_status = 1` indicates that gateway periodic `/health` probes succeed.
     - *Inference Execution Success:* `aihost_inference_completions_total{outcome="completed"}` tracks actual request and token generation completions.
     - *Metric Absence vs Zero:* TSDB series that do not exist when inactive (`ALERTS{alertstate="firing"}`, `outcome="rejected"`) render as empty sets / "No data", whereas physical gauges (`throttle = 0`, `network_errs = 0`, `drained = 0`) and PromQL fallbacks (`or 0 * completed`) output measured zeros.
8. **Live Inference Worker Topology:**
   - Worker 1 (`b0-live-llama-worker1`): GPU 0 (`0000:51:00.0`), port 8000, model **`Qwen3.6-35B-A3B-UD-Q4_K_M`**, alias `Qwen3.6-35B-A3B-UD-Q4_K_M`, reasoning budget 8192 (`engineering/lead-reasoning`).
   - Worker 2 (`b0-live-llama-deep-worker2`): GPU 1 (`0000:93:00.0`), port 8001, model **`Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M`**, alias `Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M`, reasoning budget 4096.
9. **Quality Gates & Hosted CI Verification:**
   - *Local Gates:* `make syntax`, `make check`, `make lint` (0 failures, 0 warnings), and `pytest -q` (1171 passed) pass cleanly.
   - *Hosted GitHub Actions CI:*
     - Workflow `quality.yml` (Run ID `38110956058`) on commit `433554c` **PASSED** in 15m 17s.
     - Workflow `quality.yml` (Run ID `38113136143`) on commit `6d95874` is currently executing.
