"""Platform behaviour of the gateway (docs/design/01-03): live capacity, exact sizing, bounded reasoning, admission,
cancellation, escalation, qualification routing, clients, retries, capabilities, outcomes, evidence and graceful stop.

Most tests run the real runtime against tests/fake_llama.py, an HTTP stand-in for llama.cpp.
"""
from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
import threading
import time
from http.client import HTTPConnection

import pytest

from orchestrator_gateway import GatewayServer, create_gateway
from orchestrator_runtime import (
    AdmissionController, CapabilityRegistry, Client, ClientRegistry, EvidenceStore, LlamaCppAdapter,
    OpenAIProviderAdapter, OrchestratorRuntime, Router,
)
from orchestrator_runtime import reasoning as rp
from orchestrator_runtime.clients import token_digest
from orchestrator_runtime.evidence import scrub, verify_lines
from tests.fake_llama import FakeLlama
from tests.test_orchestrator_runtime import worker


@pytest.fixture
def fakes():
    created: list[FakeLlama] = []

    def make(**kw) -> FakeLlama:
        fake = FakeLlama(**kw)
        created.append(fake)
        return fake

    yield make
    for fake in created:
        fake.close()


def llama_worker(worker_id, fake, *, pool="lead", reasoning_budget=None, role="production", model_id=None,
                 inventory_ctx=None, capabilities=("navigation", "tool_call_proposal")):
    return dataclasses.replace(
        worker(worker_id, capabilities=capabilities), endpoint=fake.endpoint, engine="llama.cpp", pool=pool,
        context_limit=inventory_ctx or fake.n_ctx, max_concurrency=fake.slots, model_id=model_id or fake.alias,
        public_model_id=f"engineering/{pool}", reasoning_budget=reasoning_budget, role=role,
    )


def build(tmp_path, workers_and_fakes, *, routes=None, aliases=None, queue_max=8, max_wait=5.0, evidence=None, **kw):
    workers = [w for w, _ in workers_and_fakes]
    adapters = {w.worker_id: OpenAIProviderAdapter(f.endpoint, "", f.alias) for w, f in workers_and_fakes}
    router = Router.from_config(routes, aliases or {}) if routes else None
    return OrchestratorRuntime(
        CapabilityRegistry(workers), adapters, evidence or EvidenceStore(tmp_path / "e.jsonl"), router=router,
        admission=AdmissionController(queue_max=queue_max, max_wait_seconds=max_wait), **kw)


def chat(content="hello world", **extra):
    return {"model": "engineering/lead", "messages": [{"role": "user", "content": content}], **extra}


# ============================================================ engines / capacity (Design 01 sections 1-2)
def test_llama_props_fixture_parses_identity_limits_and_declared_capabilities():
    props = json.load(open("vllm-top/tests/fixtures/llamacpp/props.json"))
    obs = LlamaCppAdapter.parse_props(props)
    assert (obs.engine, obs.ctx_per_slot, obs.slots_total) == ("llama.cpp", 65536, 1)
    assert obs.engine_version == "b11347-5fc4f3c8c" and obs.quantization.startswith("IQ1_M")
    assert obs.declared["tools"] and obs.declared["parallel_tool_calls"] and not obs.declared["vision"]


def test_observed_limits_govern_and_inventory_mismatch_is_evidenced(fakes, tmp_path):
    fake = fakes(n_ctx=2048)
    runtime = build(tmp_path, [(llama_worker("w1", fake, inventory_ctx=65536), fake)])
    state = runtime.capacity.state("w1")
    assert (state.source, state.ctx_per_slot) == ("observed", 2048)
    assert runtime.capacity.mismatch("w1")["context_limit"] == {"inventory": 65536, "observed": 2048}
    assert any(r["event"] == "worker_inventory_mismatch" for r in runtime.evidence.records())
    assert runtime.worker_detail("w1")["capacity"]["ctx_per_slot"] == 2048


