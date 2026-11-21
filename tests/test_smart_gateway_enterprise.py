"""Tests for enterprise smart gateway capabilities:
- Dual-level Circuit Breakers (per-worker and per-pool) with fast failover
- Prompt Complexity Analysis & Tier-based Routing
- EWMA Latency-Aware Routing
- Cost-Optimized Routing
- Asynchronous ASGI Gateway & SSE Streaming
"""
from __future__ import annotations

import json
import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")
import httpx
from starlette.testclient import TestClient

from orchestrator_gateway import AsgiServerWrapper, create_asgi_gateway
from orchestrator_runtime import (
    CapabilityRegistry,
    CircuitBreaker,
    CircuitBreakerRegistry,
    CircuitState,
    CostModel,
    EvidenceStore,
    InMemoryAdapter,
    LatencyTracker,
    OrchestratorRuntime,
    PromptComplexityAnalyzer,
    Router,
    RouteRule,
)
from orchestrator_runtime.smart_router import ComplexityReport, QualityModel, preferred_pool_bands
from tests.test_orchestrator_runtime import worker


class FlakyAdapter:
    """Simulates an upstream adapter that fails or succeeds on demand."""

    def __init__(self, content: str = "ok"):
        self.content = content
        self.fail = False

    def complete(self, request, timeout, cancel=None, on_stream_start=None, on_stream_chunk=None):
        if self.fail:
            from orchestrator_runtime import ProviderError
            raise ProviderError("upstream service error 500", status=500, body="500 Internal Error")
        return {"content": self.content, "tool_calls": []}


class StreamingMockAdapter:
    supports_streaming = True

    def __init__(self, tokens: list[str]):
        self.tokens = tokens

    def complete(self, request, timeout, cancel=None, on_stream_start=None, on_stream_chunk=None):
        if on_stream_start:
            on_stream_start()
        if on_stream_chunk:
            for tok in self.tokens:
                on_stream_chunk({"choices": [{"index": 0, "delta": {"content": tok}, "finish_reason": None}]})
        return {"content": "".join(self.tokens), "tool_calls": [], "provider_finish_reason": "stop"}


# =====================================================================
# 1. Circuit Breaker Unit & Failover Tests
# =====================================================================

def test_circuit_breaker_state_transitions():
    cb = CircuitBreaker("worker:test", failure_threshold=3, recovery_timeout=0.2, half_open_probes_required=2)
    assert cb.state == CircuitState.CLOSED
    assert cb.allow_request() is True

    # Record failures
    cb.record_failure("error 1")
    cb.record_failure("error 2")
    assert cb.state == CircuitState.CLOSED

    # 3rd failure trips to OPEN
    cb.record_failure("error 3")
    assert cb.state == CircuitState.OPEN
    assert cb.allow_request() is False

    # Wait for recovery timeout
    import time
    time.sleep(0.25)

    # Now should transition to HALF_OPEN on next check
    assert cb.allow_request() is True
    assert cb.state == CircuitState.HALF_OPEN

    # 1 successful probe keeps it HALF_OPEN
    cb.record_success()
    assert cb.state == CircuitState.HALF_OPEN

    # 2nd successful probe resets it to CLOSED
    cb.record_success()
    assert cb.state == CircuitState.CLOSED
    assert cb.allow_request() is True


def test_circuit_breaker_fast_failover_to_fallback(tmp_path):
    lead = worker("lead1"); aux = worker("aux1")
    object.__setattr__(lead, "pool", "lead"); object.__setattr__(aux, "pool", "aux")
    lead_adapter = FlakyAdapter("from-lead")
    aux_adapter = FlakyAdapter("from-aux")

    rules = [
        {"id": "default", "match": {}, "pool": "lead", "fallback": ["aux"]},
    ]
    cb_registry = CircuitBreakerRegistry(worker_failure_threshold=2, pool_failure_threshold=2)
    router = Router.from_config(rules, circuit_breakers=cb_registry)

    runtime = OrchestratorRuntime(
        CapabilityRegistry([lead, aux]),
        {"lead1": lead_adapter, "aux1": aux_adapter},
        EvidenceStore(tmp_path / "evidence.jsonl"),
        router=router,
    )
    runtime.circuit_breakers = cb_registry

    # 1. Normal request routes to lead
    req = {"model": "engineering/lead", "messages": [{"role": "user", "content": "hi"}]}
    res1 = runtime.complete(req)
    assert res1["status"] == "ok"
    assert res1["route"]["pool"] == "lead"
    assert res1["route"]["worker_id"] == "lead1"

    # 2. Trip lead pool circuit breaker by recording failures
    cb_registry.record_failure("lead1", pool_name="lead", error="500 Internal Error")
    cb_registry.record_failure("lead1", pool_name="lead", error="500 Internal Error")
    assert not cb_registry.is_pool_available("lead")

    # 3. Router should now immediately fast-failover to aux without even touching lead!
    res2 = runtime.complete(req)
    assert res2["status"] == "ok"
    assert res2["route"]["pool"] == "aux"
    assert res2["route"]["worker_id"] == "aux1"
    assert "circuit breaker open; fast failover to 'aux'" in res2["route"]["reason"]


