import hashlib
import json
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from orchestrator_runtime.clients import Client, ClientRegistry, token_digest
from orchestrator_runtime.guardrails import GuardrailScanner
from orchestrator_runtime.metrics import MetricsRegistry
from orchestrator_runtime.routing import RouteRule, Router
from orchestrator_runtime import CapabilityRegistry, EvidenceStore
from orchestrator_runtime.runtime import OrchestratorRuntime


def test_batched_client_state_persistence(tmp_path: Path):
    state_file = tmp_path / "client-usage.json"
    client = Client(
        client_id="corp-client",
        token_sha256=token_digest("test-secret-token"),
        scopes=frozenset({"workload"}),
        tokens_per_day=50_000,
    )
    registry = ClientRegistry([client], state_path=state_file)
    registry.flush_interval_seconds = 60.0  # long flush interval

    # Charge tokens without sync
    registry.charge_tokens(client, 1500)
    assert not state_file.exists()  # Batched in-memory, disk write postponed!

    # Force save state (e.g. on shutdown)
    registry.save_state(force=True)
    assert state_file.exists()
    data = json.loads(state_file.read_text(encoding="utf-8"))
    assert data["usage"]["corp-client"]["tokens_today"] == 1500


def test_client_reload_from_file_preserves_usage(tmp_path: Path):
    state_file = tmp_path / "client-usage.json"
    clients_file = tmp_path / "clients.json"

    token_a = "secret-token-a"
    token_b = "secret-token-b"

    initial_config = {
        "clients": [
            {
                "client_id": "client-a",
                "token_sha256": token_digest(token_a),
                "scopes": ["workload"],
                "quota": {"tokens_per_day": 10_000},
            }
        ]
    }
    clients_file.write_text(json.dumps(initial_config), encoding="utf-8")

    registry = ClientRegistry.from_file(clients_file, state_path=state_file)
    authenticated = registry.authenticate(f"Bearer {token_a}")
    assert authenticated is not None
    assert authenticated.client_id == "client-a"

    # Accrue usage
    registry.charge_tokens(authenticated, 2500, sync=True)
    assert registry.usage("client-a")["tokens_today"] == 2500

    # Hot reload with client-b added
    updated_config = {
        "clients": [
            {
                "client_id": "client-a",
                "token_sha256": token_digest(token_a),
                "scopes": ["workload"],
                "quota": {"tokens_per_day": 20_000},
            },
            {
                "client_id": "client-b",
                "token_sha256": token_digest(token_b),
                "scopes": ["workload"],
                "quota": {"tokens_per_day": 5_000},
            },
        ]
    }
    clients_file.write_text(json.dumps(updated_config), encoding="utf-8")
    registry.reload_from_file(clients_file)

    # Verify client-b is now recognized and client-a preserved its usage
    assert registry.authenticate(f"Bearer {token_b}") is not None
    assert registry.usage("client-a")["tokens_today"] == 2500


def test_router_update_rules_preserves_latency_tracker():
    rule1 = RouteRule("default", "lead")
    router = Router([rule1])
    router.latency_tracker.record("worker-1", "lead", 0.045)
    assert router.latency_tracker.worker_duration("worker-1") == pytest.approx(0.045)

    # Hot-update rules
    rule2 = RouteRule("fallback-rule", "deep")
    router.update_rules([rule2])
    assert len(router.rules) == 1
    assert router.rules[0].pool == "deep"
    # Latency history is preserved
    assert router.latency_tracker.worker_duration("worker-1") == pytest.approx(0.045)


def test_egress_output_dlp_reject():
    scanner = GuardrailScanner(action="reject", detect_secrets=True)
    res = scanner.inspect_output({
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "Here is the key you requested: AKIAIOSFODNN7EXAMPLE",
            }
        }]
    })
    assert res.rejected is True
    assert res.violation_type == "output_secret_detected"
    assert "aws_access_key" in res.detected_patterns


def test_egress_output_dlp_redact():
    scanner = GuardrailScanner(action="redact", detect_secrets=True)
    raw = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "Use secret ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 in header",
            }
        }]
    }
    res = scanner.inspect_output(raw)
    assert res.redacted is True
    assert "github_pat" in res.detected_patterns
    redacted_content = res.sanitized_request["choices"][0]["message"]["content"]
    assert "[REDACTED_SECRET]" in redacted_content
    assert "ghp_" not in redacted_content


def test_egress_output_dlp_flag():
    scanner = GuardrailScanner(action="flag", detect_secrets=True)
    raw = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "Secret is AKIAIOSFODNN7EXAMPLE",
            }
        }]
    }
    res = scanner.inspect_output(raw)
    assert res.flagged is True
    assert res.rejected is False
    assert res.redacted is False
    assert "aws_access_key" in res.detected_patterns


def test_runtime_reload_configuration(tmp_path: Path):
    clients_file = tmp_path / "clients.json"
    token_a = "token-a"
    clients_file.write_text(json.dumps({
        "clients": [{
            "client_id": "c-a",
            "token_sha256": token_digest(token_a),
            "scopes": ["workload"],
        }]
    }), encoding="utf-8")

    runtime = MagicMock(spec=OrchestratorRuntime)
    runtime.clients = ClientRegistry.from_file(clients_file)
    runtime.router = Router([RouteRule("default", "lead")])
    runtime.evidence = MagicMock()

    OrchestratorRuntime.reload_configuration(
        runtime,
        clients_file=clients_file,
        routes=[{"id": "r2", "pool": "deep"}],
    )
    assert len(runtime.router.rules) == 1
    assert runtime.router.rules[0].pool == "deep"
    runtime.evidence.append.assert_called_with(
        "configuration_reloaded",
        clients_count=1,
        rules_count=1,
    )


def test_runtime_streaming_egress_dlp_redaction(tmp_path: Path):
    from tests.test_orchestrator_runtime import worker
    w1 = worker("w1")

    class LeakyStreamingAdapter:
        supports_cancel = False
        supports_streaming = True

        def complete(self, request, timeout, on_stream_start=None, on_stream_chunk=None, **kwargs):
            if on_stream_start:
                on_stream_start({})
            if on_stream_chunk:
                on_stream_chunk({"choices": [{"delta": {"content": "Your token is "}}]})
                on_stream_chunk({"choices": [{"delta": {"content": "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"}}]})
            return {"choices": [{"message": {"content": "done"}}], "usage": {}}

    scanner = GuardrailScanner(action="redact", detect_secrets=True)
    runtime = OrchestratorRuntime(
        CapabilityRegistry([w1]),
        {"w1": LeakyStreamingAdapter()},
        EvidenceStore(tmp_path / "evidence.jsonl"),
        guardrails=scanner,
    )

    received_chunks = []
    def record_chunk(c):
        received_chunks.append(c["choices"][0]["delta"]["content"])

    res = runtime.complete(
        {"model": "engineering/w1", "messages": [{"role": "user", "content": "give key"}], "stream": True},
        on_stream_start=lambda m: None,
        on_stream_chunk=record_chunk,
    )
    assert res["status"] == "ok"
    assert "Your token is " in received_chunks
    assert "[REDACTED_SECRET]" in received_chunks
    assert "ghp_" not in "".join(received_chunks)

