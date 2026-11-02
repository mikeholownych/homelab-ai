"""Tests for Phase 4 Enterprise Inference Appliance Capabilities:
- Initiative 2: Zero-Downtime Hot Reconfiguration (SIGHUP & POST /v1/admin/reload)
- Initiative 4: Self-Healing & Automated Worker Recovery (Watchdog Supervisor & Synthetic Pre-Warm Probing)
- Initiative 5: Semantic Caching & Prefix Cache Affinity Routing
- Initiative 7: Appliance Management UI & Console (Admin Status & Web Admin Portal)
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import unittest.mock
import pytest

pytest.importorskip("starlette")
pytest.importorskip("httpx")
from starlette.testclient import TestClient

from orchestrator_gateway import create_asgi_gateway
from orchestrator_runtime import (
    CapabilityRegistry,
    Client,
    ClientRegistry,
    EvidenceStore,
    HealthManager,
    InMemoryAdapter,
    OrchestratorRuntime,
    ResponseCache,
    RouteRule,
    Router,
)
from orchestrator_runtime.cache import compute_shingles, extract_prompt_text, jaccard_similarity
from orchestrator_runtime.runtime import _affinity_key
from tests.test_orchestrator_runtime import worker


def make_worker(worker_id: str, pool: str = "lead"):
    return dataclasses.replace(worker(worker_id), pool=pool)


# =====================================================================
# 1. Semantic Caching & Similarity Logic
# =====================================================================

def test_semantic_shingles_and_jaccard():
    text1 = "How do I configure nginx for reverse proxying?"
    text2 = "How do I configure nginx for reverse proxy?"
    shingles1 = compute_shingles(text1, n=3)
    shingles2 = compute_shingles(text2, n=3)

    sim = jaccard_similarity(shingles1, shingles2)
    assert sim > 0.6  # High overlap

    text3 = "What is the capital of France?"
    shingles3 = compute_shingles(text3, n=3)
    sim_unrelated = jaccard_similarity(shingles1, shingles3)
    assert sim_unrelated == 0.0


def test_response_cache_similarity_does_not_substitute_a_response():
    cache = ResponseCache(
        max_entries=10,
        default_ttl=60.0,
        semantic_enabled=True,
        semantic_threshold=0.85,
    )

    req1 = {
        "model": "model-a",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Explain general relativity in simple terms please"},
        ],
        "temperature": 0.0,
    }
    resp1 = {"choices": [{"message": {"content": "General relativity explains gravity as curvature of spacetime."}}]}

    # Initially empty
    key1 = cache.compute_key(req1)
    assert cache.get(key1) is None

    # Cache response
    cache.set(key1, resp1, request=req1)
    assert cache.size() == 1

    # Exact hit
    exact_hit = cache.get(key1)
    assert exact_hit is not None
    assert exact_hit["choices"][0]["message"]["content"] == resp1["choices"][0]["message"]["content"]

    # Semantic hit with slight phrasing variation
    req2 = {
        "model": "model-a",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Explain general relativity in simple terms, please!"},
        ],
        "temperature": 0.0,
    }
    key2 = cache.compute_key(req2)
    assert key2 != key1  # Hash differs!

    sem_hit, sim = cache.get_semantic(req2)
    assert sem_hit is None
    assert sim == 0.0

    stats = cache.stats()
    assert stats["hits"] == 1
    assert stats["semantic_hits"] == 0


def test_response_cache_semantic_disabled():
    cache = ResponseCache(
        max_entries=10,
        semantic_enabled=False,
    )
    req1 = {
        "model": "model-a",
        "messages": [{"role": "user", "content": "Write a python function to compute fibonacci"}],
        "temperature": 0.0,
    }
    resp1 = {"choices": [{"message": {"content": "def fib(n): pass"}}]}
    cache.set(cache.compute_key(req1), resp1, request=req1)

    req2 = {
        "model": "model-a",
        "messages": [{"role": "user", "content": "Write a python function to compute fibonacci numbers"}],
        "temperature": 0.0,
    }
    sem_hit, sim = cache.get_semantic(req2)
    assert sem_hit is None
    assert sim == 0.0


# =====================================================================
# 2. Prefix Cache Affinity Routing
# =====================================================================

def test_prefix_cache_affinity_routing(tmp_path):
    w1 = make_worker("w1", pool="lead")
    w2 = make_worker("w2", pool="lead")
    registry = CapabilityRegistry([w1, w2])
    evidence = EvidenceStore(tmp_path / "evidence.jsonl")

    adapters = {
        "w1": InMemoryAdapter("reply from w1"),
        "w2": InMemoryAdapter("reply from w2"),
    }

    runtime = OrchestratorRuntime(registry, adapters, evidence)

    # First request establishes prefix affinity
    system_prompt = "You are a senior software engineer specialized in Linux kernel and Intel Arc GPU drivers. " * 5
    req1 = {
        "model": "engineering/w1",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Turn 1 question"},
        ],
    }

    res1 = runtime.complete(req1)
    assigned_worker_id = res1["route"]["worker_id"]

    # Affinity key should be registered
    affinity_key = _affinity_key(req1, None)
    assert affinity_key is not None
    assert runtime._worker_prefix_affinity.get(affinity_key) == assigned_worker_id

    # Second request in the same conversation (multi-turn with identical head prefix)
    req2 = {
        "model": "engineering/w1",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Turn 1 question"},
            {"role": "assistant", "content": "reply from w1"},
            {"role": "user", "content": "Turn 2 question with conversational context"},
        ],
    }
    affinity_key2 = _affinity_key(req2, None)
    assert affinity_key2 == affinity_key

    # Select with affinity key should return the exact worker that served turn 1
    selected2 = runtime.registry.select(
        frozenset({"navigation"}),
        public_model_id="engineering/w1",
        pool="lead",
        affinity_key=affinity_key2,
    )
    assert selected2.worker_id == assigned_worker_id


# =====================================================================
# 3. Zero-Downtime Hot Reconfiguration
# =====================================================================

def test_hot_reconfiguration_runtime(tmp_path, monkeypatch):
    w1 = make_worker("w1", pool="lead")
    registry = CapabilityRegistry([w1])
    evidence = EvidenceStore(tmp_path / "evidence.jsonl")
    runtime = OrchestratorRuntime(
        registry,
        {"w1": InMemoryAdapter("ok")},
        evidence,
    )

    token_hash = hashlib.sha256(b"secret123").hexdigest()
    clients_file = tmp_path / "clients.json"
    clients_file.write_text(json.dumps({
        "clients": [
            {
                "client_id": "test-client",
                "token_sha256": token_hash,
                "scopes": ["workload", "admin"],
                "default_priority": "standard",
            }
        ]
    }), encoding="utf-8")

    monkeypatch.setenv("ORCHESTRATOR_CLIENTS_FILE", str(clients_file))
    routes_json = json.dumps([
        {"id": "hot_rule_1", "pool": "lead"}
    ])
    monkeypatch.setenv("ORCHESTRATOR_ROUTES", routes_json)
    monkeypatch.setenv("ORCHESTRATOR_MODEL_ALIASES", json.dumps({"test-alias": "lead"}))

    result = runtime.reload_config()
    assert result["rules_count"] == 1
    assert result["aliases_count"] == 1
    assert result["clients_count"] == 1
    assert hasattr(runtime, "clients")
    assert "test-client" in [c.client_id for c in runtime.clients.clients()]

    # Evidence should record reload
    records = [r for r in evidence.records() if r.get("event") == "config_reloaded"]
    assert len(records) == 1
    assert records[0]["event"] == "config_reloaded"
    assert records[0]["rules_count"] == 1


# =====================================================================
# 4. Self-Healing & Automated Worker Recovery
# =====================================================================

def test_health_manager_recovery_and_warmup(tmp_path):
    w1 = worker("w1")
    registry = CapabilityRegistry([w1])
    health_mgr = HealthManager(registry)

    # Worker recovery method with recovery_hook
    recovered = []
    health_mgr.recovery_hook = lambda wid, reason: recovered.append((wid, reason))

    res = health_mgr.recover_worker("w1", reason="consecutive probe failures")
    assert res["triggered"] is True
    assert len(recovered) == 1
    assert recovered[0] == ("w1", "consecutive probe failures")

    # Warmup synthetic 1-token probe check
    with unittest.mock.patch("urllib.request.urlopen") as mock_url:
        mock_resp = unittest.mock.MagicMock()
        mock_resp.status = 200
        mock_url.return_value.__enter__.return_value = mock_resp
        warmup_record = {"model_id": "model/w1", "worker_id": "w1"}
        assert health_mgr._warmup_worker(warmup_record, "http://127.0.0.1:8000", {}) is True


# =====================================================================
# 5. Admin Endpoints & Appliance Web Console
# =====================================================================

def test_admin_api_endpoints_and_web_console(tmp_path):
    w1 = make_worker("w1", pool="lead")
    evidence = EvidenceStore(tmp_path / "evidence.jsonl")
    runtime = OrchestratorRuntime(
        CapabilityRegistry([w1]),
        {"w1": InMemoryAdapter("reply")},
        evidence,
    )
    admin_token = "enterprise-admin-secret-token"
    app = create_asgi_gateway(runtime, "client-token", monitoring_token=admin_token)
    client = TestClient(app)

    # 1. Unauthorized access to /v1/admin/status
    res_unauth = client.get("/v1/admin/status")
    assert res_unauth.status_code == 401

    # 2. Authorized access to /v1/admin/status
    res_status = client.get("/v1/admin/status", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_status.status_code == 200
    data = res_status.json()
    assert data["status"] in ("ok", "healthy")
    assert "gateway" in data
    assert "scheduler" in data
    assert "workers" in data
    assert "cache" in data
    assert "evidence" in data
    assert "reloads_count" in data

    # 3. POST /v1/admin/reload
    res_reload = client.post("/v1/admin/reload", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_reload.status_code == 200
    reload_data = res_reload.json()
    assert reload_data["status"] == "ok"
    assert "reloaded" in reload_data

    # 4. POST /v1/admin/workers/{worker_id}/recover
    res_recover = client.post("/v1/admin/workers/w1/recover", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_recover.status_code == 200
    assert res_recover.json()["status"] == "ok"

    # 5. GET /admin Web Console (HTML)
    res_unauth_ui = client.get("/admin")
    assert res_unauth_ui.status_code == 401

    # Authorized via header
    res_console = client.get("/admin", headers={"Authorization": f"Bearer {admin_token}"})
    assert res_console.status_code == 200
    assert "text/html" in res_console.headers["content-type"]
    html = res_console.text
    assert "Enterprise Appliance" in html
    import socket
    assert socket.gethostname() in html

    # Authorized via query param token
    res_query = client.get(f"/admin?token={admin_token}")
    assert res_query.status_code == 200
    assert "Enterprise Appliance Console" in res_query.text