# =====================================================================
# 2. Complexity Analysis & Tier-Based Routing Tests
# =====================================================================

def test_prompt_complexity_analysis():
    # Simple prompt
    simple_req = {"messages": [{"role": "user", "content": "What is the capital of France?"}]}
    rep_simple = PromptComplexityAnalyzer.analyze(simple_req, prompt_tokens=15)
    assert rep_simple.tier == "simple"
    assert rep_simple.score < 0.30

    # Complex coding prompt with tools and code blocks
    complex_req = {
        "messages": [
            {"role": "system", "content": "Analyze root cause and refactor concurrency deadlock."},
            {"role": "user", "content": "```python\ndef solve():\n    import threading\n    # deadlock\n```"},
        ],
        "tools": [{"type": "function", "function": {"name": "run_test"}}, {"type": "function", "function": {"name": "patch_file"}}],
    }
    rep_complex = PromptComplexityAnalyzer.analyze(complex_req, prompt_tokens=2500)
    assert rep_complex.tier in ("medium", "complex")
    assert rep_complex.score > 0.35


def test_router_matches_on_complexity_tier(tmp_path):
    lead = worker("lead1"); deep = worker("deep1")
    object.__setattr__(lead, "pool", "lead"); object.__setattr__(deep, "pool", "deep")

    rules = [
        {"id": "complex-rule", "match": {"complexity_tier": ["complex"]}, "pool": "deep"},
        {"id": "default", "match": {}, "pool": "lead"},
    ]
    router = Router.from_config(rules)

    # Simple request routes to lead
    dec_simple = router.decide(
        model="engineering/default",
        task_class=None,
        has_tools=False,
        prompt_tokens=20,
        complexity_score=0.15,
    )
    assert dec_simple.rule_id == "default"
    assert dec_simple.pool == "lead"

    # Complex request routes to deep
    dec_complex = router.decide(
        model="engineering/default",
        task_class=None,
        has_tools=True,
        prompt_tokens=4000,
        complexity_score=0.85,
    )
    assert dec_complex.rule_id == "complex-rule"
    assert dec_complex.pool == "deep"


# =====================================================================
# 3. EWMA Latency & Cost Optimization Routing Tests
# =====================================================================

def test_least_latency_routing_strategy():
    rules = [
        {"id": "latency-opt", "match": {}, "pool": "lead", "fallback": ["aux"], "strategy": "least_latency"},
    ]
    latency_tracker = LatencyTracker(alpha=0.5)
    # Simulate lead is slow (1500ms) and aux is fast (200ms)
    latency_tracker.record("lead1", "lead", duration=1.5)
    latency_tracker.record("aux1", "aux", duration=0.2)

    router = Router.from_config(rules, latency_tracker=latency_tracker)
    decision = router.decide(model="test", task_class=None, has_tools=False, prompt_tokens=100)
    # Target pool should switch to aux because aux has much lower EWMA latency
    assert decision.pool == "aux"
    assert "optimized for least latency" in decision.reason


def test_cost_optimized_routing_strategy():
    rules = [
        {"id": "cost-opt", "match": {}, "pool": "deep", "fallback": ["lead"], "strategy": "cost_optimized"},
    ]
    cost_model = CostModel({"lead": 1.0, "deep": 4.0})
    router = Router.from_config(rules, cost_model=cost_model)

    # For a simple task, cost optimization prefers the cheaper lead pool over deep
    decision = router.decide(
        model="test",
        task_class=None,
        has_tools=False,
        prompt_tokens=50,
        complexity_score=0.10,
    )
    assert decision.pool == "lead"
    assert "optimized for cost" in decision.reason


# =====================================================================
# 4. Asynchronous Starlette ASGI Gateway Tests
# =====================================================================

