from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from orchestrator_contract import Authority, Task

from orchestrator_runtime import (
    CapabilityRegistry,
    EvidenceStore,
    GraphScheduler,
    InMemoryAdapter,
    OpenAIProviderAdapter,
    OrchestratorRuntime,
    TaskGraph,
    WorkerRecord,
)


def worker(worker_id: str, *, capabilities=("navigation",), status="measured"):
    return WorkerRecord(
        worker_id=worker_id,
        public_model_id=f"engineering/{worker_id}",
        model_id=f"model/{worker_id}",
        revision="a" * 40,
        artifact_digest="sha256:" + "b" * 64,
        runtime_image_digest="sha256:" + "c" * 64,
        topology="tp1",
        gpu_assignment=(worker_id,),
        capabilities=frozenset(capabilities),
        context_limit=16_384,
        max_output_tokens=512,
        max_concurrency=2,
        resource_envelope={"memory_reserve_gib": 32},
        evidence_ids=(f"evidence-{worker_id}",),
        registry_version=1,
        measured_at="2026-09-25T00:00:00Z",
        valid_until=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        status=status,
    )


def test_registry_routes_only_current_validated_workers():
    registry = CapabilityRegistry()
    registry.register(worker("stale", status="expired"))
    registry.register(worker("ready"))

    selected = registry.select(frozenset({"navigation"}), context_tokens=100)

    assert selected.worker_id == "ready"
    assert registry.public_models() == ["engineering/ready"]


def test_graph_blocks_dependents_until_artifact_is_accepted():
    graph = TaskGraph("task-1")
    graph.add("inspect", capabilities={"navigation"})
    graph.add("patch", dependencies={"inspect"}, capabilities={"coding"})

    assert [node.node_id for node in graph.ready()] == ["inspect"]
    graph.start("inspect")
    graph.complete("inspect", artifact_content="proposal", accepted=False)
    assert graph.ready() == []
    graph.accept("inspect")
    assert [node.node_id for node in graph.ready()] == ["patch"]


def test_runtime_records_provenance_and_rejects_unavailable_capability(tmp_path):
    registry = CapabilityRegistry([worker("ready")])
    evidence = EvidenceStore(tmp_path / "evidence.jsonl")
    runtime = OrchestratorRuntime(registry, {"ready": InMemoryAdapter("answer")}, evidence)

    result = runtime.complete(
        {"messages": [{"role": "user", "content": "hello"}]},
        capabilities=frozenset({"vision"}),
    )

    assert result["status"] == "unsupported"
    assert result["failure_class"] == "capability"
    assert evidence.records()[0]["event"] == "routing_rejected"


def test_runtime_returns_openai_shape_for_one_worker(tmp_path):
    registry = CapabilityRegistry([worker("ready")])
    runtime = OrchestratorRuntime(
        registry,
        {"ready": InMemoryAdapter("hello")},
        EvidenceStore(tmp_path / "evidence.jsonl"),
    )

    result = runtime.complete(
        {"model": "engineering/ready", "messages": [{"role": "user", "content": "hi"}]}
    )

    assert result["status"] == "ok"
    choice = result["response"]["choices"][0]
    assert choice["message"]["content"] == "hello"
    assert choice["finish_reason"] == "stop"
    assert result["response"]["model"] == "engineering/ready"


def test_runtime_reports_tool_call_finish_reason(tmp_path):
    class ToolCallAdapter:
        def complete(self, request, timeout):
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "read", "arguments": "{}"},
                    }
                ],
            }

    registry = CapabilityRegistry([worker("ready")])
    runtime = OrchestratorRuntime(
        registry,
        {"ready": ToolCallAdapter()},
        EvidenceStore(tmp_path / "evidence.jsonl"),
    )

    result = runtime.complete(
        {"model": "engineering/ready", "messages": [{"role": "user", "content": "hi"}]}
    )

    choice = result["response"]["choices"][0]
    assert choice["message"]["tool_calls"] == [
        {
            "id": "call-1",
            "type": "function",
            "function": {"name": "read", "arguments": "{}"},
        }
    ]
    assert choice["finish_reason"] == "tool_calls"


def test_runtime_records_opt_in_response_lineage_without_arguments(tmp_path):
    class ToolCallAdapter:
        def complete(self, request, timeout):
            return {
                "content": "",
                "provider_status": 200,
                "provider_finish_reason": "tool_calls",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "read", "arguments": '{"path":"private"}'},
                    }
                ],
            }

    evidence = EvidenceStore(tmp_path / "evidence.jsonl")
    runtime = OrchestratorRuntime(
        CapabilityRegistry([worker("ready")]),
        {"ready": ToolCallAdapter()},
        evidence,
        diagnostic_lineage=True,
    )

    runtime.complete(
        {
            "request_id": "request-1",
            "model": "engineering/ready",
            "messages": [{"role": "user", "content": "hi"}],
        }
    )

    lineage = next(record for record in evidence.records() if record["event"] == "response_lineage")
    assert lineage == {
        **{key: lineage[key] for key in ("evidence_id", "recorded_at", "previous_hash", "record_hash")},
        "event": "response_lineage",
        "request_id": "request-1",
        "worker_id": "ready",
        "model_id": "model/ready",
        "provider_status": 200,
        "provider_finish_reason": "tool_calls",
        "tool_call_count": 1,
        "tool_calls": [{"id": "call-1", "name": "read"}],
        "normalized_finish_reason": "tool_calls",
    }
    assert "private" not in json.dumps(lineage)


