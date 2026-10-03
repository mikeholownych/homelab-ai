"""The gateway's /metrics output must be consumable by Prometheus as-is, and the numbers must be right.

The validator below is deliberately strict (no network, no extra dependency): it encodes the exposition-format
rules a scraper enforces plus the naming/shape conventions dashboards rely on.
"""
from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from orchestrator_runtime import CapabilityRegistry, EvidenceStore, HealthManager, MetricsRegistry, OrchestratorRuntime, ProviderError
from orchestrator_runtime.metrics import Counter, Gauge, MirroredCounter
from orchestrator_runtime.runtime import _token_counts
from tests.test_orchestrator_runtime import _CapturingAdapter, worker

_NAME = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
_SAMPLE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{.*\})? (\S+)$')
_LABEL = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"')


def _value(text: str) -> float:
    return {"+Inf": float("inf"), "-Inf": float("-inf"), "NaN": float("nan")}.get(text) if text in ("+Inf", "-Inf", "NaN") else float(text)


def validate_exposition(text: str) -> dict[str, str]:
    """Raise AssertionError on anything a Prometheus scraper or dashboard author would trip over."""
    assert text.endswith("\n"), "exposition must end with a newline"
    types: dict[str, str] = {}
    helps: set[str] = set()
    seen_series: set[tuple[str, tuple]] = set()
    label_names_by_family: dict[str, set[tuple]] = {}
    closed: set[str] = set()
    current: str | None = None
    hist: dict[tuple[str, tuple], dict] = {}
    for line in text.splitlines():
        if not line:
            continue
        if line.startswith("# HELP "):
            name = line.split(" ", 3)[2]
            assert name not in helps, f"duplicate HELP for {name}"
            helps.add(name)
            continue
        if line.startswith("# TYPE "):
            _, _, name, kind = line.split(" ", 3)
            assert name not in types, f"duplicate TYPE for {name}"
            assert kind in ("counter", "gauge", "histogram"), f"{name}: unsupported type {kind}"
            assert _NAME.match(name), f"bad metric name {name}"
            if kind == "counter":
                assert name.endswith("_total"), f"counter {name} must end with _total"
            types[name] = kind
            continue
        assert not line.startswith("#"), f"unexpected comment: {line}"
        m = _SAMPLE.match(line)
        assert m, f"unparseable sample line: {line!r}"
        name, label_text, raw = m.group(1), m.group(2) or "", m.group(3)
        labels = tuple(sorted(_LABEL.findall(label_text)))
        assert "".join(f'{k}="{v}"' for k, v in _LABEL.findall(label_text)).replace(",", "") or not label_text, line
        value = float(raw.replace("+Inf", "inf").replace("-Inf", "-inf").replace("NaN", "nan"))
        family = name
        for suffix in ("_bucket", "_sum", "_count"):
            if name.endswith(suffix) and types.get(name[: -len(suffix)]) == "histogram":
                family = name[: -len(suffix)]
        assert family in types, f"sample {name} appears before/without a TYPE line"
        assert family in helps, f"family {family} has no HELP"
        if family != current:
            assert family not in closed, f"family {family} is split into non-contiguous groups"
            if current:
                closed.add(current)
            current = family
        key = (name, labels)
        assert key not in seen_series, f"duplicate series {name}{label_text}"
        seen_series.add(key)
        kind = types[family]
        if kind == "counter":
            assert value >= 0, f"negative counter {line}"
        base_labels = tuple(l for l in labels if l[0] != "le")
        label_names_by_family.setdefault(family, set()).add(tuple(k for k, _ in labels if k != "le"))
        if kind == "histogram":
            h = hist.setdefault((family, base_labels), {"buckets": [], "sum": None, "count": None})
            if name.endswith("_bucket"):
                le = dict(labels)["le"]
                h["buckets"].append((float(le.replace("+Inf", "inf")), value))
            elif name.endswith("_sum"):
                h["sum"] = value
            else:
                h["count"] = value
    for family, shapes in label_names_by_family.items():
        assert len(shapes) == 1, f"{family}: inconsistent label names across series: {shapes}"
    for (family, _), h in hist.items():
        bounds = [b for b, _ in h["buckets"]]
        counts = [c for _, c in h["buckets"]]
        assert bounds == sorted(bounds) and bounds[-1] == float("inf"), f"{family}: buckets must ascend and end at +Inf"
        assert counts == sorted(counts), f"{family}: bucket counts must be cumulative"
        assert h["count"] == counts[-1], f"{family}: +Inf bucket must equal _count"
        assert h["sum"] is not None, f"{family}: missing _sum"
    return types