def test_asgi_gateway_endpoints_and_streaming(tmp_path):
    w1 = worker("w1")
    stream_tokens = ["Hello", " world", "!"]
    runtime = OrchestratorRuntime(
        CapabilityRegistry([w1]),
        {"w1": StreamingMockAdapter(stream_tokens)},
        EvidenceStore(tmp_path / "evidence.jsonl"),
    )
    app = create_asgi_gateway(runtime, "test-secret-token")
    client = TestClient(app)

    # 1. GET /health
    resp_health = client.get("/health")
    assert resp_health.status_code == 200
    assert resp_health.json()["status"] == "healthy"

    # 2. GET /metrics
    resp_metrics = client.get("/metrics")
    assert resp_metrics.status_code == 200
    assert "aihost_http_requests_total" in resp_metrics.text

    # 3. GET /v1/models (requires auth)
    resp_unauth = client.get("/v1/models")
    assert resp_unauth.status_code == 401

    resp_models = client.get("/v1/models", headers={"Authorization": "Bearer test-secret-token"})
    assert resp_models.status_code == 200
    assert resp_models.json()["object"] == "list"

    # 4. POST /v1/chat/completions (streaming SSE)
    stream_payload = {
        "model": "engineering/w1",
        "messages": [{"role": "user", "content": "Say hello"}],
        "stream": True,
    }
    resp_stream = client.post(
        "/v1/chat/completions",
        json=stream_payload,
        headers={"Authorization": "Bearer test-secret-token"},
    )
    assert resp_stream.status_code == 200
    assert "text/event-stream" in resp_stream.headers["Content-Type"]
    lines = [line.strip() for line in resp_stream.text.split("\n") if line.strip()]
    data_lines = [json.loads(line.removeprefix("data: ")) for line in lines if line.startswith("data: {")]
    assert len(data_lines) >= 3
    assert data_lines[-1]["choices"][0]["finish_reason"] == "stop"
    assert any(line == "data: [DONE]" for line in lines)