def test_provider_adapter_captures_safe_response_metadata(monkeypatch):
    tool_call = {
        "id": "provider-call-1",
        "type": "function",
        "function": {"name": "read", "arguments": "{}"},
    }

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "finish_reason": "tool_calls",
                            "message": {"content": "", "tool_calls": [tool_call]},
                        }
                    ]
                }
            ).encode()

    monkeypatch.setattr("orchestrator_runtime.runtime.urllib.request.urlopen", lambda *args, **kwargs: Response())

    output = OpenAIProviderAdapter("http://provider", "token").complete(
        {"messages": [{"role": "user", "content": "hi"}]},
        timeout=1,
    )

    assert output == {
        "content": "",
        "tool_calls": [tool_call],
        "provider_status": 200,
        "provider_finish_reason": "tool_calls",
    }


def test_scheduler_runs_dependency_gated_graph_in_order():
    graph = TaskGraph("task-2")
    graph.add("inspect", capabilities={"navigation"})
    graph.add("review", dependencies={"inspect"}, capabilities={"navigation"})
    seen = []

    GraphScheduler().run(
        graph,
        {"inspect": lambda: seen.append("inspect"), "review": lambda: seen.append("review")},
    )

    assert seen == ["inspect", "review"]
    assert all(node.state == "accepted" for node in graph.nodes())


def test_external_validation_and_tool_authority_are_separate(tmp_path):
    registry = CapabilityRegistry([worker("ready")])
    evidence = EvidenceStore(tmp_path / "evidence.jsonl")
    runtime = OrchestratorRuntime(
        registry,
        {"ready": InMemoryAdapter("proposal")},
        evidence,
        validator=lambda response: response["content"] == "accepted",
    )
    result = runtime.complete({"messages": [{"role": "user", "content": "hi"}]})
    assert result["status"] == "blocked"
    assert result["failure_class"] == "external_validation"
    assert runtime.metrics.authority_validations_total.get(outcome="rejected") == 1.0

    task = Task("task-1", "repo", "a" * 40, frozenset(), frozenset({"read"}), 1)
    authority = Authority(task.task_id, task.state_hash, frozenset({"read"}), datetime.now(timezone.utc) + timedelta(minutes=1))
    denied = runtime.execute_tool(task, authority, "read_file", {"path": "README.md"}, lambda name, args: "ok")
    assert denied["status"] == "blocked"
    assert denied["failure_class"] == "authority"
    assert runtime.metrics.authority_rejections_total.get(reason="unauthorized_action") == 1.0


class _CapturingAdapter:
    def __init__(self, error=None):
        self.error = error
        self.seen = []

    def complete(self, request, timeout):
        self.seen.append((dict(request), timeout))
        if self.error:
            raise self.error
        return {"content": "ok", "tool_calls": []}


def _runtime_with(adapter, tmp_path):
    from orchestrator_runtime import ProviderError  # noqa: F401  (exported for callers)

    registry = CapabilityRegistry([worker("w1")])
    return OrchestratorRuntime(registry, {"w1": adapter}, EvidenceStore(tmp_path / "e.jsonl"))


def test_max_tokens_is_clamped_to_remaining_context(tmp_path):
    adapter = _CapturingAdapter()
    runtime = _runtime_with(adapter, tmp_path)
    prompt = "x" * 4 * 10_000  # about 10k tokens by the gateway's estimate; limit is 16384
    result = runtime.complete({"model": "engineering/w1", "max_tokens": 20_000, "messages": [{"role": "user", "content": prompt}]})

    assert result["status"] == "ok"
    sent, timeout = adapter.seen[0]
    assert sent["max_tokens"] == 16_384 - 10_000 - 256
    assert timeout == runtime.upstream_timeout >= 600


def test_provider_context_overflow_is_a_client_error_and_keeps_worker_healthy(tmp_path):
    from orchestrator_runtime import ProviderError

    body = json.dumps({"error": {"message": "This model's maximum context length is 16384 tokens. However, you requested 20000 tokens"}})
    adapter = _CapturingAdapter(ProviderError("provider HTTP 400: " + body, status=400, body=body))
    runtime = _runtime_with(adapter, tmp_path)
    result = runtime.complete({"model": "engineering/w1", "messages": [{"role": "user", "content": "hi"}]})

    assert result["status"] == "rejected"
    assert result["failure_class"] == "context_length_exceeded"
    assert "maximum context length" in result["message"]
    assert runtime.registry.snapshot()[0]["healthy"] is True


def test_provider_server_error_still_marks_worker_unhealthy(tmp_path):
    from orchestrator_runtime import ProviderError

    adapter = _CapturingAdapter(ProviderError("provider HTTP 500: boom", status=500, body="boom"))
    runtime = _runtime_with(adapter, tmp_path)
    result = runtime.complete({"model": "engineering/w1", "messages": [{"role": "user", "content": "hi"}]})

    assert result["status"] == "blocked"
    assert runtime.registry.snapshot()[0]["healthy"] is False
