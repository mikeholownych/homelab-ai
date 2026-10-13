"""Tests for deterministic response caching in orchestrator runtime."""
from __future__ import annotations

import time
import pytest

from orchestrator_runtime import (
    CapabilityRegistry,
    EvidenceStore,
    InMemoryAdapter,
    OrchestratorRuntime,
    ResponseCache,
)
from tests.test_orchestrator_runtime import worker


def test_response_cache_is_cacheable():
    cache = ResponseCache()

    # Temperature 0 is cacheable
    assert cache.is_cacheable({"model": "test", "messages": [{"role": "user", "content": "hi"}], "temperature": 0})
    assert cache.is_cacheable({"model": "test", "messages": [{"role": "user", "content": "hi"}], "temperature": 0.0})

    # Explicit cache flag is cacheable
    assert cache.is_cacheable({"model": "test", "messages": [{"role": "user", "content": "hi"}], "cache": True})

    # High temperature is not cacheable by default
    assert not cache.is_cacheable({"model": "test", "messages": [{"role": "user", "content": "hi"}], "temperature": 0.8})

    # Streaming is not cacheable
    assert not cache.is_cacheable({"model": "test", "messages": [{"role": "user", "content": "hi"}], "temperature": 0, "stream": True})

    # Cache-Control no-cache bypasses
    assert not cache.is_cacheable(
        {"model": "test", "messages": [{"role": "user", "content": "hi"}], "temperature": 0},
        headers={"Cache-Control": "no-cache"},
    )


def test_response_cache_lru_and_ttl():
    cache = ResponseCache(max_entries=2, default_ttl=0.1)
    k1 = "key1"
    k2 = "key2"
    k3 = "key3"

    cache.set(k1, {"content": "resp1"})
    cache.set(k2, {"content": "resp2"})
    assert cache.size() == 2

    # Access k1 to make it most recently used
    assert cache.get(k1) is not None

    # Inserting k3 should evict k2 (LRU)
    cache.set(k3, {"content": "resp3"})
    assert cache.size() == 2
    assert cache.get(k2) is None
    assert cache.get(k1) is not None
    assert cache.get(k3) is not None

    # Test TTL expiration
    time.sleep(0.12)
    assert cache.get(k1) is None
    assert cache.get(k3) is None
    assert cache.size() == 0


def test_orchestrator_runtime_cache_end_to_end(tmp_path):
    w1 = worker("w1")
    call_count = 0

    class CountingAdapter:
        supports_cancel = False
        supports_streaming = False

        def complete(self, request, timeout, **kwargs):
            nonlocal call_count
            call_count += 1
            return {
                "content": f"result-{call_count}",
                "tool_calls": [],
                "provider_status": 200,
                "provider_finish_reason": "stop",
            }

    adapter = CountingAdapter()
    runtime = OrchestratorRuntime(
        CapabilityRegistry([w1]),
        {"w1": adapter},
        EvidenceStore(tmp_path / "evidence.jsonl"),
        cache=ResponseCache(max_entries=50, default_ttl=3600.0),
    )

    req_deterministic = {
        "model": "engineering/w1",
        "messages": [{"role": "user", "content": "deterministic question"}],
        "temperature": 0,
    }

    # 1. First invocation: Cache MISS -> adapter called
    res1 = runtime.complete(req_deterministic)
    assert res1["status"] == "ok"
    assert call_count == 1
    assert res1["headers"]["X-AIHost-Cache"] == "MISS"
    content1 = res1["response"]["choices"][0]["message"]["content"]
    assert content1 == "result-1"

    # 2. Second identical invocation: Cache HIT -> adapter NOT called again!
    res2 = runtime.complete(req_deterministic)
    assert res2["status"] == "ok"
    assert call_count == 1  # Still 1! Zero GPU / adapter calls!
    assert res2["headers"]["X-AIHost-Cache"] == "HIT"
    content2 = res2["response"]["choices"][0]["message"]["content"]
    assert content2 == "result-1"
    assert res2["cached"] is True

    # 3. Third invocation with temperature > 0: Cache BYPASS -> adapter called
    req_stochastic = {
        "model": "engineering/w1",
        "messages": [{"role": "user", "content": "deterministic question"}],
        "temperature": 0.7,
    }
    res3 = runtime.complete(req_stochastic)
    assert res3["status"] == "ok"
    assert call_count == 2
    assert res3["headers"]["X-AIHost-Cache"] == "BYPASS"
    content3 = res3["response"]["choices"][0]["message"]["content"]
    assert content3 == "result-2"