def test_asgi_server_wrapper_lifecycle(tmp_path):
    import time
    import urllib.request

    w1 = worker("w1")
    runtime = OrchestratorRuntime(
        CapabilityRegistry([w1]),
        {"w1": InMemoryAdapter("hello")},
        EvidenceStore(tmp_path / "evidence.jsonl"),
    )
    app = create_asgi_gateway(runtime, "test-secret-token")
    wrapper = AsgiServerWrapper(app, "127.0.0.1", 0, log_level="error")

    import threading
    thread = threading.Thread(target=wrapper.serve_forever, daemon=True)
    thread.start()

    deadline = time.monotonic() + 5.0
    while not wrapper.server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert wrapper.server.started

    try:
        port = wrapper.server.servers[0].sockets[0].getsockname()[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert data["status"] == "healthy"
    finally:
        wrapper.shutdown()
        thread.join(timeout=3.0)
        assert not thread.is_alive()


def test_asgi_server_wrapper_ssl_config():
    import ssl
    wrapper = AsgiServerWrapper(
        None, "0.0.0.0", 8443,
        ssl_keyfile="/path/to/key.pem",
        ssl_certfile="/path/to/cert.pem",
    )
    assert wrapper.config.ssl_keyfile == "/path/to/key.pem"
    assert wrapper.config.ssl_certfile == "/path/to/cert.pem"
    assert wrapper.config.ssl_cert_reqs == ssl.CERT_NONE


# =====================================================================
# quality_first auto routing (engineering/auto)
# =====================================================================

AUTO_RULES = [
    {
        "id": "engineering-auto",
        "match": {"model": ["engineering/auto"]},
        "pool": "lead",
        "fallback": ["deep", "rocm"],
        "strategy": "quality_first",
        "fallback_on_saturation": True,
        "reasoning": {"mode": "off", "answer_allowance": 8192},
    },
    {"id": "default", "match": {}, "pool": "lead", "fallback": ["deep"]},
]
AUTO_ALIASES = {
    "engineering/lead": {"pool": "lead", "reasoning": {"mode": "off", "answer_allowance": 8192}},
    "engineering/deep": {"pool": "deep", "reasoning": {"mode": "on", "budget": 4096, "answer_allowance": 8192}},
    "engineering/interactive-rocm": {"pool": "rocm", "reasoning": {"mode": "off", "answer_allowance": 8192}},
}


def test_quality_first_strategy_is_accepted():
    Router.from_config(AUTO_RULES, AUTO_ALIASES)


def test_omitted_model_normalizes_to_engineering_auto():
    router = Router.from_config(AUTO_RULES, AUTO_ALIASES)
    d = router.decide(model=None, task_class=None, has_tools=False, prompt_tokens=20,
                      request={"messages": [{"role": "user", "content": "hi"}]})
    assert d.rule_id == "engineering-auto"


def test_quality_first_prefers_deep_for_complex_reasoning():
    router = Router.from_config(AUTO_RULES, AUTO_ALIASES)
    req = {"messages": [{"role": "user", "content": "step-by-step analyze root cause of this architecture deadlock"}]}
    d = router.decide(model="engineering/auto", task_class=None, has_tools=False, prompt_tokens=800, request=req)
    assert d.pool == "deep"
    # deep is alone in the top band; the remaining peers follow in quality order (rocm 2.5 > lead 2.0)
    assert d.fallback == ("rocm", "lead")
    assert "quality_first" in d.reason


COMPLEX_REQ = {"messages": [{"role": "user", "content": "step-by-step analyze root cause of this architecture deadlock"}]}
CODE_TOOLS_REQ = {
    "messages": [{"role": "user", "content": "```python\ndef foo():\n    pass\n``` fix this function"}],
    "tools": [{"type": "function", "function": {"name": "read_file", "parameters": {}}}],
}


def test_quality_first_deep_selection_uses_deep_reasoning_policy():
    router = Router.from_config(AUTO_RULES, AUTO_ALIASES)
    d = router.decide(model="engineering/auto", task_class=None, has_tools=False, prompt_tokens=800, request=COMPLEX_REQ)
    assert d.pool == "deep"
    assert d.policy.mode == "on"
    assert d.policy.budget == 4096
    assert d.policy.answer_allowance == 8192
    assert d.policy == router.alias_specs["engineering/deep"].policy


def test_quality_first_lead_and_rocm_selection_keep_reasoning_off():
    router = Router.from_config(AUTO_RULES, AUTO_ALIASES)
    rocm = router.decide(model="engineering/auto", task_class=None, has_tools=True, prompt_tokens=400, request=CODE_TOOLS_REQ)
    assert rocm.pool == "rocm"
    assert rocm.policy.mode == "off" and rocm.policy.answer_allowance == 8192
    lead = router.decide(model="engineering/auto", task_class=None, has_tools=False, prompt_tokens=5,
                         request={"messages": [{"role": "user", "content": "hi"}]})
    assert lead.pool == "lead"
    assert lead.policy.mode == "off" and lead.policy.answer_allowance == 8192


def test_quality_first_failover_off_deep_drops_deep_reasoning_policy():
    cbs = CircuitBreakerRegistry(worker_failure_threshold=2, pool_failure_threshold=2)
    router = Router.from_config(AUTO_RULES, AUTO_ALIASES, circuit_breakers=cbs)
    cbs.record_failure("deep1", pool_name="deep", error="500")
    cbs.record_failure("deep1", pool_name="deep", error="500")
    d = router.decide(model="engineering/auto", task_class=None, has_tools=False, prompt_tokens=800, request=COMPLEX_REQ)
    assert d.pool in ("lead", "rocm")
    assert d.policy.mode == "off"


def test_pool_bands_encode_fit_classes():
    complex_report = ComplexityReport(score=0.9, tier="complex")
    assert preferred_pool_bands(complex_report, has_tools=False) == [["deep"], ["lead", "rocm"]]
    assert preferred_pool_bands(complex_report, has_tools=True) == [["deep"], ["lead", "rocm"]]
    assert preferred_pool_bands(ComplexityReport(score=0.5, tier="medium"), has_tools=True) == [["rocm", "lead"], ["deep"]]
    assert preferred_pool_bands(ComplexityReport(score=0.1, tier="simple"), has_tools=False) == [["lead"], ["rocm"], ["deep"]]
    assert preferred_pool_bands(None, has_tools=False) == [["lead"], ["rocm"], ["deep"]]


def test_quality_weights_reorder_peers_within_a_band():
    # Default weights: rocm 2.5 > lead 2.0 so code+tools prefers rocm; an operator retune flips it.
    retuned = Router.from_config(AUTO_RULES, AUTO_ALIASES, quality_model=QualityModel({"rocm": 1.0}))
    d = retuned.decide(model="engineering/auto", task_class=None, has_tools=True, prompt_tokens=400, request=CODE_TOOLS_REQ)
    assert d.pool == "lead"
    assert d.fallback == ("rocm", "deep")
    default = Router.from_config(AUTO_RULES, AUTO_ALIASES)
    d = default.decide(model="engineering/auto", task_class=None, has_tools=True, prompt_tokens=400, request=CODE_TOOLS_REQ)
    assert d.pool == "rocm"
    assert d.fallback == ("lead", "deep")


def test_quality_weights_reorder_fallbacks_of_complex_requests():
    router = Router.from_config(AUTO_RULES, AUTO_ALIASES, quality_model=QualityModel({"lead": 9.0}))
    d = router.decide(model="engineering/auto", task_class=None, has_tools=False, prompt_tokens=800, request=COMPLEX_REQ)
    assert d.pool == "deep"
    assert d.fallback == ("lead", "rocm")


def test_quality_weights_never_override_fit_band():
    # Even an extreme weight on deep cannot pull it ahead of the code/tools band, nor a tiny one demote it for complex.
    boosted = Router.from_config(AUTO_RULES, AUTO_ALIASES, quality_model=QualityModel({"deep": 100.0}))
    d = boosted.decide(model="engineering/auto", task_class=None, has_tools=True, prompt_tokens=400, request=CODE_TOOLS_REQ)
    assert d.pool == "rocm"
    assert d.fallback[-1] == "deep"
    demoted = Router.from_config(AUTO_RULES, AUTO_ALIASES, quality_model=QualityModel({"deep": 0.1}))
    d = demoted.decide(model="engineering/auto", task_class=None, has_tools=False, prompt_tokens=800, request=COMPLEX_REQ)
    assert d.pool == "deep"


def test_quality_first_latency_breaks_equal_quality_ties_within_band():
    tracker = LatencyTracker()
    tracker.record("w-lead", "lead", 0.5)
    tracker.record("w-rocm", "rocm", 2.0)
    router = Router.from_config(AUTO_RULES, AUTO_ALIASES, latency_tracker=tracker,
                                quality_model=QualityModel({"rocm": 2.0}))
    d = router.decide(model="engineering/auto", task_class=None, has_tools=True, prompt_tokens=400, request=CODE_TOOLS_REQ)
    assert d.pool == "lead"


def test_quality_first_prefers_rocm_for_code_tools():
    router = Router.from_config(AUTO_RULES, AUTO_ALIASES)
    req = {
        "messages": [{"role": "user", "content": "```python\ndef foo():\n    pass\n``` fix this function"}],
        "tools": [{"type": "function", "function": {"name": "read_file", "parameters": {}}}],
    }
    d = router.decide(model="engineering/auto", task_class=None, has_tools=True, prompt_tokens=400, request=req)
    assert d.pool == "rocm"
    assert "lead" in d.fallback and "deep" in d.fallback


def test_quality_first_prefers_lead_for_simple():
    router = Router.from_config(AUTO_RULES, AUTO_ALIASES)
    req = {"messages": [{"role": "user", "content": "hi"}]}
    d = router.decide(model="engineering/auto", task_class=None, has_tools=False, prompt_tokens=5, request=req)
    assert d.pool == "lead"


def test_quality_first_skips_open_circuit_breaker_then_failover_order():
    cbs = CircuitBreakerRegistry(worker_failure_threshold=2, pool_failure_threshold=2)
    router = Router.from_config(AUTO_RULES, AUTO_ALIASES, circuit_breakers=cbs)
    cbs.record_failure("deep1", pool_name="deep", error="500")
    cbs.record_failure("deep1", pool_name="deep", error="500")
    assert not cbs.is_pool_available("deep")
    req = {"messages": [{"role": "user", "content": "step-by-step analyze root cause architecture"}]}
    d = router.decide(model="engineering/auto", task_class=None, has_tools=False, prompt_tokens=800, request=req)
    assert d.pool != "deep"
    assert d.pool in ("lead", "rocm")
    assert "deep" in d.fallback


def test_pin_aliases_still_bypass_quality_first():
    router = Router.from_config(AUTO_RULES, AUTO_ALIASES)
    d = router.decide(model="engineering/interactive-rocm", task_class=None, has_tools=False, prompt_tokens=5)
    assert d.rule_id == "alias:engineering/interactive-rocm"
    assert d.pool == "rocm"
    assert d.fallback == ()


def test_unknown_model_does_not_use_engineering_auto_rule():
    router = Router.from_config(AUTO_RULES, AUTO_ALIASES)
    d = router.decide(model="engineering/other", task_class=None, has_tools=False, prompt_tokens=5,
                      request={"messages": [{"role": "user", "content": "hi"}]})
    assert d.rule_id == "default"
    assert d.pool == "lead"
    assert "rocm" not in d.fallback

