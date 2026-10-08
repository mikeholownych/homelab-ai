from __future__ import annotations

import json
import threading
from http.client import HTTPConnection

import pytest

from orchestrator_gateway import GatewayServer, create_gateway
from orchestrator_runtime import (
    CapabilityRegistry, EvidenceStore, InMemoryAdapter, OrchestratorRuntime, RouteConfigError, Router,
)
from tests.test_orchestrator_runtime import worker

RULES = [
    {"id": "subagent-aux", "match": {"task_class": ["subagent", "summarize"]}, "pool": "aux", "fallback": ["lead"]},
    {"id": "tools-lead", "match": {"has_tools": True}, "pool": "lead"},
    {"id": "small-aux", "match": {"max_prompt_tokens": 200}, "pool": "aux", "fallback": ["lead"]},
    {"id": "default", "match": {}, "pool": "lead"},
]
# Only explicit pool names bypass the table; the generic legacy name (engineering/b0) is routed by it.
ALIASES = {"engineering/lead": "lead", "engineering/aux": "aux"}


def _decide(router, **kw):
    base = dict(model="engineering/other", task_class=None, has_tools=False, prompt_tokens=1000)
    base.update(kw)
    return router.decide(**base)


def test_first_match_wins_and_default_catches_the_rest():
    router = Router.from_config(RULES, ALIASES)
    assert _decide(router, task_class="subagent").rule_id == "subagent-aux"
    assert _decide(router, task_class="subagent", has_tools=True).rule_id == "subagent-aux"  # order matters
    assert _decide(router, has_tools=True).rule_id == "tools-lead"
    assert _decide(router, prompt_tokens=50).rule_id == "small-aux"
    assert _decide(router, prompt_tokens=5000).rule_id == "default"
    assert _decide(router, task_class="unknown-class").pool == "lead"


def test_model_alias_is_an_explicit_choice_that_bypasses_the_table():
    router = Router.from_config(RULES, ALIASES)
    decision = _decide(router, model="engineering/aux", has_tools=True, task_class=None)
    assert (decision.pool, decision.rule_id, decision.fallback) == ("aux", "alias:engineering/aux", ())


@pytest.mark.parametrize("bad", [
    [],
    [{"id": "a", "pool": "lead", "match": {"has_tools": True}}],  # last rule is not an unconditional default
    [{"id": "a", "pool": "lead"}, {"id": "a", "pool": "lead"}],  # duplicate ids
    [{"id": "a", "pool": "lead", "bogus": 1}],
    [{"id": "a", "pool": "lead", "match": {"colour": "red"}}],
    [{"id": "a", "pool": "lead", "fallback": ["lead"]}],
    [{"id": "a", "pool": ""}],
    [{"id": "a", "pool": "lead", "match": {"min_prompt_tokens": 10, "max_prompt_tokens": 5}}, {"id": "d", "pool": "lead"}],
    [{"id": "a", "pool": "lead", "match": {"has_tools": "yes"}}, {"id": "d", "pool": "lead"}],
    [{"id": "a", "pool": "lead", "match": {"min_prompt_tokens": -1}}, {"id": "d", "pool": "lead"}],
])
def test_invalid_route_tables_are_rejected(bad):
    with pytest.raises(RouteConfigError):
        Router.from_config(bad)


def _runtime(tmp_path, *, aux_healthy=True, lead_healthy=True):
    # Both declare tool support (production inventory name), so tool requests are routable under R9.
    lead = worker("lead1", capabilities=("navigation", "tool_call_proposal")); aux = worker("aux1", capabilities=("navigation", "tool_call_proposal"))
    object.__setattr__(lead, "pool", "lead"); object.__setattr__(aux, "pool", "aux")
    object.__setattr__(lead, "healthy", lead_healthy); object.__setattr__(aux, "healthy", aux_healthy)
    adapters = {"lead1": InMemoryAdapter("from-lead"), "aux1": InMemoryAdapter("from-aux")}
    runtime = OrchestratorRuntime(CapabilityRegistry([lead, aux]), adapters, EvidenceStore(tmp_path / "e.jsonl"),
                                  router=Router.from_config(RULES, ALIASES))
    return runtime, adapters


def _req(content="hello " * 400, **extra):
    return {"model": "engineering/b0", "messages": [{"role": "user", "content": content}], **extra}


