from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from orchestrator_contract import Authority, Task

from orchestrator_runtime import (
    CapabilityRegistry,
    EvidenceStore,
    GraphScheduler,
    InMemoryAdapter,
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
    assert result["response"]["choices"][0]["message"]["content"] == "hello"
    assert result["response"]["model"] == "engineering/ready"


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

    task = Task("task-1", "repo", "a" * 40, frozenset(), frozenset({"read"}), 1)
    authority = Authority(task.task_id, task.state_hash, frozenset({"read"}), datetime.now(timezone.utc) + timedelta(minutes=1))
    denied = runtime.execute_tool(task, authority, "read_file", {"path": "README.md"}, lambda name, args: "ok")
    assert denied["status"] == "blocked"
    assert denied["failure_class"] == "authority"