def test_model_swap_is_picked_up_without_config_and_wrong_model_is_blocked(fakes, tmp_path):
    fake = fakes(n_ctx=4096, alias="model-a")
    runtime = build(tmp_path, [(llama_worker("w1", fake), fake)])
    before = runtime.capacity.state("w1").limits_version
    fake.n_ctx, fake.slots = 8192, 2  # restart with new flags, same model
    runtime.refresh_capacity()
    after = runtime.capacity.state("w1")
    assert (after.ctx_per_slot, after.slots_total) == (8192, 2) and after.limits_version != before
    assert runtime.admission.limit("w1") == 2
    assert any(r["event"] == "worker_capacity_changed" for r in runtime.evidence.records())
    fake.alias = "some-other-model"  # the pool's worker now serves a different model: fail closed
    runtime.refresh_capacity()
    assert runtime.capacity.blocked_reason("w1") == "model_identity_mismatch"
    assert runtime.complete(chat())["failure_class"] in ("capability", "pool_unavailable")


def test_unreachable_engine_capacity_is_unknown_and_not_eligible(tmp_path):
    rec = dataclasses.replace(worker("w1"), endpoint="http://127.0.0.1:9", engine="llama.cpp")
    runtime = OrchestratorRuntime(CapabilityRegistry([rec]), {"w1": OpenAIProviderAdapter("http://127.0.0.1:9", "")},
                                  EvidenceStore(tmp_path / "e.jsonl"))
    assert runtime.capacity.blocked_reason("w1") == "capacity_unknown"
    assert runtime.complete(chat(model="engineering/w1"))["status"] != "ok"


# ============================================================ exact sizing (Design 01 section 3)
def test_prompt_is_counted_exactly_including_tools_and_completion_fits_the_rest(fakes, tmp_path):
    fake = fakes(n_ctx=1000)
    runtime = build(tmp_path, [(llama_worker("w1", fake), fake)])
    tools = [{"type": "function", "function": {"name": "ls", "parameters": {"type": "object"}}}]
    result = runtime.complete(chat("a b c", tools=tools))
    assert result["status"] == "ok"
    headers = result["headers"]
    prompt = int(headers["X-AIHost-Prompt-Tokens"])
    assert headers["X-AIHost-Prompt-Tokens-Source"] == "exact"
    with_tools_rendering = runtime.capacity.engines["w1"].count_prompt(fake.requests[-1])
    assert prompt == with_tools_rendering
    sent = fake.requests[-1]
    assert sent["max_tokens"] == min(8192, 1000 - prompt - 16) == int(headers["X-AIHost-Max-Completion"])


def test_omitted_max_tokens_is_bounded_and_client_cannot_raise_it(fakes, tmp_path):
    fake = fakes(n_ctx=65536)
    routes = [{"id": "d", "match": {}, "pool": "lead", "reasoning": {"mode": "off", "answer_allowance": 2000}}]
    runtime = build(tmp_path, [(llama_worker("w1", fake), fake)], routes=routes)
    assert runtime.complete(chat())["status"] == "ok"
    assert fake.requests[-1]["max_tokens"] == 2000  # no max_tokens from the client: route cap, never unlimited
    result = runtime.complete(chat(max_tokens=50_000))
    assert fake.requests[-1]["max_tokens"] == 2000 and "max_tokens" in result["headers"]["X-AIHost-Clamped"]
    runtime.complete(chat(max_tokens=10))
    assert fake.requests[-1]["max_tokens"] == 10  # asking for less is honoured


def test_context_rejection_is_exact_and_machine_readable(fakes, tmp_path):
    fake = fakes(n_ctx=60)
    runtime = build(tmp_path, [(llama_worker("w1", fake), fake)])
    result = runtime.complete(chat("word " * 40))
    assert result["failure_class"] == "context_length_exceeded" and result["http_status"] == 400
    details = result["details"]
    assert details["prompt_tokens_source"] == "exact" and details["context_length"] == 60
    assert details["available_completion"] < 64 and details["min_completion"] == 64


