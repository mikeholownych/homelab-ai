"""Regressions from the October 21 physical qualification; no GPU required."""
import copy
import json
import threading
from dataclasses import replace
from http.client import HTTPConnection

import pytest

from orchestrator_runtime import CapabilityRegistry, Client, EvidenceStore, OrchestratorRuntime, ResponseCache
from tests.test_orchestrator_runtime import worker


def request():
    return {"model": "engineering/w1", "messages": [{"role": "user", "content": "Return x == y."}],
            "temperature": 0, "max_tokens": 64}


class Adapter:
    supports_cancel = False
    supports_streaming = False

    def __init__(self):
        self.calls = 0
        self.timeouts = 0

    def complete(self, request, timeout, **kwargs):
        self.calls += 1
        if self.timeouts:
            self.timeouts -= 1
            raise TimeoutError("request budget exhausted")
        return {"content": f"result-{self.calls}", "tool_calls": [], "provider_finish_reason": "stop"}


def runtime(tmp_path):
    adapter = Adapter()
    return OrchestratorRuntime(CapabilityRegistry([worker("w1")]), {"w1": adapter},
                               EvidenceStore(tmp_path / "evidence.jsonl")), adapter


@pytest.mark.parametrize("field,value", [
    ("max_tokens", 32), ("max_completion_tokens", 32), ("temperature", 0.00001),
    ("response_format", {"type": "json_object"}), ("tool_choice", "none"),
    ("parallel_tool_calls", False), ("stop", ["STOP"]), ("seed", 42),
    ("top_p", 0.8), ("logit_bias", {"123": -100}), ("future_sampling_control", 1),
    ("reasoning_effort", "high"),
])
def test_cache_keys_include_every_response_control(field, value):
    cache = ResponseCache()
    original = request()
    changed = {**original, field: value}
    assert cache.compute_key(original) != cache.compute_key(changed)


@pytest.mark.parametrize("content", ["Return x != y.", "return X == Y.", "Do not return x == y."])
def test_similar_text_never_substitutes_an_answer(content):
    cache = ResponseCache(semantic_enabled=True, semantic_threshold=0.5)
    original = request()
    cache.set(cache.compute_key(original), {"content": "original"}, request=original)
    changed = copy.deepcopy(original)
    changed["messages"][0]["content"] = content
    assert cache.get_semantic(changed) == (None, 0.0)


def test_identical_runtime_request_hits_but_controls_and_headers_bypass(tmp_path):
    rt, adapter = runtime(tmp_path)
    assert rt.complete(request())["headers"]["X-AIHost-Cache"] == "MISS"
    assert rt.complete(request())["headers"]["X-AIHost-Cache"] == "HIT"
    assert rt.complete({**request(), "max_tokens": 32})["headers"]["X-AIHost-Cache"] == "MISS"
    assert rt.complete(request(), cache_headers={"cache-control": "no-store"})["headers"]["X-AIHost-Cache"] == "BYPASS"
    assert rt.complete(request(), cache_headers={"x-aihost-cache": "bypass"})["headers"]["X-AIHost-Cache"] == "BYPASS"
    assert rt.complete({**request(), "cache": False})["headers"]["X-AIHost-Cache"] == "BYPASS"
    assert adapter.calls == 5


def test_cache_isolates_clients_and_runtime_artifact_changes(tmp_path):
    rt, adapter = runtime(tmp_path)
    alice = Client("alice", "fixture", frozenset({"workload"}))
    bob = replace(alice, client_id="bob")
    assert rt.complete(request(), client=alice)["headers"]["X-AIHost-Cache"] == "MISS"
    assert rt.complete(request(), client=bob)["headers"]["X-AIHost-Cache"] == "MISS"
    assert rt.complete(request(), client=alice)["headers"]["X-AIHost-Cache"] == "HIT"
    rt.registry.register(replace(worker("w1"), runtime_image_digest="sha256:" + "d" * 64))
    assert rt.complete(request(), client=alice)["headers"]["X-AIHost-Cache"] == "MISS"
    assert adapter.calls == 3


def test_hot_reload_invalidates_cached_policy_results(tmp_path):
    rt, adapter = runtime(tmp_path)
    assert rt.complete(request())["headers"]["X-AIHost-Cache"] == "MISS"
    assert rt.complete(request())["headers"]["X-AIHost-Cache"] == "HIT"
    rt.reload_config()
    assert rt.complete(request())["headers"]["X-AIHost-Cache"] == "MISS"
    assert adapter.calls == 2


def test_request_timeouts_do_not_demote_health_trip_breakers_or_replay(tmp_path):
    rt, adapter = runtime(tmp_path)
    adapter.timeouts = 6  # Exceeds the worker circuit-breaker threshold.
    before = rt.health._states["w1"]
    for _ in range(6):
        result = rt.complete({**request(), "cache": False})
        assert result["failure_class"] == "timeout"
        assert rt.registry.snapshot()[0]["healthy"]
        assert rt.health._states["w1"] is before  # Neither false failure nor fabricated success.
        assert rt.circuit_breakers.is_worker_available("w1")
    assert adapter.calls == 6
    assert rt.metrics.provider_errors_total.get(worker_id="w1", error_type="timeout") == 6
    assert rt.complete({**request(), "cache": False})["status"] == "ok"
    assert adapter.calls == 7


def test_independent_failure_observation_still_blocks_dispatch(tmp_path):
    rt, adapter = runtime(tmp_path)
    rt.health.record_worker_observation("w1", healthy=False, error="probe_connection_refused")
    result = rt.complete(request())
    assert result["status"] != "ok"
    assert adapter.calls == 0
    rt.health.record_worker_observation("w1", healthy=True)
    assert rt.complete(request())["status"] == "ok"


@pytest.mark.parametrize("transport", ["sync", "asgi"])
def test_http_bypass_reaches_runtime_even_when_a_response_is_cached(tmp_path, transport):
    from orchestrator_gateway import GatewayServer, create_gateway

    rt, adapter = runtime(tmp_path)
    headers = {"Authorization": "Bearer fixture-cache-client", "Content-Type": "application/json"}
    if transport == "asgi":
        pytest.importorskip("starlette")
        pytest.importorskip("httpx")
        from starlette.testclient import TestClient
        from orchestrator_gateway import create_asgi_gateway

        with TestClient(create_asgi_gateway(rt, "fixture-cache-client")) as client:
            first = client.post("/v1/chat/completions", json=request(), headers=headers)
            second = client.post("/v1/chat/completions", json=request(), headers=headers)
            bypass = client.post("/v1/chat/completions", json=request(),
                                 headers={**headers, "cache-control": "no-store"})
            assert [r.status_code for r in [first, second, bypass]] == [200, 200, 200]
            assert [r.headers["X-AIHost-Cache"] for r in [first, second, bypass]] == ["MISS", "HIT", "BYPASS"]
    else:
        server = GatewayServer(("127.0.0.1", 0), create_gateway(rt, "fixture-cache-client"))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            results = []
            for extra in [{}, {}, {"cache-control": "no-store"}]:
                connection = HTTPConnection(*server.server_address, timeout=5)
                connection.request("POST", "/v1/chat/completions", json.dumps(request()), {**headers, **extra})
                response = connection.getresponse()
                response.read()
                results.append((response.status, response.getheader("X-AIHost-Cache")))
                connection.close()
            assert results == [(200, "MISS"), (200, "HIT"), (200, "BYPASS")]
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
    assert adapter.calls == 2