def test_runtime_routes_by_rule_and_records_evidence(tmp_path):
    runtime, _ = _runtime(tmp_path)
    cases = [
        (dict(task_class="subagent"), "aux1", "subagent-aux"),
        (dict(task_class=None, tools=[{"type": "function"}]), "lead1", "tools-lead"),
        (dict(task_class=None), "lead1", "default"),
    ]
    for extra, expected_worker, rule in cases:
        task_class = extra.pop("task_class")
        result = runtime.complete(_req(**extra), task_class=task_class)
        assert result["status"] == "ok"
        assert result["route"]["worker_id"] == expected_worker and result["route"]["rule_id"] == rule
    selected = [r for r in runtime.evidence.records() if r["event"] == "worker_selected"]
    assert [r["route_rule"] for r in selected] == ["subagent-aux", "tools-lead", "default"]


def test_aux_falls_back_to_lead_but_lead_never_falls_back_to_aux(tmp_path):
    runtime, _ = _runtime(tmp_path, aux_healthy=False)
    result = runtime.complete(_req(), task_class="subagent")
    assert result["status"] == "ok" and result["route"]["worker_id"] == "lead1" and result["route"]["fallback_used"] is True

    runtime, _ = _runtime(tmp_path, lead_healthy=False)
    result = runtime.complete(_req(), task_class=None)  # default rule has no fallback
    assert result["status"] == "blocked" and result["failure_class"] == "pool_unavailable"
    assert result["route"]["rule_id"] == "default"


def test_pinned_worker_bypasses_the_table_and_is_labelled(tmp_path):
    runtime, _ = _runtime(tmp_path)
    result = runtime.complete(_req(), worker_id="aux1")
    assert result["route"]["rule_id"] == "pinned" and result["route"]["worker_id"] == "aux1"


def _serve(runtime):
    server = GatewayServer(("127.0.0.1", 0), create_gateway(runtime, "tok", allow_worker_pinning=True))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _call(server, method, path, body=None, headers=None):
    host, port = server.server_address
    conn = HTTPConnection(host, port)
    h = {"Authorization": "Bearer tok", "Content-Type": "application/json", **(headers or {})}
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
    r = conn.getresponse(); data = r.read(); conn.close()
    return r.status, dict(r.getheaders()), json.loads(data)


def test_gateway_exposes_route_header_inventory_and_aliases(tmp_path):
    runtime, _ = _runtime(tmp_path)
    server = _serve(runtime)
    try:
        status, headers, payload = _call(server, "POST", "/v1/chat/completions", _req(), {"X-Task-Class": "summarize"})
        assert status == 200 and payload["choices"][0]["message"]["content"] == "from-aux"
        assert headers["X-AIHost-Route"] == "rule=subagent-aux;pool=aux;worker=aux1;fallback=false"

        status, headers, payload = _call(server, "POST", "/v1/chat/completions", _req(model="engineering/aux", tools=[{"type": "function"}]))
        assert payload["choices"][0]["message"]["content"] == "from-aux" and "rule=alias:engineering/aux" in headers["X-AIHost-Route"]

        status, _, inventory = _call(server, "GET", "/v1/routes")
        assert status == 200
        assert [r["id"] for r in inventory["router"]["rules"]] == ["subagent-aux", "tools-lead", "small-aux", "default"]
        # aliases are described with their pool, scope and reasoning policy (Design 03 R4 / Design 02)
        assert {name: spec["pool"] for name, spec in inventory["router"]["aliases"].items()} == ALIASES
        assert all(spec["scope"] == "workload" for spec in inventory["router"]["aliases"].values())
        assert sorted(inventory["pools"]) == ["aux", "lead"] and inventory["pools"]["aux"][0]["worker_id"] == "aux1"

        status, _, models = _call(server, "GET", "/v1/models")
        ids = {m["id"] for m in models["data"]}
        assert {"engineering/aux", "engineering/lead"} <= ids

        conn = HTTPConnection(*server.server_address)
        conn.request("GET", "/v1/routes"); assert conn.getresponse().status == 401  # inventory needs auth
    finally:
        server.shutdown(); server.server_close()


def test_gateway_reports_pool_unavailable_with_the_matched_rule(tmp_path):
    runtime, _ = _runtime(tmp_path, lead_healthy=False)
    server = _serve(runtime)
    try:
        status, headers, payload = _call(server, "POST", "/v1/chat/completions", _req())
        assert status == 503 and payload["error"]["code"] == "pool_unavailable"
        assert "rule=default" in headers["X-AIHost-Route"]
    finally:
        server.shutdown(); server.server_close()