def test_fit_checked_fallback_uses_a_larger_window(fakes, tmp_path):
    small, large = fakes(n_ctx=80, alias="m"), fakes(n_ctx=4096, alias="m")
    routes = [{"id": "d", "match": {}, "pool": "lead", "fallback": ["deep"]}]
    runtime = build(tmp_path, [(llama_worker("a", small, pool="lead"), small), (llama_worker("b", large, pool="deep"), large)], routes=routes)
    result = runtime.complete(chat("word " * 50))
    assert result["status"] == "ok" and result["route"]["worker_id"] == "b"


# ============================================================ bounded reasoning (Design 02 / R8)
def test_reasoning_policy_is_monotonic():
    policy = rp.RoutePolicy(mode="on", budget=4096, answer_allowance=8192)
    a = rp.apply({"messages": []}, policy, worker_cap=2048, worker_reasons=True, profile=None)
    assert (a.thinking, a.budget, a.output_cap) == (True, 2048, 2048 + 8192)  # worker cap wins
    b = rp.apply({"messages": [], "thinking_budget_tokens": 99999, "chat_template_kwargs": {"enable_thinking": True}},
                 policy, worker_cap=4096, worker_reasons=True, profile="low")
    assert b.budget == 1024 and "reasoning_budget" in b.clamped  # profile lowers; raise attempt is overwritten
    c = rp.apply({"messages": [], "thinking_budget_tokens": 100}, policy, worker_cap=4096, worker_reasons=True, profile=None)
    assert c.budget == 100  # asking for less is honoured
    d = rp.apply({"messages": [], "chat_template_kwargs": {"enable_thinking": True}}, rp.RoutePolicy(mode="off"),
                 worker_cap=4096, worker_reasons=True, profile=None)
    assert d.thinking is False and d.request["chat_template_kwargs"]["enable_thinking"] is False and "enable_thinking" in d.clamped
    with pytest.raises(rp.ProfileError):
        rp.apply({"messages": []}, policy, worker_cap=None, worker_reasons=True, profile="infinite")


def test_reasoning_budget_exhaustion_and_truncation_are_reported_not_hidden(fakes, tmp_path):
    fake = fakes()
    routes = [{"id": "d", "match": {}, "pool": "lead", "reasoning": {"mode": "on", "budget": 512, "answer_allowance": 1024}}]
    runtime = build(tmp_path, [(llama_worker("w1", fake, reasoning_budget=512), fake)], routes=routes)
    fake.reasoning_content = "thinking... " + rp.DEFAULT_BUDGET_MESSAGE
    fake.finish_reason = "length"
    result = runtime.complete(chat())
    assert fake.requests[-1]["thinking_budget_tokens"] == 512 and fake.requests[-1]["chat_template_kwargs"]["enable_thinking"] is True
    assert result["response"]["choices"][0]["finish_reason"] == "length"  # N1: never rewritten to "stop"
    assert result["headers"]["X-AIHost-Termination"] == "output_limit;reasoning_budget_exhausted"
    assert runtime.metrics.reasoning_budget_exhausted_total.get(worker_id="w1", pool="lead") == 1.0
    record = [r for r in runtime.evidence.records() if r["event"] == "response_validated"][-1]
    assert record["termination"] == "output_limit" and record["reasoning_budget_exhausted"] is True


# ============================================================ admission, priority, fairness, deadlines (R2/R7)
def test_queue_full_and_max_wait_return_429_with_retry_after(fakes, tmp_path):
    fake = fakes()
    fake.delay = 1.5
    runtime = build(tmp_path, [(llama_worker("w1", fake), fake)], queue_max=1, max_wait=0.5)
    first = threading.Thread(target=runtime.complete, args=(chat(),))
    first.start()
    time.sleep(0.3)
    waited = runtime.complete(chat())
    assert waited["http_status"] == 429 and waited["failure_class"] == "capacity_exhausted" and waited["retry_after"] >= 1
    first.join()
    assert fake.busy == 0