# ----------------------------------------------------------------------------------------------- fixtures
class _Llama(BaseHTTPRequestHandler):
    METRICS = ("llamacpp:prompt_tokens_total 1000\nllamacpp:prompt_tokens_cached_total 9000\nllamacpp:prompt_seconds_total 12.5\n"
               "llamacpp:tokens_predicted_total 400\nllamacpp:tokens_predicted_seconds_total 5.25\nllamacpp:requests_processing 1\nllamacpp:requests_deferred 0\n")

    def do_GET(self):  # noqa: N802
        if self.path == "/slots":
            body = json.dumps([{"id": 0, "n_ctx": 65536, "is_processing": True, "n_prompt_tokens": 200, "n_prompt_tokens_processed": 20,
                                "next_token": [{"n_decoded": 50}]}])
        elif self.path == "/metrics":
            body = self.METRICS
        else:
            body = json.dumps({"data": []})
        data = body.encode()
        self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def log_message(self, *a):
        return


def _engine_health(metrics):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Llama)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    w = worker("w1")
    object.__setattr__(w, "endpoint", f"http://127.0.0.1:{server.server_address[1]}")
    object.__setattr__(w, "engine", "llama.cpp")
    object.__setattr__(w, "pool", "lead")
    return server, w, HealthManager(CapabilityRegistry([w]), {}, metrics)


# ----------------------------------------------------------------------------------------------- the contract
def test_a_fresh_registry_is_valid_exposition():
    validate_exposition(MetricsRegistry().render_prometheus_text())


def test_a_populated_registry_is_valid_exposition_and_engine_series_carry_stable_labels():
    metrics = MetricsRegistry()
    server, w, health = _engine_health(metrics)
    try:
        health.collect_all_engine_stats()
        metrics.http_requests_total.inc(route="health", method="GET", status_class="2xx")
        metrics.inference_completions_total.inc(worker_id="w1", outcome="completed", failure_class="none")
        metrics.inference_duration_seconds.observe(3.1, worker_id="w1", model="engineering/b0", pool="lead")
        metrics.inference_prompt_tokens_total.inc(25, worker_id="w1", model="engineering/b0", source="provider")
        types = validate_exposition(metrics.render_prometheus_text())
    finally:
        server.shutdown(); server.server_close()
    assert types["aihost_engine_prompt_tokens_total"] == "counter"          # mirrored counters keep counter semantics
    assert types["aihost_engine_kv_cache_usage_ratio"] == "gauge"
    text = metrics.render_prometheus_text()
    assert 'aihost_engine_requests_running{worker_id="w1",pool="lead",engine="llama.cpp"} 1' in text
    assert 'aihost_engine_prefix_cache_hit_ratio{worker_id="w1",pool="lead",engine="llama.cpp"} 0.9' in text


def test_values_keep_full_precision_so_second_valued_counters_advance_exactly():
    c, g = Counter("x_seconds_total", "h"), Gauge("g", "h")
    c.inc(1234567.891); g.set(0.30000000000000004)
    assert "x_seconds_total 1234567.891" in "\n".join(c.collect())
    assert "g 0.30000000000000004" in "\n".join(g.collect())
    big = Counter("n_total", "h"); big.inc(718216)
    assert "n_total 718216" in "\n".join(big.collect())


