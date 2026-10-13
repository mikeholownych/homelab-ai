#!/usr/bin/env python3
"""Generate the Grafana dashboards deterministically (so they are reviewable, diffable and testable).

    python observability/tools/build_dashboards.py            # write observability/grafana/dashboards/*.json
    python observability/tools/build_dashboards.py --check    # exit 1 if the committed files differ

Every expression only uses metrics that exist (tests/test_observability_as_code.py enforces that), and every
panel carries a unit and a plain-language description of what it does and does not tell you.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "grafana" / "dashboards"
DS = {"type": "prometheus", "uid": "${DS_PROMETHEUS}"}


class Board:
    def __init__(self, uid: str, title: str, description: str):
        self.uid, self.title, self.description = uid, title, description
        self.panels: list[dict] = []
        self._y = 0
        self._x = 0
        self._id = 1

    def row(self, title: str) -> None:
        self._x, self._y = 0, self._y + (0 if not self.panels else 8)
        self.panels.append({"id": self._id, "type": "row", "title": title, "collapsed": False,
                            "gridPos": {"h": 1, "w": 24, "x": 0, "y": self._y}, "panels": []})
        self._id += 1
        self._y += 1

    def _place(self, w: int, h: int) -> dict:
        if self._x + w > 24:
            self._x, self._y = 0, self._y + h
        pos = {"h": h, "w": w, "x": self._x, "y": self._y}
        self._x += w
        return pos

    def _target(self, expr: str, legend: str, ref: str) -> dict:
        return {"datasource": DS, "expr": expr, "legendFormat": legend, "refId": ref, "editorMode": "code", "range": True}

    def timeseries(self, title: str, description: str, targets: list[tuple[str, str]], unit: str = "short",
                   w: int = 12, h: int = 8, stack: bool = False, min_: float | None = None, max_: float | None = None,
                   no_data_text: str | None = None) -> None:
        defaults = {"unit": unit, "custom": {"fillOpacity": 25 if stack else 8, "lineWidth": 1, "showPoints": "never",
                                              "stacking": {"mode": "normal" if stack else "none"}}}
        if min_ is not None:
            defaults["min"] = min_
        if max_ is not None:
            defaults["max"] = max_
        if no_data_text is not None:
            defaults["noDataText"] = no_data_text
        self.panels.append({"id": self._id, "type": "timeseries", "title": title, "description": description, "datasource": DS,
                             "gridPos": self._place(w, h), "fieldConfig": {"defaults": defaults, "overrides": []},
                             "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
                             "targets": [self._target(e, l, chr(65 + i)) for i, (e, l) in enumerate(targets)]})
        self._id += 1

    def stat(self, title: str, description: str, expr: str, unit: str = "short", w: int = 6, h: int = 4,
             thresholds: list[tuple[float | None, str]] | None = None, no_data_text: str | None = None) -> None:
        steps = [{"color": c, "value": v} for v, c in (thresholds or [(None, "green")])]
        defaults = {"unit": unit, "thresholds": {"mode": "absolute", "steps": steps}}
        if no_data_text is not None:
            defaults["noDataText"] = no_data_text
        self.panels.append({"id": self._id, "type": "stat", "title": title, "description": description, "datasource": DS,
                            "gridPos": self._place(w, h),
                            "fieldConfig": {"defaults": defaults, "overrides": []},
                            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}, "colorMode": "value"},
                            "targets": [self._target(expr, "", "A")]})
        self._id += 1

    def build(self) -> dict:
        return {"uid": self.uid, "title": self.title, "description": self.description, "schemaVersion": 39, "version": 1,
                "editable": False, "graphTooltip": 1, "refresh": "30s", "tags": ["aihost"], "time": {"from": "now-6h", "to": "now"},
                "timezone": "browser",
                "links": [
                    {"title": "Appliance Overview", "url": "/d/aihost-appliance-telemetry/aihost-appliance-and-gpu-telemetry", "type": "link", "targetBlank": False},
                    {"title": "Inference Drilldown", "url": "/d/aihost-inference/aihost-inference", "type": "link", "targetBlank": False},
                    {"title": "Host & GPU Drilldown", "url": "/d/aihost-host/aihost-host-and-gpu", "type": "link", "targetBlank": False},
                    {"title": "Stack Health", "url": "/d/observability-stack-health/observability-stack-infrastructure-health", "type": "link", "targetBlank": False},
                ],
                "templating": {"list": [
                    {"name": "DS_PROMETHEUS", "label": "Prometheus", "type": "datasource", "query": "prometheus",
                     "current": {"selected": True, "text": "VictoriaMetrics", "value": "victoriametrics"}, "hide": 0},
                    {"name": "worker", "label": "Worker", "type": "query", "datasource": DS, "includeAll": True, "multi": True,
                     "allValue": ".*", "refresh": 2, "current": {"selected": True, "text": "All", "value": "$__all"},
                     "query": {"query": "label_values(aihost_worker_info, worker_id)", "refId": "worker"}}]},
                "panels": self.panels}


def inference() -> dict:
    b = Board("aihost-inference", "AIHost - inference",
              "Gateway and engine view of the local inference stack. Engine counters advance when a request finishes, "
              "so rates are smooth only over minutes; TTFT and inter-token latency are not measurable (non-streaming upstream).")
    W = 'worker_id=~"$worker"'
    b.row("Overview")
    b.stat("Workers healthy", "Workers the gateway currently considers healthy.", f"sum(aihost_worker_health_status{{{W}}})", thresholds=[(None, "red"), (1, "green")], w=4)
    b.stat("Requests / s", "Inference requests received by the gateway.", 'sum(rate(aihost_inference_requests_total{status="received"}[5m]))', unit="reqps", w=4)
    b.stat("Provider error ratio", "Failed or timed-out share of requests that reached a worker. Caller faults (rejected) are excluded.",
           f"(max(aihost:inference_error_ratio:rate5m{{{W}}}) or vector(0))", unit="percentunit", thresholds=[(None, "green"), (0.05, "red")], no_data_text="0% (idle)", w=4)
    b.stat("Estimated token share (1 h)", "Share of counted tokens that are the gateway's estimate instead of the engine's exact usage. Should stay near 0%; a rise means an engine stopped reporting usage.",
           "(aihost:inference_tokens_estimated_share:rate1h or vector(0))", unit="percentunit", thresholds=[(None, "green"), (0.01, "orange")], no_data_text="0% (idle)", w=4)
    b.stat("Rejected / s (caller faults)", "Requests refused as invalid for the worker (context overflow, malformed history). Says nothing about worker health.",
           f'(sum(rate(aihost_inference_completions_total{{outcome="rejected",{W}}}[5m])) or vector(0))', unit="reqps", no_data_text="0 (idle)", w=4)
    b.stat("Gateway uptime", "Elapsed time in seconds since the orchestrator gateway started.", "max(aihost_gateway_uptime_seconds)", unit="s", w=4)

    b.row("Throughput")
    b.timeseries("Decode speed (tokens per busy second)", "Generated tokens divided by generation time, per worker. A decode-speed figure, not wall-clock throughput. Appears during active generation periods.",
                 [(f"aihost:engine_decode_tokens_per_second:rate5m{{{W}}}", "{{worker_id}}")], unit="short", no_data_text="No active generations in window")
    b.timeseries("Prompt evaluation speed (tokens per busy second)", "Prompt tokens evaluated per second of prompt processing; cached tokens are not included. Appears during active request processing.",
                 [(f"aihost:engine_prompt_eval_tokens_per_second:rate5m{{{W}}}", "{{worker_id}}")], unit="short", no_data_text="No prompt evaluations in window")
    b.timeseries("Generated tokens / s (wall clock)", "Tokens the engine generated per wall-clock second, averaged over 5 minutes.",
                 [(f"rate(aihost_engine_generation_tokens_total{{{W}}}[5m])", "{{worker_id}}")], unit="short")
    b.timeseries("Prefix-cache hit ratio (1 h window)", "Share of prompt tokens served from cache over the last hour alongside lifetime engine ratio.",
                 [(f"aihost:engine_prefix_cache_hit_ratio:rate1h{{{W}}}", "{{worker_id}} (1h window)"),
                  (f"aihost_engine_prefix_cache_hit_ratio{{{W}}}", "{{worker_id}} (lifetime)")], unit="percentunit", min_=0, max_=1)

    b.row("Latency and Outcomes")
    b.timeseries("Request duration p50 / p95 by pool", "Time the gateway spent on the worker call, including engine-side queueing. Measurement window: 5 minutes.",
                 [("aihost:inference_duration_seconds:p50_5m", "p50 {{pool}}"), ("aihost:inference_duration_seconds:p95_5m", "p95 {{pool}}")], unit="s", no_data_text="No completed requests in window")
    b.timeseries("Scheduler queue wait latency", "Average time requests spend waiting inside the gateway scheduler queue prior to worker dispatch. Measurement window: 5 minutes.",
                 [("rate(aihost_scheduler_queue_wait_seconds_sum[5m]) / (rate(aihost_scheduler_queue_wait_seconds_count[5m]) > 0)", "queue wait")], unit="s", no_data_text="No queued requests in window")
    b.timeseries("Requests by outcome", "Completed, failed, timed-out and rejected requests per second.",
                 [(f"aihost:inference_completions:rate5m{{{W}}}", "{{worker_id}} {{outcome}}")], unit="reqps", stack=True)
    b.timeseries("Completion terminations by reason", "Completed inference requests broken down by termination reason (stop token, max length context truncation).",
                 [('sum by (model, reason) (rate(aihost_completion_terminations_total[5m]))', "{{model}} - {{reason}}")], unit="short", stack=True)

    b.row("Engine state")
    b.timeseries("Running / waiting requests", "Requests being processed and requests deferred inside the engine. Sustained waiting means queueing.",
                 [(f"aihost_engine_requests_running{{{W}}}", "running {{worker_id}}"), (f"aihost_engine_requests_waiting{{{W}}}", "waiting {{worker_id}}")])
    b.timeseries("Context occupancy (KV)", "Share of the context window held by active or retained sequences. When idle this is the retained context, not zero.",
                 [(f"aihost_engine_kv_cache_usage_ratio{{{W}}}", "{{worker_id}}")], unit="percentunit", min_=0, max_=1)
    b.timeseries("In-flight tokens", "Tokens decoded / prompt tokens evaluated so far by requests still running.",
                 [(f"aihost_engine_generation_tokens_in_flight{{{W}}}", "decoded {{worker_id}}"), (f"aihost_engine_prompt_tokens_in_flight{{{W}}}", "prompt {{worker_id}}")])
    b.timeseries("Requests outstanding vs configured concurrency", "Requests the gateway has on a worker versus its max concurrency; the excess waits inside the engine.",
                 [(f"aihost_worker_inflight{{{W}}}", "in flight {{worker_id}}"), (f"aihost_worker_max_concurrency{{{W}}}", "max {{worker_id}}")])

    b.row("Routing, Policy and Authentication")
    b.timeseries("Route decisions by rule and pool", "Routing rule evaluations and destinations. Distinguishes reasoning-off lead routes from engineering/lead-reasoning at 8192 context window.",
                 [("sum by (rule, pool) (rate(aihost_route_decisions_total[5m]))", "{{rule}} -> {{pool}}")], unit="reqps", stack=True)
    b.timeseries("Worker dispatches / s", "Dispatches to target inference workers, reflecting distribution, health-based eligibility, and fallback.",
                 [("sum by (target_worker) (rate(aihost_inference_dispatches_total[5m]))", "-> {{target_worker}}")], unit="reqps", stack=True)
    b.timeseries("Client authority validations", "Client authority check rate partitioned by authority and outcome (allow / deny) without exposing credentials.",
                 [("sum by (authority, result) (rate(aihost_authority_validations_total[5m]))", "{{authority}} ({{result}})")], unit="reqps", stack=True)
    b.timeseries("HTTP requests by status code", "Gateway HTTP ingress request outcomes grouped by response status code.",
                 [("sum by (code) (rate(aihost_http_requests_total[5m]))", "HTTP {{code}}")], unit="reqps", stack=True)
    b.timeseries("Token accounting by source (tokens / s)", "Tokens the gateway counted: provider = the engine's exact usage, estimated = the gateway's fallback.",
                 [('sum by (source) (rate(aihost_inference_prompt_tokens_total[5m]))', "prompt {{source}}"),
                  ('sum by (source) (rate(aihost_inference_completion_tokens_total[5m]))', "completion {{source}}")], stack=True)
    b.timeseries("Circuit breaker state by worker and pool", "Current circuit breaker state: 0 = CLOSED (healthy), 0.5 = HALF-OPEN (probing), 1 = OPEN (tripped).",
                 [("max by (target_type, target_id) (aihost_circuit_breaker_state)", "{{target_type}}: {{target_id}}")], unit="short", min_=0, max_=1)
    b.timeseries("Response cache performance (hits vs misses / s)", "Sub-millisecond response cache hits vs misses.",
                 [("sum by (model) (rate(aihost_gateway_cache_hits_total[5m]))", "hits {{model}}"),
                  ("sum by (model) (rate(aihost_gateway_cache_misses_total[5m]))", "misses {{model}}")], unit="reqps", stack=True)
    b.timeseries("Security & Guardrail Activity (violations / s)", "Rate of detected prompt injection and sensitive secret DLP violations on ingress and egress.",
                 [("sum by (direction, action, violation_type) (rate(aihost_guardrail_violations_total[5m]))", "{{direction}} {{action}}: {{violation_type}}")], unit="events/s", stack=True)

    b.row("Production Lifecycle")
    b.stat("Evidence chain valid", "Release evidence chain verification state (1 = cryptographically valid, 0 = failed).",
           "min(aihost_evidence_chain_valid)", thresholds=[(None, "red"), (1, "green")])
    b.stat("Evidence verification failures / s", "Rate of release evidence verification failures.",
           "sum(rate(aihost_evidence_verification_failures_total[5m]))", thresholds=[(None, "green"), (0.01, "red")])
    b.stat("Reconciliation timer active", "State of scheduled Ansible reconciliation timer (0 = paused, 1 = active). Value 0 is an expected operational pause during benchmark sweeps.",
           "max(aihost_reconciliation_timer_active)", thresholds=[(None, "blue"), (1, "green")])
    b.stat("Workers drained", "Count of workers marked as drained for scheduled maintenance.",
           f"sum(aihost_worker_drained{{{W}}})", thresholds=[(None, "green"), (1, "orange")])
    return b.build()


def host() -> dict:
    b = Board("aihost-host", "AIHost - host and GPU",
              "Host CPU, memory, disk and the two Arc GPUs. Decode on this machine is bound by a single CPU thread, so the busiest-core panel "
              "is the one that explains inference speed.")
    b.row("Overview")
    b.stat("Thermal severity", "0 ok, 1 warning, 2 critical, from the host thermal state machine.", "max(aihost_gpu_thermal_severity)", thresholds=[(None, "green"), (1, "orange"), (2, "red")], w=4)
    b.stat("Closest GPU temperature to limit", "Smallest gap (C) between any sensor and its kernel-reported critical limit.", "min(aihost:gpu_temperature_headroom_celsius:min)", unit="celsius",
           thresholds=[(None, "red"), (10, "orange"), (25, "green")], w=4)
    b.stat("Busiest CPU core", "Highest per-core busy share over 5 minutes.", "max(aihost:cpu_busiest_core_ratio:rate5m)", unit="percentunit", thresholds=[(None, "green"), (0.9, "orange")], w=4)
    b.stat("Host metrics age", "Seconds since the textfile exporter last wrote its file (it runs every minute).", "time() - max(aihost_metrics_last_success_timestamp_seconds)", unit="s",
           thresholds=[(None, "green"), (180, "orange"), (300, "red")], w=4)
    b.stat("Host uptime", "Seconds elapsed since the host kernel booted.", "time() - min(node_boot_time_seconds)", unit="s", w=4)
    b.stat("GPU throttle active", "Hardware frequency throttling state (0 = normal, 1 = throttled).", "max(aihost_gpu_throttle_status)", thresholds=[(None, "green"), (1, "red")], w=4)

    b.row("Dual Intel Arc B65 GPUs")
    b.timeseries("GPU utilisation (awake share)", "1 minus the share of time the graphics tile sat in RC6 idle: busy or not, not execution-unit occupancy.",
                 [("aihost:gpu_utilization_ratio:rate5m", "gpu{{gpu}}")], unit="percentunit", min_=0, max_=1)
    b.timeseries("GPU power (W) and cap", "Whole-card power from the energy counter versus configured card power cap.",
                 [("aihost:gpu_power_watts:rate5m", "power gpu{{gpu}}"), ("aihost_gpu_power_cap_watts", "cap gpu{{gpu}}")], unit="watt")
    b.timeseries("Energy per generated token, idle included (J)", "Card energy over 15 minutes divided by tokens generated, idle time included, so it falls as utilisation rises.",
                 [("aihost:joules_per_generated_token_incl_idle:rate15m", "{{worker_id}}")], unit="joule")
    b.timeseries("Temperature: sensors vs limit", "Package, VRAM, PCIe, and memory controller sensors with kernel-reported critical limits.",
                 [('aihost_gpu_temperature_celsius{sensor=~"pkg|vram|pcie|mctrl"}', "{{sensor}} gpu{{gpu}}"),
                  ('aihost_gpu_temperature_limit_celsius{sensor=~"pkg|vram"}', "limit {{sensor}} gpu{{gpu}}")], unit="celsius")
    b.timeseries("Graphics tile frequency", "Actual graphics tile frequency.", [("aihost_gpu_actual_frequency_hertz", "gpu{{gpu}} {{gt}}")], unit="hertz", w=8)
    b.timeseries("Hardware throttle triggers", "Hardware frequency throttle triggers from graphics tile registers (thermal and power limit throttling).",
                 [("aihost_gpu_throttle_reason_thermal", "thermal throttle gpu{{gpu}}"), ("aihost_gpu_throttle_reason_power", "power throttle gpu{{gpu}}")], unit="short", min_=0, max_=1, w=8)
    b.timeseries("PCIe Link: Physical Slot vs Internal Endpoint", "PCIe physical motherboard slot link (host root port to card bridge: Gen3 x16, 8 GT/s) alongside internal endpoint link (onboard bridge to graphics tile: x1, 2.5 GT/s).",
                 [("aihost_gpu_slot_pcie_link_width", "GPU {{gpu}} physical slot width"),
                  ("aihost_gpu_slot_pcie_link_speed_gts", "GPU {{gpu}} physical slot speed GT/s"),
                  ("aihost_gpu_pcie_link_width", "GPU {{gpu}} internal endpoint width"),
                  ("aihost_gpu_pcie_link_speed_gts", "GPU {{gpu}} internal endpoint speed GT/s")], unit="short", w=8)
    b.timeseries("GPU VRAM allocation and worker residency",
                 "Resident GPU VRAM allocated by llama.cpp workers via kernel xe DRM fdinfo versus total physical VRAM (BAR2 32 GiB aperture).",
                 [("aihost_gpu_vram_used_bytes", "GPU {{gpu}} VRAM used"),
                  ("aihost_gpu_vram_total_bytes", "GPU {{gpu}} VRAM total"),
                  ("aihost_llama_worker_vram_resident_bytes", "Worker port {{port}} resident")], unit="bytes", w=12, h=8)
    b.timeseries("GPU VRAM utilization ratio",
                 "Share of physical GPU VRAM allocated to inference workloads.",
                 [("aihost:gpu_vram_usage_ratio:ratio", "GPU {{gpu}} ({{bdf}})")], unit="percentunit", min_=0, max_=1, w=12, h=8)

    b.row("Host CPU, Memory and Pressure")
    b.timeseries("CPU busy per core", "Per-core busy share. One core near 100% while the rest idle is the single-thread decode bottleneck.",
                 [("aihost:cpu_core_busy_ratio:rate5m", "cpu{{cpu}}")], unit="percentunit", min_=0, max_=1)
    b.timeseries("Memory available and swap", "Available memory, total host memory, and active swap space in bytes.",
                 [("node_memory_MemAvailable_bytes", "available"), ("node_memory_MemTotal_bytes", "total"), ("node_memory_SwapTotal_bytes - node_memory_SwapFree_bytes", "swap used")], unit="bytes")
    b.timeseries("Linux PSI (Pressure Stall Information)", "Percentage of time tasks are stalled waiting for CPU, memory, or I/O resources (100 * rate of waiting seconds).",
                 [("rate(node_pressure_cpu_waiting_seconds_total[5m]) * 100", "CPU PSI %"),
                  ("rate(node_pressure_memory_waiting_seconds_total[5m]) * 100", "Memory PSI %"),
                  ("rate(node_pressure_io_waiting_seconds_total[5m]) * 100", "I/O PSI %")], unit="percent", min_=0)
    b.timeseries("Model file page-cache residency and faults", "Share of model weights cached in host OS page cache (0..1) and worker major page fault rate requiring disk reads. Complements GPU VRAM allocation with host-side page-cache visibility.",
                 [("aihost:llama_model_file_cache_residency:ratio", "cache ratio"), ("aihost:llama_worker_major_faults:rate5m", "major faults/s")], unit="short")

    b.row("Host Disk, Network and Services")
    b.timeseries("Filesystem free space", "Free share of the root and local-ai model filesystems.",
                 [('node_filesystem_avail_bytes{mountpoint=~"/|/var/lib/local-ai",fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes{mountpoint=~"/|/var/lib/local-ai",fstype!~"tmpfs|overlay"}', "{{mountpoint}}")],
                 unit="percentunit", min_=0, max_=1, w=8)
    b.timeseries("Disk throughput (read / write)", "Disk read and write throughput in bytes per second for physical storage.",
                 [("sum by (device) (rate(node_disk_read_bytes_total[5m]))", "read {{device}}"), ("sum by (device) (rate(node_disk_written_bytes_total[5m]))", "write {{device}}")], unit="Bps", w=8)
    b.timeseries("Disk I/O time (% busy)", "Percentage of time physical disks were occupied servicing read or write requests.",
                 [("sum by (device) (rate(node_disk_io_time_seconds_total[5m])) * 100", "{{device}} io %")], unit="percent", w=8)
    b.timeseries("Network throughput (Rx / Tx)", "Network ingress and egress bandwidth on host interfaces.",
                 [('rate(node_network_receive_bytes_total{device=~"en.*|eth.*"}[5m]) * 8', "Rx {{device}}"), ('rate(node_network_transmit_bytes_total{device=~"en.*|eth.*"}[5m]) * 8', "Tx {{device}}")], unit="bps", w=8)
    b.timeseries("Network errors (Rx / Tx)", "Network packet receive and transmit error rate.",
                 [('rate(node_network_receive_errs_total{device=~"en.*|eth.*"}[5m])', "Rx err {{device}}"), ('rate(node_network_transmit_errs_total{device=~"en.*|eth.*"}[5m])', "Tx err {{device}}")], unit="pps", w=8)
    b.timeseries("Inference service units (1 = active)", "systemd state of the gateway, workers and console.",
                 [('node_systemd_unit_state{state="active"}', "{{name}}")], min_=0, max_=1, w=8)
    return b.build()


def render() -> dict[str, str]:
    return {f"{d['uid']}.json": json.dumps(d, indent=2, sort_keys=True) + "\n" for d in (inference(), host())}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    files = render()
    if args.check:
        stale = [n for n, text in files.items() if not (OUT / n).exists() or (OUT / n).read_text() != text]
        print("dashboards are up to date" if not stale else f"stale dashboards: {stale}")
        sys.exit(1 if stale else 0)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (OUT / name).write_text(text)
        print("wrote", OUT / name)