def test_priority_then_fair_share_then_arrival_order():
    controller = AdmissionController(queue_max=10, max_wait_seconds=5)
    controller.set_slots("w", 1)
    assert controller.acquire(controller.new_ticket("p"), lambda: ["w"]) == "w"  # occupy the only slot
    order: list[str] = []
    tickets = [controller.new_ticket("p", priority="background", client_id="a"),
               controller.new_ticket("p", priority="interactive", client_id="a"),
               controller.new_ticket("p", priority="interactive", client_id="a"),
               controller.new_ticket("p", priority="interactive", client_id="b")]

    def wait(ticket, label):
        controller.acquire(ticket, lambda: ["w"])
        order.append(label)
        time.sleep(0.05)
        controller.release("w", ok=True)

    threads = [threading.Thread(target=wait, args=(t, f"{t.priority}:{t.client_id}:{t.seq}")) for t in tickets]
    for thread in threads:
        thread.start()
        time.sleep(0.05)
    controller.release("w", ok=True)
    for thread in threads:
        thread.join()
    # interactive before background; client "a" was already served once, so "b" goes before a's second request
    assert [o.split(":")[0] for o in order] == ["interactive", "interactive", "interactive", "background"]
    assert order[1].split(":")[1] == "b"


def test_deadline_expires_while_queued_with_504(fakes, tmp_path):
    fake = fakes()
    fake.delay = 1.0
    runtime = build(tmp_path, [(llama_worker("w1", fake), fake)])
    t = threading.Thread(target=runtime.complete, args=(chat(),))
    t.start()
    time.sleep(0.2)
    result = runtime.complete(chat(), deadline_ms=200)
    assert result["http_status"] == 504 and result["failure_class"] == "deadline_exceeded"
    t.join()


def test_adaptive_concurrency_halves_under_distress_and_recovers():
    controller = AdmissionController(aimd_increase_after=2)
    controller.set_slots("w", 4)
    assert controller.limit("w") == 4
    controller.acquire(controller.new_ticket("p"), lambda: ["w"])
    controller.release("w", ok=False, distress=True)
    assert controller.limit("w") == 2
    for _ in range(4):
        controller.acquire(controller.new_ticket("p"), lambda: ["w"])
        controller.release("w", ok=True, duration=1.0)
    assert controller.limit("w") == 4  # recovered, never above the observed slots