def test_a_mirrored_counter_is_typed_counter_and_a_removed_series_disappears():
    m = MirroredCounter("e_tokens_total", "h", ("worker_id",))
    m.set(10, worker_id="a"); m.set(4, worker_id="a")          # an engine restart: the value drops, which is a counter reset
    assert "# TYPE e_tokens_total counter" in "\n".join(m.collect()) and 'e_tokens_total{worker_id="a"} 4' in "\n".join(m.collect())
    m.remove(worker_id="a")
    assert 'worker_id="a"' not in "\n".join(m.collect())


def test_engine_series_are_absent_when_the_engine_does_not_report_them_and_when_the_reading_goes_stale():
    metrics = MetricsRegistry()
    server, w, health = _engine_health(metrics)
    try:
        _Llama.METRICS = "llamacpp:prompt_tokens_total 7\nllamacpp:tokens_predicted_total 3\n"   # no running/waiting/cached series
        health.collect_all_engine_stats()
        text = metrics.render_prometheus_text()
        assert 'aihost_engine_prompt_tokens_total{worker_id="w1",pool="lead",engine="llama.cpp"} 7' in text
        assert "aihost_engine_requests_running{" not in text, "an unreported series must be absent, not zero"
        assert "aihost_engine_prompt_tokens_cached_total{" not in text
        # The reading ages out and the worker stops answering: the series must vanish from the scrape.
        health._engine_stats["w1"]["observed_at"] -= 600
        object.__setattr__(w, "endpoint", "http://127.0.0.1:1")
        health.registry = CapabilityRegistry([w])
        health.collect_all_engine_stats()
        remaining = [l for l in metrics.render_prometheus_text().splitlines() if l.startswith("aihost_engine_")]
        assert remaining == [], f"stale engine series must be removed, still exported: {remaining}"
    finally:
        _Llama.METRICS = ("llamacpp:prompt_tokens_total 1000\nllamacpp:prompt_tokens_cached_total 9000\nllamacpp:prompt_seconds_total 12.5\n"
                          "llamacpp:tokens_predicted_total 400\nllamacpp:tokens_predicted_seconds_total 5.25\nllamacpp:requests_processing 1\nllamacpp:requests_deferred 0\n")
        server.shutdown(); server.server_close()


# ----------------------------------------------------------------------------------------------- accuracy
def test_token_counts_use_the_engines_exact_usage_and_label_estimates():
    out = {"content": "x" * 400, "usage": {"prompt_tokens": 25, "completion_tokens": 260}}
    assert _token_counts(out, 15) == (25, 260, ("provider", "provider"))
    assert _token_counts({"content": "x" * 400}, 15) == (15, 100, ("estimated", "estimated"))
    # a tool-call-only reply still generated tokens: the old estimate (content length only) counted zero
    tool = {"content": "", "tool_calls": [{"function": {"name": "list_dir", "arguments": '{"path":"tests","depth":2}'}}]}
    assert _token_counts(tool, 10)[1] > 0
    # partial usage: use what is exact, estimate the rest, and say which is which
    assert _token_counts({"content": "x" * 40, "usage": {"prompt_tokens": 9}}, 5) == (9, 10, ("provider", "estimated"))
    assert _token_counts({"content": "", "usage": {"prompt_tokens": True, "completion_tokens": -1}}, 5)[2] == ("estimated", "estimated")


def _runtime(adapter, tmp_path):
    metrics = MetricsRegistry()
    w = worker("w1")
    registry = CapabilityRegistry([w])
    return OrchestratorRuntime(registry, {"w1": adapter}, EvidenceStore(tmp_path / "e.jsonl"), metrics=metrics), metrics


