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
                   w: int = 12, h: int = 8, stack: bool = False, min_: float | None = None, max_: float | None = None) -> None:
        defaults = {"unit": unit, "custom": {"fillOpacity": 25 if stack else 8, "lineWidth": 1, "showPoints": "never",
                                              "stacking": {"mode": "normal" if stack else "none"}}}
        if min_ is not None:
            defaults["min"] = min_
        if max_ is not None:
            defaults["max"] = max_
        self.panels.append({"id": self._id, "type": "timeseries", "title": title, "description": description, "datasource": DS,
                            "gridPos": self._place(w, h), "fieldConfig": {"defaults": defaults, "overrides": []},
                            "options": {"legend": {"displayMode": "list", "placement": "bottom"}, "tooltip": {"mode": "multi"}},
                            "targets": [self._target(e, l, chr(65 + i)) for i, (e, l) in enumerate(targets)]})
        self._id += 1

    def stat(self, title: str, description: str, expr: str, unit: str = "short", w: int = 6, h: int = 4,
             thresholds: list[tuple[float | None, str]] | None = None) -> None:
        steps = [{"color": c, "value": v} for v, c in (thresholds or [(None, "green")])]
        self.panels.append({"id": self._id, "type": "stat", "title": title, "description": description, "datasource": DS,
                            "gridPos": self._place(w, h),
                            "fieldConfig": {"defaults": {"unit": unit, "thresholds": {"mode": "absolute", "steps": steps}}, "overrides": []},
                            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}, "colorMode": "value"},
                            "targets": [self._target(expr, "", "A")]})
        self._id += 1

    def build(self) -> dict:
        return {"uid": self.uid, "title": self.title, "description": self.description, "schemaVersion": 39, "version": 1,
                "editable": False, "graphTooltip": 1, "refresh": "30s", "tags": ["aihost"], "time": {"from": "now-6h", "to": "now"},
                "timezone": "browser",
                "templating": {"list": [
                    {"name": "DS_PROMETHEUS", "label": "Prometheus", "type": "datasource", "query": "prometheus", "current": {}, "hide": 0},
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
    b.stat("Workers healthy", "Workers the gateway currently considers healthy.", f"sum(aihost_worker_health_status{{{W}}})", thresholds=[(None, "red"), (1, "green")])
    b.stat("Requests / s", "Inference requests received by the gateway.", 'sum(rate(aihost_inference_requests_total{status="received"}[5m]))', unit="reqps")
    b.stat("Provider error ratio", "Failed or timed-out share of requests that reached a worker. Caller faults (rejected) are excluded.",
           f"max(aihost:inference_error_ratio:rate5m{{{W}}})", unit="percentunit", thresholds=[(None, "green"), (0.05, "red")])
    b.stat("Estimated token share (1 h)", "Share of counted tokens that are the gateway's estimate instead of the engine's exact usage. Should stay near 0%; a rise means an engine stopped reporting usage.",
           "aihost:inference_tokens_estimated_share:rate1h", unit="percentunit", thresholds=[(None, "green"), (0.01, "orange")])
    b.stat("Rejected / s (caller faults)", "Requests refused as invalid for the worker (context overflow, malformed history). Says nothing about worker health.",
           f'sum(rate(aihost_inference_completions_total{{outcome="rejected",{W}}}[5m]))', unit="reqps")
    b.row("Throughput")
    b.timeseries("Decode speed (tokens per busy second)", "Generated tokens divided by generation time, per worker. A decode-speed figure, not wall-clock throughput.",
                 [(f"aihost:engine_decode_tokens_per_second:rate5m{{{W}}}", "{{worker_id}}")], unit="short")
    b.timeseries("Prompt evaluation speed (tokens per busy second)", "Prompt tokens evaluated per second of prompt processing; cached tokens are not included.",
                 [(f"aihost:engine_prompt_eval_tokens_per_second:rate5m{{{W}}}", "{{worker_id}}")], unit="short")
    b.timeseries("Generated tokens / s (wall clock)", "Tokens the engine generated per wall-clock second, averaged over 5 minutes.",
                 [(f"rate(aihost_engine_generation_tokens_total{{{W}}}[5m])", "{{worker_id}}")], unit="short")
    b.timeseries("Prefix-cache hit ratio (1 h window)", "Share of prompt tokens served from cache over the last hour.",
                 [(f"aihost:engine_prefix_cache_hit_ratio:rate1h{{{W}}}", "{{worker_id}}")], unit="percentunit", min_=0, max_=1)
    b.row("Latency")
    b.timeseries("Request duration p50 / p95 by pool", "Time the gateway spent on the worker call, including engine-side queueing. Not time-to-first-token.",
                 [("aihost:inference_duration_seconds:p50_5m", "p50 {{pool}}"), ("aihost:inference_duration_seconds:p95_5m", "p95 {{pool}}")], unit="s")
    b.timeseries("Requests by outcome", "Completed, failed, timed-out and rejected requests per second.",
                 [(f"aihost:inference_completions:rate5m{{{W}}}", "{{worker_id}} {{outcome}}")], unit="reqps", stack=True)
    b.row("Engine state")
    b.timeseries("Running / waiting requests", "Requests being processed and requests deferred inside the engine. Sustained waiting means queueing.",
                 [(f"aihost_engine_requests_running{{{W}}}", "running {{worker_id}}"), (f"aihost_engine_requests_waiting{{{W}}}", "waiting {{worker_id}}")])
    b.timeseries("Context occupancy (KV)", "Share of the context window held by active or retained sequences. When idle this is the retained context, not zero.",
                 [(f"aihost_engine_kv_cache_usage_ratio{{{W}}}", "{{worker_id}}")], unit="percentunit", min_=0, max_=1)
    b.timeseries("In-flight tokens", "Tokens decoded / prompt tokens evaluated so far by requests still running.",
                 [(f"aihost_engine_generation_tokens_in_flight{{{W}}}", "decoded {{worker_id}}"), (f"aihost_engine_prompt_tokens_in_flight{{{W}}}", "prompt {{worker_id}}")])
    b.row("Routing and accounting")
    b.timeseries("Route decisions / s", "Which routing rule sent traffic to which pool.", [("sum by (rule, pool) (rate(aihost_route_decisions_total[5m]))", "{{rule}} -> {{pool}}")],
                 unit="reqps", stack=True)
    b.timeseries("Token accounting by source (tokens / s)", "Tokens the gateway counted: provider = the engine's exact usage, estimated = the gateway's fallback.",
                 [('sum by (source) (rate(aihost_inference_prompt_tokens_total[5m]))', "prompt {{source}}"),
                  ('sum by (source) (rate(aihost_inference_completion_tokens_total[5m]))', "completion {{source}}")], stack=True)
    b.timeseries("Requests outstanding vs configured concurrency", "Requests the gateway has on a worker versus its max concurrency; the excess waits inside the engine.",
                 [(f"aihost_worker_inflight{{{W}}}", "in flight {{worker_id}}"), (f"aihost_worker_max_concurrency{{{W}}}", "max {{worker_id}}")])
    return b.build()


def host() -> dict:
    b = Board("aihost-host", "AIHost - host and GPU",
              "Host CPU, memory, disk and the two Arc GPUs. Decode on this machine is bound by a single CPU thread, so the busiest-core panel "
              "is the one that explains inference speed.")
    b.row("Overview")
    b.stat("Thermal severity", "0 ok, 1 warning, 2 critical, from the host thermal state machine.", "max(aihost_gpu_thermal_severity)", thresholds=[(None, "green"), (1, "orange"), (2, "red")])
    b.stat("Closest GPU temperature to a kernel limit", "Smallest gap (C) between any sensor and its kernel-reported critical limit.", "min(aihost:gpu_temperature_headroom_celsius:min)", unit="celsius",
           thresholds=[(None, "red"), (10, "orange"), (25, "green")])
    b.stat("Busiest CPU core", "Highest per-core busy share over 5 minutes.", "max(aihost:cpu_busiest_core_ratio:rate5m)", unit="percentunit", thresholds=[(None, "green"), (0.9, "orange")])
    b.stat("Host metrics age", "Seconds since the textfile exporter last wrote its file (it runs every minute).", "time() - max(aihost_metrics_last_success_timestamp_seconds)", unit="s",
           thresholds=[(None, "green"), (180, "orange"), (300, "red")])
    b.row("GPU")
    b.timeseries("GPU utilisation (awake share)", "1 minus the share of time the graphics tile sat in RC6 idle: busy or not, not execution-unit occupancy.",
                 [("aihost:gpu_utilization_ratio:rate5m", "gpu{{gpu}}")], unit="percentunit", min_=0, max_=1)
    b.timeseries("GPU power (W)", "Whole-card power from the energy counter.", [("aihost:gpu_power_watts:rate5m", "gpu{{gpu}}")], unit="watt")
    b.timeseries("Energy per generated token, idle included (J)", "Card energy over 15 minutes divided by tokens generated, idle time included, so it falls as utilisation rises.",
                 [("aihost:joules_per_generated_token_incl_idle:rate15m", "{{worker_id}}")], unit="joule")
    b.timeseries("Temperature: package and VRAM vs limit", "Package and VRAM sensors with the kernel-reported critical limit.",
                 [('aihost_gpu_temperature_celsius{sensor=~"pkg|vram"}', "{{sensor}} gpu{{gpu}}"), ('aihost_gpu_temperature_limit_celsius{sensor=~"pkg|vram"}', "limit {{sensor}} gpu{{gpu}}")], unit="celsius")
    b.timeseries("Graphics tile frequency", "Actual graphics tile frequency.", [("aihost_gpu_actual_frequency_hertz", "gpu{{gpu}} {{gt}}")], unit="hertz")
    b.row("CPU, memory, disk")
    b.timeseries("CPU busy per core", "Per-core busy share. One core near 100% while the rest idle is the single-thread decode bottleneck.",
                 [("aihost:cpu_core_busy_ratio:rate5m", "cpu{{cpu}}")], unit="percentunit", min_=0, max_=1)
    b.timeseries("Memory available", "Available memory and its share of total.", [("node_memory_MemAvailable_bytes", "available"), ("node_memory_MemTotal_bytes", "total")], unit="bytes")
    b.timeseries("Filesystem free space", "Free share of the root and model filesystems.",
                 [('node_filesystem_avail_bytes{mountpoint=~"/|/var/lib/local-ai",fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes{mountpoint=~"/|/var/lib/local-ai",fstype!~"tmpfs|overlay"}', "{{mountpoint}}")],
                 unit="percentunit", min_=0, max_=1)
    b.timeseries("Inference service units (1 = active)", "systemd state of the gateway, workers and console.",
                 [('node_systemd_unit_state{state="active"}', "{{name}}")], min_=0, max_=1)
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