# ============================================================ R1 cancellation
def test_streaming_forwards_upstream_deltas_and_disconnect_aborts_generation(fakes, tmp_path):
    fake = fakes()
    fake.content = "first second third"
    fake.stream_delay = 2.0
    runtime = build(tmp_path, [(llama_worker("w1", fake), fake)])
    server = GatewayServer(("127.0.0.1", 0), create_gateway(runtime, "tok"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        conn = HTTPConnection(*server.server_address, timeout=10)
        conn.request("POST", "/v1/chat/completions", body=json.dumps(chat(stream=True)),
                     headers={"Authorization": "Bearer tok", "Content-Type": "application/json"})
        response = conn.getresponse()
        assert response.status == 200 and response.getheader("Content-Type") == "text/event-stream"
        first = response.readline()
        assert first.startswith(b"data: ")
        first_event = json.loads(first[len(b"data: "):])
        assert first_event["choices"][0]["delta"]["content"] == "first "
        response.close()
        conn.close()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not (fake.aborted and runtime.admission.inflight("w1") == 0):
            time.sleep(0.05)
        assert fake.aborted == 1 and fake.completed == 0, f"aborted={fake.aborted}, completed={fake.completed}"
        assert runtime.admission.inflight("w1") == 0
        assert any(r["event"] == "request_cancelled" and r["reason"] == "client_disconnect"
                   for r in runtime.evidence.records())
        # A client hanging up mid-stream is a cancellation, never evidence against the worker.
        assert runtime.registry.record("w1").healthy is True
        assert not any(r["event"] == "execution_failed" for r in runtime.evidence.records())
    finally:
        server.shutdown()


def test_streaming_completes_with_real_upstream_frames_and_terminal_chunk(fakes, tmp_path):
    fake = fakes()
    fake.content = "first second"
    fake.stream_delay = 0.01
    runtime = build(tmp_path, [(llama_worker("w1", fake), fake)])
    server = GatewayServer(("127.0.0.1", 0), create_gateway(runtime, "tok"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        conn = HTTPConnection(*server.server_address, timeout=10)
        conn.request("POST", "/v1/chat/completions", body=json.dumps(chat(stream=True)),
                     headers={"Authorization": "Bearer tok", "Content-Type": "application/json"})
        response = conn.getresponse()
        body = response.read().decode()
        events = [json.loads(line.removeprefix("data: ")) for line in body.splitlines() if line.startswith("data: {")]
        assert response.status == 200 and body.endswith("data: [DONE]\n\n")
        streamed_content = [event["choices"][0]["delta"]["content"] for event in events
                            if event.get("choices") and "content" in event["choices"][0].get("delta", {})]
        assert streamed_content == ["first ", "second "]
        assert events[-1]["choices"][0]["finish_reason"] == "stop"
        assert fake.completed == 1 and fake.aborted == 0
    finally:
        server.shutdown()


def test_client_disconnect_aborts_generation_and_frees_the_slot(fakes, tmp_path):
    fake = fakes()
    fake.delay = 5.0
    runtime = build(tmp_path, [(llama_worker("w1", fake), fake)])
    server = GatewayServer(("127.0.0.1", 0), create_gateway(runtime, "tok"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        conn = HTTPConnection(*server.server_address, timeout=10)
        conn.request("POST", "/v1/chat/completions", body=json.dumps(chat()),
                     headers={"Authorization": "Bearer tok", "Content-Type": "application/json"})
        time.sleep(0.6)
        conn.sock.close()  # client goes away mid-generation
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not (fake.aborted and runtime.admission.inflight("w1") == 0):
            time.sleep(0.05)
        assert fake.aborted == 1 and fake.completed == 0  # the worker stopped instead of finishing for nobody
        assert runtime.admission.inflight("w1") == 0
        assert any(r["event"] == "request_cancelled" and r["reason"] == "client_disconnect" for r in runtime.evidence.records())
    finally:
        server.shutdown()


# ============================================================ R3 escalation, R10 outcomes
def test_retry_attempt_and_reported_failure_escalate_deterministically(fakes, tmp_path):
    lead, deep = fakes(alias="L"), fakes(alias="D")
    routes = [{"id": "escalate", "match": {"attempt_gte": 2}, "pool": "deep"},
              {"id": "after-fail", "match": {"previous_outcome": ["fail"]}, "pool": "deep"},
              {"id": "default", "match": {}, "pool": "lead"}]
    runtime = build(tmp_path, [(llama_worker("l", lead, pool="lead"), lead), (llama_worker("d", deep, pool="deep"), deep)], routes=routes)
    client = Client("c1", token_digest("x"), frozenset({"workload"}))
    first = runtime.complete(chat(), client=client)
    assert first["route"]["rule_id"] == "default"
    assert runtime.complete(chat(), client=client, attempt=2)["route"]["rule_id"] == "escalate"
    assert runtime.report_outcome(client, first["request_id"], "fail")["status"] == "recorded"
    escalated = runtime.complete(chat(), client=client, previous_request=first["request_id"])
    assert escalated["route"]["rule_id"] == "after-fail" and escalated["route"]["worker_id"] == "d"
    other = Client("c2", token_digest("y"), frozenset({"workload"}))
    assert runtime.report_outcome(other, first["request_id"], "pass")["status"] == "not_found"  # own requests only
    summary = runtime.outcome_summary()
    assert summary[0]["fail"] == 1 and summary[0]["source"] == "client_reported"


# ============================================================ R4 candidates, canary, shadow
def test_candidate_alias_requires_qualification_scope_and_never_serves_ordinary_routes(fakes, tmp_path):
    prod, cand = fakes(alias="P"), fakes(alias="C")
    routes = [{"id": "default", "match": {}, "pool": "lead"}]
    aliases = {"candidate/c": {"pool": "cand", "scope": "qualification"}}
    runtime = build(tmp_path, [(llama_worker("p", prod), prod), (llama_worker("c", cand, pool="cand", role="candidate"), cand)],
                    routes=routes, aliases=aliases)
    workload = Client("w", token_digest("w"), frozenset({"workload"}))
    qualifier = Client("q", token_digest("q"), frozenset({"qualification"}))
    assert runtime.complete(chat(model="candidate/c"), client=workload)["http_status"] == 403
    assert runtime.complete(chat(model="candidate/c"), client=qualifier)["route"]["worker_id"] == "c"
    assert runtime.complete(chat(), client=workload)["route"]["worker_id"] == "p"
    assert "candidate/c" not in {m["id"] for m in runtime.alias_view(workload)}
    assert "candidate/c" in {m["id"] for m in runtime.alias_view(qualifier)}


def test_canary_split_is_deterministic_and_shadow_is_compared_never_returned(fakes, tmp_path):
    prod, cand = fakes(alias="P"), fakes(alias="C")
    prod.content, cand.content = "primary", "shadow-answer"
    routes = [{"id": "default", "match": {}, "pool": "lead", "shadow": {"pool": "cand", "percent": 100}}]
    runtime = build(tmp_path, [(llama_worker("p", prod), prod), (llama_worker("c", cand, pool="cand", role="candidate"), cand)],
                    routes=routes)
    result = runtime.complete(chat())
    assert result["response"]["choices"][0]["message"]["content"] == "primary"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not any(r["event"] == "shadow_compared" for r in runtime.evidence.records()):
        time.sleep(0.05)
    compared = [r for r in runtime.evidence.records() if r["event"] == "shadow_compared"]
    assert compared and compared[0]["content_equal"] is False
    from orchestrator_runtime.runtime import _split_hit
    assert all(_split_hit(f"k{i}", 30) == _split_hit(f"k{i}", 30) for i in range(50))
    assert 20 <= sum(_split_hit(f"k{i}", 30) for i in range(200)) <= 90


def test_ordinary_rules_cannot_reach_candidate_pools(monkeypatch):
    from orchestrator_gateway.__main__ import load_router
    workers = [dataclasses.replace(worker("p"), pool="lead"), dataclasses.replace(worker("c"), pool="cand", role="candidate")]
    monkeypatch.setenv("ORCHESTRATOR_ROUTES", json.dumps([{"id": "d", "match": {}, "pool": "lead", "fallback": ["cand"]}]))
    with pytest.raises(RuntimeError, match="candidate"):
        load_router(workers)


# ============================================================ R6 clients, R7 safe retries
def test_client_registry_scopes_and_quotas(tmp_path):
    path = tmp_path / "clients.json"
    path.write_text(json.dumps({"clients": [
        {"client_id": "nexus", "token_sha256": token_digest("t1"), "scopes": ["workload"], "quota": {"requests_per_minute": 2}},
        {"client_id": "ops", "token_sha256": token_digest("t2"), "scopes": ["admin", "monitoring"]},
    ]}))
    registry = ClientRegistry.from_file(path, state_path=tmp_path / "usage.json")
    nexus = registry.authenticate("Bearer t1")
    assert nexus.client_id == "nexus" and registry.authenticate("Bearer nope") is None
    registry.admit(nexus)
    registry.admit(nexus)
    from orchestrator_runtime import QuotaExceeded
    with pytest.raises(QuotaExceeded) as raised:
        registry.admit(nexus)
    assert raised.value.retry_after >= 1
    path.write_text(json.dumps({"clients": [{"client_id": "x", "token_sha256": "abc", "scopes": ["workload"]}]}))
    with pytest.raises(ValueError):
        ClientRegistry.from_file(path)


def test_pre_generation_failure_is_retried_once_elsewhere(fakes, tmp_path):
    good = fakes(alias="m")
    dead = dataclasses.replace(llama_worker("dead", good), endpoint="http://127.0.0.1:9", worker_id="dead")
    runtime = OrchestratorRuntime(
        CapabilityRegistry([dead, llama_worker("good", good)]),
        {"dead": OpenAIProviderAdapter("http://127.0.0.1:9", "", "m"), "good": OpenAIProviderAdapter(good.endpoint, "", "m")},
        EvidenceStore(tmp_path / "e.jsonl"), engines={"dead": LlamaCppAdapter(good.endpoint), "good": LlamaCppAdapter(good.endpoint)},
    )
    results = [runtime.complete(chat(model="engineering/lead"), affinity=f"s{i}") for i in range(6)]
    assert all(r["status"] == "ok" and r["route"]["worker_id"] == "good" for r in results)
    assert runtime.metrics.retries_total.get(reason="pre_generation") >= 1


def test_timeout_is_never_retried(fakes, tmp_path):
    slow = fakes(alias="m")
    slow.delay = 3
    runtime = build(tmp_path, [(llama_worker("w1", slow), slow)])
    result = runtime.complete(chat(), timeout=0.5)
    assert result["failure_class"] == "timeout" and runtime.metrics.retries_total.get(reason="pre_generation") == 0


# ============================================================ R9 capabilities and /v1/models
def test_capability_routing_rejects_with_missing_names_and_alias_view_reports_provenance(fakes, tmp_path):
    no_tools = fakes(tools=False)
    runtime = build(tmp_path, [(llama_worker("w1", no_tools, capabilities=("navigation",)), no_tools)],
                    capability_evidence={"sha256:" + "b" * 64: {"reasoning_controllable": {"result": "pass", "evidence_id": "Q-1", "date": "2026-10-07"}}})
    result = runtime.complete(chat(tools=[{"type": "function", "function": {"name": "x"}}]))
    assert result["http_status"] == 422 and result["missing_capabilities"] == ["tools"]
    view = {m["id"]: m for m in runtime.alias_view()}["engineering/lead"]
    assert view["context_length"] == no_tools.n_ctx and view["max_model_len"] == no_tools.n_ctx and view["limits_version"]
    caps = view["capabilities"]
    assert caps["tools"] == {"available": False, "provenance": "unavailable"}
    assert caps["reasoning_controllable"]["provenance"] == "verified" and caps["reasoning_controllable"]["evidence"] == ["Q-1"]
    assert caps["fim"]["available"] is False and caps["streaming"]["available"] is True
    assert view["serving"][0]["engine_version"] == "b1-test" and view["serving"][0]["quantization"]


def test_tokenize_endpoint_counts_exactly(fakes, tmp_path):
    fake = fakes()
    runtime = build(tmp_path, [(llama_worker("w1", fake), fake)])
    counted = runtime.count_tokens(chat("a b c"))
    assert counted["source"] == "exact" and counted["prompt_tokens"] > 0 and counted["context_length"] == fake.n_ctx


# ============================================================ R5 drain, R11 evidence, R12 graceful stop
def test_drain_admits_nothing_new_and_survives_restart(fakes, tmp_path):
    fake = fakes()
    state = tmp_path / "state.json"
    runtime = build(tmp_path, [(llama_worker("w1", fake), fake)], state_path=state)
    assert runtime.drain("w1")["status"] == "drained"
    assert runtime.complete(chat())["status"] != "ok"
    assert runtime.worker_detail("w1")["drain"]["state"] == "drained"
    restarted = build(tmp_path, [(llama_worker("w1", fake), fake)], state_path=state)
    assert "w1" in restarted.admission.drained()
    restarted.undrain("w1")
    assert restarted.complete(chat())["status"] == "ok"


def test_evidence_chain_continues_across_restarts_and_breaks_are_detected(tmp_path):
    path = tmp_path / "chain.jsonl"
    first = EvidenceStore(path)
    first.genesis(release="r1")
    first.append("a", x=1)
    second = EvidenceStore(path)  # restart: continues from the persisted head
    assert second.chain_valid and second.head == first.head
    second.append("b", x=2)
    assert verify_lines(path.read_text().splitlines())[0]
    lines = path.read_text().splitlines()
    tampered = json.loads(lines[1]); tampered["x"] = 99
    path.write_text("\n".join([lines[0], json.dumps(tampered), *lines[2:]]) + "\n")
    third = EvidenceStore(path)
    assert not third.chain_valid and third.records()[-1]["event"] == "chain_break_detected"
    cli = subprocess.run([sys.executable, "-m", "orchestrator_runtime.evidence", "verify", str(path)], capture_output=True, text=True)
    assert cli.returncode == 1 and '"intact": false' in cli.stdout


def test_prompt_data_policy_defaults_to_hash_only():
    secret = "my api key is sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    assert "sk-" not in scrub(secret, "hash") and scrub(secret, "hash").startswith("[sha256:")
    assert "<redacted>" in scrub(secret, "redact") and scrub(secret, "store") == secret


def test_graceful_shutdown_refuses_new_work_and_finishes_or_cancels_inflight(fakes, tmp_path):
    fake = fakes()
    fake.delay = 0.5
    runtime = build(tmp_path, [(llama_worker("w1", fake), fake)])
    results = []
    t = threading.Thread(target=lambda: results.append(runtime.complete(chat())))
    t.start()
    time.sleep(0.2)
    runtime.begin_shutdown()
    assert runtime.complete(chat())["failure_class"] == "gateway_restarting"
    assert runtime.wait_idle(5.0) is True
    t.join()
    assert results[0]["status"] == "ok"  # in-flight work completed within the grace period


# ============================================================ remote-origin policy (Design 05)
def test_local_listener_serves_monitoring_only_and_remote_listener_refuses_host_origin(fakes, tmp_path):
    fake = fakes()
    runtime = build(tmp_path, [(llama_worker("w1", fake), fake)])
    for mode in ("local", "remote"):
        server = GatewayServer(("127.0.0.1", 0), create_gateway(runtime, "tok", listener=mode))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            conn = HTTPConnection(*server.server_address, timeout=5)
            conn.request("POST", "/v1/chat/completions", body=json.dumps(chat()),
                         headers={"Authorization": "Bearer tok", "Content-Type": "application/json"})
            response = conn.getresponse()
            body = json.loads(response.read())
            assert response.status == 403 and body["error"]["code"] == "local_origin_forbidden"
            conn = HTTPConnection(*server.server_address, timeout=5)
            conn.request("GET", "/health")
            health = conn.getresponse()
            assert health.status in (200, 503) if mode == "local" else health.status == 403
        finally:
            server.shutdown()
    assert runtime.metrics.local_origin_refused_total.get(listener="local") >= 1


def test_origin_classification():
    from orchestrator_gateway.server import _is_local
    local = {"10.0.8.5", "127.0.0.1", "::1"}
    assert _is_local("127.0.0.1", local) and _is_local("::1", local) and _is_local("10.0.8.5", local)
    assert _is_local("::ffff:10.0.8.5", local)
    assert not _is_local("10.0.8.95", local)