def test_a_caller_fault_is_rejected_not_failed_and_a_provider_fault_is_failed(tmp_path):
    body = json.dumps({"error": {"message": "This model's maximum context length is 16384 tokens."}})
    runtime, metrics = _runtime(_CapturingAdapter(ProviderError("provider HTTP 400: " + body, status=400, body=body)), tmp_path)
    runtime.complete({"model": "engineering/w1", "messages": [{"role": "user", "content": "hi"}]})
    assert metrics.inference_completions_total.get(worker_id="w1", outcome="rejected", failure_class="context_length_exceeded") == 1
    assert metrics.inference_completions_total.get(worker_id="w1", outcome="failed", failure_class="provider") == 0
    bad = json.dumps({"error": {"code": 500, "message": "Failed to parse tool call arguments as JSON: x"}})
    runtime, metrics = _runtime(_CapturingAdapter(ProviderError("provider HTTP 500: " + bad, status=500, body=bad)), tmp_path)
    runtime.complete({"model": "engineering/w1", "messages": [{"role": "user", "content": "hi"}]})
    assert metrics.inference_completions_total.get(worker_id="w1", outcome="rejected", failure_class="invalid_request") == 1
    runtime, metrics = _runtime(_CapturingAdapter(ProviderError("provider HTTP 500: boom", status=500, body="boom")), tmp_path)
    runtime.complete({"model": "engineering/w1", "messages": [{"role": "user", "content": "hi"}]})
    assert metrics.inference_completions_total.get(worker_id="w1", outcome="failed", failure_class="provider") == 1
    assert metrics.inference_completions_total.get(worker_id="w1", outcome="rejected", failure_class="invalid_request") == 0
    validate_exposition(metrics.render_prometheus_text())


def test_in_flight_and_max_concurrency_are_exported_and_inflight_returns_to_zero(tmp_path):
    seen = {}

    class Probe:
        def complete(self, request, timeout):
            seen["during"] = runtime.metrics.worker_inflight.get(worker_id="w1")
            return {"content": "ok", "tool_calls": [], "usage": {"prompt_tokens": 3, "completion_tokens": 1}}

    runtime, metrics = _runtime(Probe(), tmp_path)
    runtime.complete({"model": "engineering/w1", "messages": [{"role": "user", "content": "hi"}]})
    assert seen["during"] == 1
    assert metrics.worker_inflight.get(worker_id="w1") == 0
    assert metrics.worker_max_concurrency.get(worker_id="w1") == worker("w1").max_concurrency
    assert metrics.inference_prompt_tokens_total.get(worker_id="w1", model="engineering/w1", source="provider") == 3
    assert metrics.inference_completion_tokens_total.get(worker_id="w1", model="engineering/w1", source="provider") == 1
    validate_exposition(metrics.render_prometheus_text())


def test_the_validator_rejects_the_defects_the_old_host_exporter_had():
    import pytest

    duplicated = ('# HELP aihost_gpu_temperature_celsius t\n# TYPE aihost_gpu_temperature_celsius gauge\n'
                  'aihost_gpu_temperature_celsius{device="hwmon4/xe"} 28\naihost_gpu_temperature_celsius{device="hwmon4/xe"} 30\n')
    with pytest.raises(AssertionError, match="duplicate series"):
        validate_exposition(duplicated)
    mixed = ('# HELP t t\n# TYPE t gauge\nt{device="a"} 1\nt 2\n')
    with pytest.raises(AssertionError, match="inconsistent label names"):
        validate_exposition(mixed)
    with pytest.raises(AssertionError, match="must end with _total"):
        validate_exposition("# HELP c c\n# TYPE c counter\nc 1\n")
    with pytest.raises(AssertionError, match="cumulative"):
        validate_exposition('# HELP h h\n# TYPE h histogram\nh_bucket{le="1"} 5\nh_bucket{le="+Inf"} 3\nh_sum 1\nh_count 3\n')
    with pytest.raises(AssertionError, match="newline"):
        validate_exposition("# HELP g g\n# TYPE g gauge\ng 1")


def test_worker_info_joins_a_worker_to_its_gpu_and_model():
    metrics = MetricsRegistry()
    server, w, health = _engine_health(metrics)
    try:
        health.collect_all_engine_stats()
    finally:
        server.shutdown(); server.server_close()
    text = metrics.render_prometheus_text()
    validate_exposition(text)
    line = next(l for l in text.splitlines() if l.startswith("aihost_worker_info{"))
    assert 'worker_id="w1"' in line and 'pool="lead"' in line and 'engine="llama.cpp"' in line and line.endswith(" 1")
    assert re.search(r'gpu="[^"]+"', line)
