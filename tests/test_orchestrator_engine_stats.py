from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from orchestrator_runtime import CapabilityRegistry, HealthManager, MetricsRegistry
from orchestrator_runtime.engine_stats import extract, parse_prometheus
from tests.test_orchestrator_runtime import worker

VLLM = """# HELP vllm:num_requests_running running
# TYPE vllm:num_requests_running gauge
vllm:num_requests_running{engine="0",model_name="m"} 1.0
vllm:num_requests_waiting{engine="0",model_name="m"} 0.0
vllm:kv_cache_usage_perc{engine="0",model_name="m"} 0.25
vllm:prompt_tokens_total{engine="0",model_name="m"} 1000.0
vllm:generation_tokens_total{engine="0",model_name="m"} 250.0
vllm:prefix_cache_queries_total{engine="0",model_name="m"} 800.0
vllm:prefix_cache_hits_total{engine="0",model_name="m"} 600.0
vllm:time_to_first_token_seconds_bucket{engine="0",le="0.1"} 5.0
"""
LLAMA = """# TYPE llamacpp:prompt_tokens_total counter
llamacpp:prompt_tokens_total 4096
llamacpp:tokens_predicted_total 512
llamacpp:requests_processing 1
llamacpp:requests_deferred 2
llamacpp:kv_cache_usage_ratio 0.5
"""


def test_vllm_series_are_mapped_to_neutral_names():
    stats = extract("vllm", VLLM)
    assert stats["requests_running"] == 1.0 and stats["requests_waiting"] == 0.0
    assert stats["kv_cache_usage"] == 0.25
    assert (stats["prompt_tokens_total"], stats["generation_tokens_total"]) == (1000.0, 250.0)
    assert stats["prefix_cache_hit_ratio"] == 0.75


def test_llama_series_are_mapped_and_missing_ones_are_unknown_not_zero():
    stats = extract("llama.cpp", LLAMA)
    assert (stats["requests_running"], stats["requests_waiting"], stats["kv_cache_usage"]) == (1, 2, 0.5)
    assert stats["generation_tokens_total"] == 512 and stats["prefix_cache_hit_ratio"] is None
    partial = extract("llama.cpp", "llamacpp:prompt_tokens_total 7\n")
    assert partial["requests_running"] is None and partial["kv_cache_usage"] is None


def test_unknown_engine_or_empty_metrics_yield_nothing():
    assert extract("unknown", VLLM) is None
    assert extract("vllm", "# nothing here\n") is None
    assert extract("llama.cpp", "garbage line\nnot_a_metric{x=\"y\"} NaN\n") is None


def test_parser_sums_labelled_samples_and_ignores_comments():
    assert parse_prometheus('a{x="1"} 2\na{x="2"} 3\n# c\nb 4\n') == {"a": 5.0, "b": 4.0}


class _Engine(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.headers.get("Authorization") != "Bearer sekret-worker-token-123":
            self.send_response(401); self.end_headers(); return
        body = (json.dumps({"data": []}) if self.path == "/v1/models" else LLAMA).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        return


def test_health_publishes_pool_engine_and_stats_without_exposing_credentials():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Engine)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        w = worker("w1")
        object.__setattr__(w, "endpoint", f"http://127.0.0.1:{server.server_address[1]}")
        object.__setattr__(w, "auth_token", "sekret-worker-token-123")
        object.__setattr__(w, "engine", "llama.cpp")
        object.__setattr__(w, "pool", "aux")
        health = HealthManager(CapabilityRegistry([w]), {}, MetricsRegistry())
        assert health.probe_worker("w1") is True
        _, payload = health.check()
        summary = payload["workers"]["w1"]
        assert summary["pool"] == "aux" and summary["engine"] == "llama.cpp"
        assert summary["engine_stats"]["kv_cache_usage"] == 0.5
        assert abs(summary["engine_stats"]["observed_at"] - time.time()) < 5
        assert "sekret-worker-token-123" not in json.dumps(payload)  # credentials are never published
    finally:
        server.shutdown(); server.server_close()


def test_stats_collection_failure_never_changes_health():
    w = worker("w2"); object.__setattr__(w, "engine", "vllm")
    health = HealthManager(CapabilityRegistry([w]), {}, MetricsRegistry())
    _, payload = health.check()
    assert payload["workers"]["w2"]["engine_stats"] is None


def test_stats_refresh_independently_of_health_and_stale_stats_are_not_published():
    from orchestrator_runtime import health as health_module

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Engine)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        w = worker("w3")
        object.__setattr__(w, "endpoint", f"http://127.0.0.1:{server.server_address[1]}")
        object.__setattr__(w, "auth_token", "sekret-worker-token-123")
        object.__setattr__(w, "engine", "llama.cpp")
        hm = HealthManager(CapabilityRegistry([w]), {}, MetricsRegistry())
        hm.collect_all_engine_stats()          # no /v1/models probe involved
        _, payload = hm.check()
        assert payload["workers"]["w3"]["engine_stats"]["requests_waiting"] == 2
        # age the stored observation beyond the publish window: it must disappear, not look current
        hm._engine_stats["w3"]["observed_at"] -= health_module.ENGINE_STATS_MAX_AGE_SECONDS + 1
        _, payload = hm.check()
        assert payload["workers"]["w3"]["engine_stats"] is None
    finally:
        server.shutdown(); server.server_close()


# ----------------------------------------------------------------------------- llama.cpp build 11347 shape
LLAMA_NEW = """llamacpp:prompt_tokens_total 1000
llamacpp:prompt_tokens_cached_total 9000
llamacpp:prompt_seconds_total 12.5
llamacpp:tokens_predicted_total 400
llamacpp:tokens_predicted_seconds_total 5.0
llamacpp:requests_processing 1
llamacpp:requests_deferred 0
"""


