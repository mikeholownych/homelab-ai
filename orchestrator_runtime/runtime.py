from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from concurrent.futures import ThreadPoolExecutor

from orchestrator_contract import Authority, Task


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


@dataclass(frozen=True)
class WorkerRecord:
    worker_id: str
    public_model_id: str
    model_id: str
    revision: str
    artifact_digest: str
    runtime_image_digest: str
    topology: str
    gpu_assignment: tuple[str, ...]
    capabilities: frozenset[str]
    context_limit: int
    max_output_tokens: int
    max_concurrency: int
    resource_envelope: dict[str, Any]
    evidence_ids: tuple[str, ...]
    registry_version: int
    measured_at: str
    valid_until: str
    status: str = "measured"
    healthy: bool = True
    endpoint: str | None = None
    auth_token: str | None = None

    def __post_init__(self) -> None:
        if self.revision in {"", "main", "latest"}:
            raise ValueError("worker revision must be exact")
        if not self.evidence_ids:
            raise ValueError("worker capability records require evidence")

    @property
    def identity_hash(self) -> str:
        return _hash({
            "worker_id": self.worker_id,
            "public_model_id": self.public_model_id,
            "model_id": self.model_id,
            "revision": self.revision,
            "artifact_digest": self.artifact_digest,
            "runtime_image_digest": self.runtime_image_digest,
            "topology": self.topology,
            "gpu_assignment": self.gpu_assignment,
        })

    def eligible(self, required: frozenset[str], context_tokens: int, concurrency: int) -> bool:
        if self.status not in {"measured", "provisional"} or not self.healthy:
            return False
        if datetime.fromisoformat(self.valid_until.replace("Z", "+00:00")) <= datetime.now(timezone.utc):
            return False
        return (
            required <= self.capabilities
            and context_tokens <= self.context_limit
            and concurrency <= self.max_concurrency
        )


class CapabilityRegistry:
    def __init__(self, workers: list[WorkerRecord] | None = None) -> None:
        self._workers: dict[str, WorkerRecord] = {}
        self._lock = threading.RLock()
        for worker in workers or []:
            self.register(worker)

    def register(self, worker: WorkerRecord) -> None:
        with self._lock:
            self._workers[worker.worker_id] = worker

    def update_health(self, worker_id: str, healthy: bool) -> None:
        with self._lock:
            worker = self._workers[worker_id]
            self._workers[worker_id] = WorkerRecord(**{**worker.__dict__, "healthy": healthy})

    def select(
        self, required: frozenset[str], *, context_tokens: int = 0, concurrency: int = 1,
        public_model_id: str | None = None,
    ) -> WorkerRecord:
        with self._lock:
            candidates = [
                worker for worker in self._workers.values()
                if (public_model_id is None or worker.public_model_id == public_model_id)
                and worker.eligible(required, context_tokens, concurrency)
            ]
        if not candidates:
            raise LookupError("no worker proves the requested capability")
        return sorted(candidates, key=lambda worker: worker.worker_id)[0]

    def public_models(self) -> list[str]:
        with self._lock:
            return sorted({
                worker.public_model_id for worker in self._workers.values()
                if worker.eligible(frozenset(), 0, 1)
            })

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [worker.__dict__.copy() for worker in self._workers.values()]


class EvidenceStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else None
        self._records: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def append(self, event: str, **fields: Any) -> str:
        with self._lock:
            previous = self._records[-1]["record_hash"] if self._records else None
            record = {
                "evidence_id": str(uuid.uuid4()),
                "event": event,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "previous_hash": previous,
                **fields,
            }
            record["record_hash"] = _hash(record)
            self._records.append(record)
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(_canonical(record) + "\n")
            return record["evidence_id"]

    def records(self) -> list[dict[str, Any]]:
        with self._lock:
            return [record.copy() for record in self._records]


class ProviderAdapter(Protocol):
    def complete(self, request: dict[str, Any], timeout: float) -> dict[str, Any]: ...


@dataclass
class InMemoryAdapter:
    content: str
    calls: int = 0

    def complete(self, request: dict[str, Any], timeout: float) -> dict[str, Any]:
        self.calls += 1
        return {"content": self.content, "tool_calls": []}


