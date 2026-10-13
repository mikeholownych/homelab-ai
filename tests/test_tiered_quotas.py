"""Tests for tiered per-model and per-pool client rate quotas."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from orchestrator_runtime import CapabilityRegistry, EvidenceStore, InMemoryAdapter, OrchestratorRuntime
from orchestrator_runtime.clients import Client, ClientRegistry, QuotaExceeded
from tests.test_orchestrator_runtime import worker


def test_tiered_quota_parsing_from_file(tmp_path):
    registry_file = tmp_path / "clients.json"
    dummy_digest = "a" * 64
    config = {
        "clients": [
            {
                "client_id": "tiered-client",
                "token_sha256": dummy_digest,
                "scopes": ["workload"],
                "quota": {
                    "requests_per_minute": 100,
                    "tokens_per_day": 1000000,
                    "models": {
                        "qwen-coder": {"requests_per_minute": 10, "tokens_per_day": 50000},
                    },
                    "pools": {
                        "lead": {"requests_per_minute": 20, "tokens_per_day": 200000},
                    },
                },
            }
        ]
    }
    registry_file.write_text(json.dumps(config), encoding="utf-8")
    reg = ClientRegistry.from_file(registry_file)
    clients = reg.clients()
    assert len(clients) == 1
    c = clients[0]
    assert c.client_id == "tiered-client"
    assert c.requests_per_minute == 100
    assert c.tokens_per_day == 1000000
    assert "qwen-coder" in c.model_quotas
    assert c.model_quotas["qwen-coder"]["requests_per_minute"] == 10
    assert c.model_quotas["qwen-coder"]["tokens_per_day"] == 50000
    assert "lead" in c.pool_quotas
    assert c.pool_quotas["lead"]["requests_per_minute"] == 20


def test_tiered_model_rate_limiting():
    c = Client(
        client_id="c1",
        token_sha256="b" * 64,
        scopes=frozenset({"workload"}),
        requests_per_minute=100,
        model_quotas={
            "expensive-model": {"requests_per_minute": 2},
        },
    )
    reg = ClientRegistry([c])

    # Model admission: first 2 requests succeed
    reg.admit(c, model="expensive-model")
    reg.admit(c, model="expensive-model")

    # 3rd request for expensive-model is rejected
    with pytest.raises(QuotaExceeded) as exc:
        reg.admit(c, model="expensive-model")
    assert "expensive-model" in str(exc.value)

    # But request for another model still passes under global limit
    reg.admit(c, model="cheap-model")


def test_tiered_pool_token_budget_and_persistence(tmp_path):
    state_file = tmp_path / "client-state.json"
    c = Client(
        client_id="c2",
        token_sha256="c" * 64,
        scopes=frozenset({"workload"}),
        pool_quotas={
            "lead": {"tokens_per_day": 1000},
        },
    )
    reg = ClientRegistry([c], state_path=state_file, flush_interval_seconds=0.01)

    reg.admit(c, pool="lead")
    reg.charge_tokens(c, 800, pool="lead", sync=True)

    usage = reg.usage("c2")
    assert usage["tokens_today"] == 800
    assert usage["pools"]["lead"] == 800

    # Charge remaining 300 (exceeds 1000 limit)
    reg.charge_tokens(c, 300, pool="lead", sync=True)
    assert reg.usage("c2")["pools"]["lead"] == 1100

    with pytest.raises(QuotaExceeded) as exc:
        reg.admit(c, pool="lead")
    assert "pool 'lead'" in str(exc.value)

    # Test persistence and restore
    new_reg = ClientRegistry([c], state_path=state_file)
    assert new_reg.usage("c2")["pools"]["lead"] == 1100
    with pytest.raises(QuotaExceeded):
        new_reg.admit(c, pool="lead")


def test_runtime_complete_enforces_model_and_pool_quotas(tmp_path):
    w1 = worker("w1")
    c = Client(
        client_id="app-user",
        token_sha256="d" * 64,
        scopes=frozenset({"workload"}),
        model_quotas={
            "engineering/w1": {"requests_per_minute": 1},
        },
    )
    runtime = OrchestratorRuntime(
        CapabilityRegistry([w1]),
        {"w1": InMemoryAdapter("reply")},
        EvidenceStore(tmp_path / "evidence.jsonl"),
    )
    runtime.clients = ClientRegistry([c])

    req = {"model": "engineering/w1", "messages": [{"role": "user", "content": "hi"}]}

    # First completion succeeds
    res1 = runtime.complete(req, client=c)
    assert res1["status"] == "ok"

    # Second completion hits 429 quota_exceeded for model
    res2 = runtime.complete(req, client=c)
    assert res2["status"] == "limited"
    assert res2["http_status"] == 429
    assert "engineering/w1" in res2["message"]