def _slot(*, n_ctx=65536, prompt=0, decoded=0, processing=False, processed=0):
    return {"id": 0, "n_ctx": n_ctx, "is_processing": processing, "n_prompt_tokens": prompt,
            "n_prompt_tokens_processed": processed, "next_token": [{"n_decoded": decoded, "n_remain": -1}]}


def test_llama_cached_tokens_drive_prefix_hit_ratio_and_seconds_totals_are_published():
    stats = extract("llama.cpp", LLAMA_NEW)
    assert stats["prefix_cache_hit_ratio"] == 0.9           # 9000 / (9000 + 1000)
    assert stats["prompt_tokens_cached_total"] == 9000 and stats["generation_seconds_total"] == 5.0
    assert stats["kv_cache_usage"] is None                  # this build exposes no KV series: unknown, not zero
    assert extract("llama.cpp", "llamacpp:prompt_tokens_total 7\n")["prefix_cache_hit_ratio"] is None


def test_slots_supply_kv_usage_and_in_flight_tokens_when_metrics_have_no_kv_series():
    idle = extract("llama.cpp", LLAMA_NEW, [_slot(prompt=13107)])
    assert idle["kv_cache_usage"] == 13107 / 65536 and idle["generation_tokens_in_flight"] == 0   # retained context
    busy = extract("llama.cpp", LLAMA_NEW, [_slot(prompt=100, decoded=300, processing=True, processed=23)])
    assert abs(busy["kv_cache_usage"] - 400 / 65536) < 1e-9
    assert (busy["generation_tokens_in_flight"], busy["prompt_tokens_in_flight"]) == (300, 23)


def test_an_engine_kv_series_wins_over_the_slots_estimate_and_bad_slots_are_ignored():
    assert extract("llama.cpp", LLAMA + "", [_slot(prompt=60000)])["kv_cache_usage"] == 0.5
    for bad in (None, [], "x", [{"n_ctx": 0}], [None], [{"n_ctx": 10}, 3]):
        stats = extract("llama.cpp", LLAMA_NEW, bad)
        assert stats["kv_cache_usage"] is None and "generation_tokens_in_flight" not in stats


def test_live_counters_never_go_backwards_within_an_epoch_and_reset_on_engine_restart():
    from orchestrator_runtime.engine_stats import with_live_counters

    def stats(done, flight): return {"generation_tokens_total": done, "generation_tokens_in_flight": flight,
                                     "prompt_tokens_total": 0.0, "prompt_tokens_in_flight": 0.0}
    a = with_live_counters(stats(1000, 300), None);          assert a["generation_tokens_live"] == 1300
    # request finished between the two reads: completed not yet visible, in-flight already gone -> raw sum dips
    b = with_live_counters(stats(1000, 0), a);               assert b["generation_tokens_live"] == 1300
    c = with_live_counters(stats(1420, 0), b);               assert c["generation_tokens_live"] == 1420
    # engine restarted: completed total decreased -> guard resets instead of holding the old high-water mark
    d = with_live_counters(stats(10, 0), c);                 assert d["generation_tokens_live"] == 10
    assert "generation_tokens_live" not in with_live_counters({"generation_tokens_total": 5.0}, None)


class _LlamaWithSlots(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.headers.get("Authorization") != "Bearer sekret-worker-token-123":
            self.send_response(401); self.end_headers(); return
        if self.path == "/slots":
            body = json.dumps([_slot(prompt=200, decoded=50, processing=True, processed=20)])
        elif self.path == "/metrics":
            body = LLAMA_NEW
        else:
            body = json.dumps({"data": []})
        data = body.encode()
        self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def log_message(self, *a):
        return


def test_health_collects_slots_for_llama_cpp_and_publishes_live_fields():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _LlamaWithSlots)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        w = worker("w4")
        object.__setattr__(w, "endpoint", f"http://127.0.0.1:{server.server_address[1]}")
        object.__setattr__(w, "auth_token", "sekret-worker-token-123")
        object.__setattr__(w, "engine", "llama.cpp")
        hm = HealthManager(CapabilityRegistry([w]), {}, MetricsRegistry())
        hm.collect_all_engine_stats()
        hm.collect_all_engine_stats()
        stats = hm.check()[1]["workers"]["w4"]["engine_stats"]
        assert stats["generation_tokens_live"] == 450 and stats["prompt_tokens_live"] == 1020
        assert abs(stats["kv_cache_usage"] - 250 / 65536) < 1e-9 and stats["prefix_cache_hit_ratio"] == 0.9
    finally:
        server.shutdown(); server.server_close()


def test_a_missing_slots_endpoint_leaves_metrics_stats_intact():
    class NoSlots(_LlamaWithSlots):
        def do_GET(self):  # noqa: N802
            if self.path == "/slots":
                self.send_response(404); self.end_headers(); return
            super().do_GET()

    server = ThreadingHTTPServer(("127.0.0.1", 0), NoSlots)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        w = worker("w5")
        object.__setattr__(w, "endpoint", f"http://127.0.0.1:{server.server_address[1]}")
        object.__setattr__(w, "auth_token", "sekret-worker-token-123")
        object.__setattr__(w, "engine", "llama.cpp")
        hm = HealthManager(CapabilityRegistry([w]), {}, MetricsRegistry())
        hm.collect_all_engine_stats()
        stats = hm.check()[1]["workers"]["w5"]["engine_stats"]
        assert stats["generation_tokens_total"] == 400 and stats["kv_cache_usage"] is None
        assert "generation_tokens_live" not in stats
    finally:
        server.shutdown(); server.server_close()