@dataclass
class OpenAIProviderAdapter:
    endpoint: str
    auth_token: str

    def complete(self, request: dict[str, Any], timeout: float) -> dict[str, Any]:
        payload = json.dumps(request).encode()
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.auth_token}"}
        http_request = urllib.request.Request(
            self.endpoint.rstrip("/") + "/v1/chat/completions", payload, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(http_request, timeout=timeout) as response:
                provider_status = response.status
                body = json.loads(response.read().decode())
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as error:
            raise RuntimeError(f"provider request failed: {error}") from error
        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        return {
            "content": message.get("content", ""),
            "tool_calls": message.get("tool_calls", []),
            "provider_status": provider_status,
            "provider_finish_reason": choice.get("finish_reason"),
        }


@dataclass
class TaskNode:
    node_id: str
    capabilities: frozenset[str]
    dependencies: frozenset[str] = frozenset()
    state: str = "pending"
    artifact_id: str | None = None
    artifact_accepted: bool = False


class TaskGraph:
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self._nodes: dict[str, TaskNode] = {}

    def add(self, node_id: str, *, capabilities: set[str] | frozenset[str], dependencies: set[str] | frozenset[str] = frozenset()) -> None:
        if node_id in self._nodes or node_id in dependencies:
            raise ValueError("invalid or duplicate task node")
        if not dependencies <= self._nodes.keys():
            raise ValueError("dependencies must be declared before dependents")
        self._nodes[node_id] = TaskNode(node_id, frozenset(capabilities), frozenset(dependencies))

    def ready(self) -> list[TaskNode]:
        return [
            node for node in self._nodes.values()
            if node.state == "pending"
            and all(self._nodes[dep].state == "accepted" and self._nodes[dep].artifact_accepted for dep in node.dependencies)
        ]

    def start(self, node_id: str) -> None:
        node = self._nodes[node_id]
        if node not in self.ready():
            raise ValueError("task dependency gate is not satisfied")
        node.state = "running"

    def complete(self, node_id: str, *, artifact_content: str, accepted: bool) -> str:
        node = self._nodes[node_id]
        if node.state != "running":
            raise ValueError("task is not running")
        node.artifact_id = _hash({"task_id": self.task_id, "node_id": node_id, "content": artifact_content})
        node.artifact_accepted = accepted
        node.state = "accepted" if accepted else "blocked"
        return node.artifact_id

    def accept(self, node_id: str) -> None:
        node = self._nodes[node_id]
        if node.state != "blocked" or not node.artifact_id:
            raise ValueError("only a completed artifact can be accepted")
        node.state = "accepted"
        node.artifact_accepted = True

    def nodes(self) -> list[TaskNode]:
        return list(self._nodes.values())


class GraphScheduler:
    """Small dependency-gated scheduler; handlers run only after predecessors accept."""

    def run(self, graph: TaskGraph, handlers: dict[str, Any], *, mode: str = "dependency-gated", max_workers: int = 4) -> None:
        if mode not in {"serial", "parallel", "dependency-gated"}:
            raise ValueError("unsupported scheduling mode")
        while pending := graph.ready():
            if mode == "serial" or len(pending) == 1:
                selected = pending[:1]
            else:
                selected = pending
            for node in selected:
                graph.start(node.node_id)
            if len(selected) == 1:
                results = [(selected[0], handlers[selected[0].node_id]())]
            else:
                with ThreadPoolExecutor(max_workers=min(max_workers, len(selected))) as pool:
                    futures = [(node, pool.submit(handlers[node.node_id])) for node in selected]
                    results = [(node, future.result()) for node, future in futures]
            for node, result in results:
                graph.complete(node.node_id, artifact_content=str(result), accepted=True)


class OrchestratorRuntime:
    def __init__(self, registry: CapabilityRegistry, adapters: dict[str, ProviderAdapter], evidence: EvidenceStore, *, max_body_bytes: int = 1_000_000, validator: Any | None = None, diagnostic_lineage: bool = False) -> None:
        self.registry = registry
        self.adapters = adapters
        self.evidence = evidence
        self.max_body_bytes = max_body_bytes
        self.validator = validator
        self.diagnostic_lineage = diagnostic_lineage

    def complete(self, request: dict[str, Any], *, capabilities: frozenset[str] = frozenset({"navigation"}), timeout: float = 60.0) -> dict[str, Any]:
        request_id = request.get("request_id") or str(uuid.uuid4())
        messages = request.get("messages")
        if not isinstance(messages, list) or not messages:
            return {"status": "rejected", "failure_class": "request_shape", "request_id": request_id}
        context_tokens = sum(len(str(message.get("content", ""))) for message in messages) // 4
        public_model = request.get("model")
        try:
            worker = self.registry.select(capabilities, context_tokens=context_tokens, public_model_id=public_model)
        except LookupError:
            self.evidence.append("routing_rejected", request_id=request_id, failure_class="capability")
            return {"status": "unsupported", "failure_class": "capability", "request_id": request_id}
        adapter = self.adapters.get(worker.worker_id)
        if adapter is None:
            self.evidence.append("routing_rejected", request_id=request_id, failure_class="adapter_unavailable", worker_id=worker.worker_id)
            return {"status": "blocked", "failure_class": "adapter_unavailable", "request_id": request_id}
        self.evidence.append("worker_selected", request_id=request_id, worker_id=worker.worker_id, worker_identity=worker.identity_hash)
        started = time.monotonic()
        try:
            output = adapter.complete(request, timeout)
        except TimeoutError:
            self.evidence.append("execution_failed", request_id=request_id, worker_id=worker.worker_id, failure_class="timeout")
            return {"status": "blocked", "failure_class": "timeout", "request_id": request_id}
        except Exception as error:
            self.evidence.append("execution_failed", request_id=request_id, worker_id=worker.worker_id, failure_class="worker", error=type(error).__name__)
            return {"status": "blocked", "failure_class": "worker", "request_id": request_id}
        if self.validator is not None and not self.validator(output):
            self.evidence.append("response_rejected", request_id=request_id, worker_id=worker.worker_id, failure_class="external_validation")
            return {"status": "blocked", "failure_class": "external_validation", "request_id": request_id}
        tool_calls = output.get("tool_calls", [])
        normalized_finish_reason = "tool_calls" if tool_calls else "stop"
        response = {
            "id": "chatcmpl-" + request_id.replace("-", "")[:24],
            "object": "chat.completion",
            "created": int(time.time()),
            "model": worker.public_model_id,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": output.get("content", ""), "tool_calls": tool_calls}, "finish_reason": normalized_finish_reason}],
        }
        if self.diagnostic_lineage:
            self.evidence.append(
                "response_lineage",
                request_id=request_id,
                worker_id=worker.worker_id,
                model_id=worker.model_id,
                provider_status=output.get("provider_status"),
                provider_finish_reason=output.get("provider_finish_reason"),
                tool_call_count=len(tool_calls),
                tool_calls=[
                    {"id": call.get("id"), "name": (call.get("function") or {}).get("name")}
                    for call in tool_calls
                ],
                normalized_finish_reason=normalized_finish_reason,
            )
        self.evidence.append("response_validated", request_id=request_id, worker_id=worker.worker_id, elapsed_ms=round((time.monotonic() - started) * 1000, 3), response_hash=_hash(response))
        return {"status": "ok", "request_id": request_id, "response": response}

    def execute_tool(self, task: Task, authority: Authority, tool_name: str, arguments: dict[str, Any], executor: Any) -> dict[str, Any]:
        if not tool_name or not isinstance(arguments, dict) or not authority.allows(task, "execute"):
            self.evidence.append("execution_rejected", task_id=task.task_id, tool_name=tool_name, failure_class="authority")
            return {"status": "blocked", "failure_class": "authority"}
        self.evidence.append("execution_authorized", task_id=task.task_id, tool_name=tool_name, arguments_hash=_hash(arguments))
        try:
            result = executor(tool_name, arguments)
        except Exception as error:
            self.evidence.append("execution_failed", task_id=task.task_id, tool_name=tool_name, failure_class="execution", error=type(error).__name__)
            return {"status": "failed", "failure_class": "execution"}
        self.evidence.append("execution_verified", task_id=task.task_id, tool_name=tool_name, result_hash=_hash(result))
        return {"status": "executed", "result": result}
