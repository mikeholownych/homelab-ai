from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from orchestrator_contract import Authority, Task

from .health import HealthManager
from .metrics import MetricsRegistry
from .routing import Router


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _affinity_key(request: dict[str, Any], explicit: str | None) -> str | None:
    """Stable per-conversation key: an explicit session id, else the leading system/user messages."""
    if explicit:
        return "session:" + explicit
    messages = request.get("messages")
    if not isinstance(messages, list) or not messages:
        return None
    head = [(m.get("role"), str(m.get("content", ""))[:2000]) for m in messages[:2] if isinstance(m, dict)]
    return "prefix:" + _hash([request.get("model"), head])


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
    pool: str = "lead"
    engine: str = "unknown"

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
        self._selection_cursors: dict[str | None, int] = {}
        self._lock = threading.RLock()
        for worker in workers or []:
            self.register(worker)

    def register(self, worker: WorkerRecord) -> None:
        with self._lock:
            self._workers[worker.worker_id] = worker

    def update_health(self, worker_id: str, healthy: bool) -> None:
        with self._lock:
            if worker_id in self._workers:
                worker = self._workers[worker_id]
                self._workers[worker_id] = WorkerRecord(**{**worker.__dict__, "healthy": healthy})

    def select(
        self, required: frozenset[str], *, context_tokens: int = 0, concurrency: int = 1,
        public_model_id: str | None = None, affinity_key: str | None = None, pool: str | None = None,
    ) -> WorkerRecord:
        with self._lock:
            candidates = [
                worker for worker in self._workers.values()
                if (public_model_id is None or worker.public_model_id == public_model_id)
                and (pool is None or worker.pool == pool)
                and worker.eligible(required, context_tokens, concurrency)
            ]
        if not candidates:
            raise LookupError("no worker proves the requested capability")
        if affinity_key:
            # Rendezvous hashing: a conversation keeps landing on the same worker so its prompt/prefix
            # cache stays warm, and losing a worker only remaps that worker's conversations.
            return max(candidates, key=lambda worker: _hash([affinity_key, worker.worker_id]))
        candidates = sorted(candidates, key=lambda worker: worker.worker_id)
        cursor = self._selection_cursors.get(public_model_id, 0)
        selected = candidates[cursor % len(candidates)]
        self._selection_cursors[public_model_id] = cursor + 1
        return selected

    def get(
        self, worker_id: str, required: frozenset[str], *, context_tokens: int = 0, concurrency: int = 1,
        public_model_id: str | None = None,
    ) -> WorkerRecord:
        with self._lock:
            worker = self._workers.get(worker_id)
        if (
            worker is None
            or (public_model_id is not None and worker.public_model_id != public_model_id)
            or not worker.eligible(required, context_tokens, concurrency)
        ):
            raise LookupError("requested worker is unavailable or lacks the requested capability")
        return worker

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


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


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
    model_id: str | None = None

    def complete(self, request: dict[str, Any], timeout: float) -> dict[str, Any]:
        provider_request = dict(request)
        if self.model_id is not None:
            provider_request["model"] = self.model_id
        # The runtime normalizes the provider response before the gateway emits SSE.
        provider_request["stream"] = False
        provider_request.pop("stream_options", None)
        payload = json.dumps(provider_request).encode()
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.auth_token}"}
        http_request = urllib.request.Request(
            self.endpoint.rstrip("/") + "/v1/chat/completions", payload, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(http_request, timeout=timeout) as response:
                provider_status = response.status
                body = json.loads(response.read().decode())
        except urllib.error.HTTPError as error:
            body = error.read().decode(errors="replace")[:512]
            raise ProviderError(f"provider HTTP {error.code}: {body}", status=error.code, body=body) from error
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise ProviderError(f"provider request failed: {error}") from error
        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        output = {
            "content": message.get("content", ""),
            "tool_calls": message.get("tool_calls", []),
            "provider_status": provider_status,
            "provider_finish_reason": choice.get("finish_reason"),
        }
        if message.get("reasoning_content"):
            output["reasoning_content"] = message["reasoning_content"]
        if isinstance(body.get("usage"), dict):
            output["usage"] = body["usage"]
        return output


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

    def __init__(self, metrics: MetricsRegistry | None = None) -> None:
        self.metrics = metrics

    def run(
        self,
        graph: TaskGraph,
        handlers: dict[str, Any],
        *,
        mode: str = "dependency-gated",
        max_workers: int = 4,
        metrics: MetricsRegistry | None = None,
    ) -> None:
        active_metrics = metrics or self.metrics
        if mode not in {"serial", "parallel", "dependency-gated"}:
            raise ValueError("unsupported scheduling mode")
        while pending := graph.ready():
            if active_metrics:
                active_metrics.scheduler_queued_work.set(len(pending))
                blocked = sum(1 for n in graph.nodes() if n.state == "pending" and n not in pending)
                active_metrics.scheduler_dependency_blocked_work.set(blocked)
            if mode == "serial" or len(pending) == 1:
                selected = pending[:1]
            else:
                selected = pending
            for node in selected:
                graph.start(node.node_id)
            if active_metrics:
                active_metrics.scheduler_active_work.inc(len(selected))
                active_metrics.scheduler_queued_work.set(max(0, len(pending) - len(selected)))
            try:
                if len(selected) == 1:
                    results = [(selected[0], handlers[selected[0].node_id]())]
                else:
                    with ThreadPoolExecutor(max_workers=min(max_workers, len(selected))) as pool:
                        futures = [(node, pool.submit(handlers[node.node_id])) for node in selected]
                        results = [(node, future.result()) for node, future in futures]
            finally:
                if active_metrics:
                    active_metrics.scheduler_active_work.dec(len(selected))
            for node, result in results:
                graph.complete(node.node_id, artifact_content=str(result), accepted=True)
        if active_metrics:
            active_metrics.scheduler_queued_work.set(0)
            blocked = sum(1 for n in graph.nodes() if n.state == "pending")
            active_metrics.scheduler_dependency_blocked_work.set(blocked)


class OrchestratorRuntime:
    def __init__(
        self,
        registry: CapabilityRegistry,
        adapters: dict[str, ProviderAdapter],
        evidence: EvidenceStore,
        *,
        max_body_bytes: int = 1_000_000,
        validator: Any | None = None,
        diagnostic_lineage: bool = False,
        metrics: MetricsRegistry | None = None,
        health: HealthManager | None = None,
        scheduling_mode: str | None = None,
        router: Router | None = None,
    ) -> None:
        self.router = router
        self.registry = registry
        self.adapters = adapters
        self.evidence = evidence
        self.max_body_bytes = max_body_bytes
        self.validator = validator
        self.diagnostic_lineage = diagnostic_lineage
        self.metrics = metrics or MetricsRegistry()
        self.scheduling_mode = scheduling_mode or os.environ.get("ORCHESTRATOR_SCHEDULING_MODE", "CONFIGURATION_B_PLUS")
        # Whole-response wait for non-streamed upstream calls. Long agent turns (large prefill plus
        # a long completion at tens of tokens/s) routinely exceed a minute, so the default is generous.
        self.upstream_timeout = float(os.environ.get("ORCHESTRATOR_UPSTREAM_TIMEOUT_SECONDS", "600"))
        self.health = health or HealthManager(self.registry, self.adapters, self.metrics, scheduling_mode=self.scheduling_mode)

    def complete(
        self,
        request: dict[str, Any],
        *,
        capabilities: frozenset[str] = frozenset({"navigation"}),
        timeout: float | None = None,
        worker_id: str | None = None,
        affinity: str | None = None,
        task_class: str | None = None,
    ) -> dict[str, Any]:
        timeout = self.upstream_timeout if timeout is None else timeout
        request_id = request.get("request_id") or str(uuid.uuid4())
        self.metrics.inference_requests_total.inc(status="received")
        messages = request.get("messages")
        if not isinstance(messages, list) or not messages:
            self.metrics.inference_requests_total.inc(status="rejected")
            self.metrics.scheduler_admission_backpressure_total.inc(reason="request_shape")
            return {"status": "rejected", "failure_class": "request_shape", "request_id": request_id}
        context_tokens = sum(len(str(message.get("content", ""))) for message in messages) // 4
        public_model = request.get("model")
        largest_window = max((w["context_limit"] for w in self.registry.snapshot()), default=0)
        if largest_window and context_tokens > largest_window:
            self.metrics.inference_requests_total.inc(status="rejected")
            self.evidence.append("routing_rejected", request_id=request_id, failure_class="context_length_exceeded")
            return {
                "status": "rejected",
                "failure_class": "context_length_exceeded",
                "request_id": request_id,
                "message": f"Prompt is about {context_tokens} tokens; the model context limit is {largest_window}. Reduce the conversation size.",
            }
        affinity_key = _affinity_key(request, affinity)
        route: dict[str, Any] = {"rule_id": "legacy", "pool": None, "fallback_used": False, "reason": "no route table configured"}
        try:
            if worker_id:
                worker = self.registry.get(worker_id, capabilities, context_tokens=context_tokens,
                                           public_model_id=None if self.router else public_model)
                route = {"rule_id": "pinned", "pool": worker.pool, "fallback_used": False, "reason": "explicit worker pin"}
            elif self.router is not None:
                decision = self.router.decide(model=public_model, task_class=task_class,
                                              has_tools=bool(request.get("tools")), prompt_tokens=context_tokens)
                worker = None
                for index, pool_name in enumerate(decision.pools):
                    try:
                        worker = self.registry.select(capabilities, context_tokens=context_tokens, pool=pool_name,
                                                      affinity_key=affinity_key)
                    except LookupError:
                        continue
                    route = {"rule_id": decision.rule_id, "pool": pool_name, "fallback_used": index > 0, "reason": decision.reason}
                    break
                if worker is None:
                    self.metrics.scheduler_dispatch_decisions_total.inc(worker_id="none", decision="rejected_pool_unavailable")
                    self.metrics.inference_completions_total.inc(worker_id="none", outcome="failed")
                    self.evidence.append("routing_rejected", request_id=request_id, failure_class="pool_unavailable",
                                         route_rule=decision.rule_id, route_pools=list(decision.pools))
                    return {"status": "blocked", "failure_class": "pool_unavailable", "request_id": request_id,
                            "message": f"No healthy worker is available in pool(s) {list(decision.pools)} (rule '{decision.rule_id}').",
                            "route": {"rule_id": decision.rule_id, "pool": decision.pool, "fallback_used": False, "reason": decision.reason}}
            else:
                worker = self.registry.select(
                    capabilities, context_tokens=context_tokens, public_model_id=public_model,
                    affinity_key=affinity_key,
                )
        except LookupError:
            self.metrics.scheduler_dispatch_decisions_total.inc(worker_id="none", decision="rejected_capability")
            self.metrics.inference_completions_total.inc(worker_id="none", outcome="failed")
            self.evidence.append("routing_rejected", request_id=request_id, failure_class="capability")
            return {"status": "unsupported", "failure_class": "capability", "request_id": request_id}

        adapter = self.adapters.get(worker.worker_id)
        if adapter is None:
            self.metrics.scheduler_dispatch_decisions_total.inc(worker_id=worker.worker_id, decision="rejected_unhealthy")
            self.metrics.inference_completions_total.inc(worker_id=worker.worker_id, outcome="failed")
            self.health.record_worker_observation(worker.worker_id, healthy=False, error="adapter_unavailable")
            self.evidence.append("routing_rejected", request_id=request_id, failure_class="adapter_unavailable", worker_id=worker.worker_id)
            return {"status": "blocked", "failure_class": "adapter_unavailable", "request_id": request_id}

        # Keep prompt + completion inside the worker's context window instead of letting the
        # provider reject the whole request. The prompt size is an estimate, so a residual
        # provider-side overflow is still reported as a client error below.
        for limit_key in ("max_tokens", "max_completion_tokens"):
            requested = request.get(limit_key)
            if isinstance(requested, int) and not isinstance(requested, bool) and requested > 0:
                room = worker.context_limit - context_tokens - 256
                if room < requested:
                    if room < 16:
                        self.evidence.append("routing_rejected", request_id=request_id, failure_class="context_length_exceeded", worker_id=worker.worker_id)
                        self.metrics.inference_completions_total.inc(worker_id=worker.worker_id, outcome="failed")
                        return {
                            "status": "rejected",
                            "failure_class": "context_length_exceeded",
                            "request_id": request_id,
                            "message": f"Prompt is about {context_tokens} tokens; the model context limit is {worker.context_limit}. Reduce the conversation size.",
                        }
                    request = {**request, limit_key: room}

        self.metrics.scheduler_dispatch_decisions_total.inc(worker_id=worker.worker_id, decision="dispatched")
        self.metrics.inference_dispatches_total.inc(worker_id=worker.worker_id, model=worker.public_model_id)
        self.metrics.route_decisions_total.inc(rule=str(route["rule_id"]), pool=str(route["pool"]))
        self.evidence.append("worker_selected", request_id=request_id, worker_id=worker.worker_id, worker_identity=worker.identity_hash,
                             route_rule=route["rule_id"], route_pool=route["pool"], route_fallback=route["fallback_used"])

        started = time.monotonic()
        self.metrics.scheduler_active_work.inc()
        try:
            output = adapter.complete(request, timeout)
            call_duration = time.monotonic() - started
            self.health.record_worker_observation(worker.worker_id, healthy=True, duration=call_duration)
        except TimeoutError:
            call_duration = time.monotonic() - started
            self.metrics.inference_completions_total.inc(worker_id=worker.worker_id, outcome="timed_out")
            self.health.record_worker_observation(worker.worker_id, healthy=False, duration=call_duration, error="timeout")
            self.evidence.append("execution_failed", request_id=request_id, worker_id=worker.worker_id, failure_class="timeout")
            return {"status": "blocked", "failure_class": "timeout", "request_id": request_id}
        except ProviderError as error:
            call_duration = time.monotonic() - started
            self.metrics.inference_completions_total.inc(worker_id=worker.worker_id, outcome="failed")
            if error.status is not None and 400 <= error.status < 500 and error.status not in (401, 403, 408, 429):
                # The worker answered correctly; the request was invalid for it (e.g. context overflow).
                self.health.record_worker_observation(worker.worker_id, healthy=True, duration=call_duration)
                failure_class = "context_length_exceeded" if "maximum context length" in error.body else "invalid_request"
                self.evidence.append("execution_failed", request_id=request_id, worker_id=worker.worker_id, failure_class=failure_class, error=type(error).__name__, detail=error.body[:512])
                message = error.body
                try:
                    message = json.loads(error.body)["error"]["message"]
                except (ValueError, KeyError, TypeError):
                    pass
                return {"status": "rejected", "failure_class": failure_class, "request_id": request_id, "message": str(message)[:1000]}
            self.health.record_worker_observation(worker.worker_id, healthy=False, duration=call_duration, error=str(error))
            self.evidence.append("execution_failed", request_id=request_id, worker_id=worker.worker_id, failure_class="provider", error=type(error).__name__, detail=str(error)[:512])
            return {"status": "blocked", "failure_class": "provider", "request_id": request_id}
        except Exception as error:
            call_duration = time.monotonic() - started
            self.metrics.inference_completions_total.inc(worker_id=worker.worker_id, outcome="failed")
            self.health.record_worker_observation(worker.worker_id, healthy=False, duration=call_duration, error=str(error))
            self.evidence.append("execution_failed", request_id=request_id, worker_id=worker.worker_id, failure_class="worker", error=type(error).__name__)
            return {"status": "blocked", "failure_class": "worker", "request_id": request_id}
        finally:
            self.metrics.scheduler_active_work.dec()

        if self.validator is not None:
            is_valid = bool(self.validator(output))
            self.metrics.authority_validations_total.inc(outcome="accepted" if is_valid else "rejected")
            if not is_valid:
                self.metrics.inference_completions_total.inc(worker_id=worker.worker_id, outcome="failed")
                self.evidence.append("response_rejected", request_id=request_id, worker_id=worker.worker_id, failure_class="external_validation")
                return {"status": "blocked", "failure_class": "external_validation", "request_id": request_id}
        else:
            self.metrics.authority_validations_total.inc(outcome="accepted")

        total_duration = time.monotonic() - started
        self.metrics.inference_duration_seconds.observe(total_duration, worker_id=worker.worker_id, model=worker.public_model_id)
        self.metrics.inference_completions_total.inc(worker_id=worker.worker_id, outcome="completed")

        prompt_tokens = context_tokens
        completion_content = str(output.get("content", ""))
        completion_tokens = max(1, len(completion_content) // 4) if completion_content else 0
        self.metrics.inference_prompt_tokens_total.inc(prompt_tokens, worker_id=worker.worker_id, model=worker.public_model_id)
        self.metrics.inference_completion_tokens_total.inc(completion_tokens, worker_id=worker.worker_id, model=worker.public_model_id)

        tool_calls = output.get("tool_calls", [])
        normalized_finish_reason = "tool_calls" if tool_calls else "stop"
        message = {"role": "assistant", "content": output.get("content", ""), "tool_calls": tool_calls}
        if output.get("reasoning_content"):
            message["reasoning_content"] = output["reasoning_content"]
        response = {
            "id": "chatcmpl-" + request_id.replace("-", "")[:24],
            "object": "chat.completion",
            "created": int(time.time()),
            "model": worker.public_model_id,
            "choices": [{"index": 0, "message": message, "finish_reason": normalized_finish_reason}],
        }
        if isinstance(output.get("usage"), dict):
            response["usage"] = output["usage"]
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
        return {"status": "ok", "request_id": request_id, "response": response, "route": {**route, "worker_id": worker.worker_id}}

    def execute_tool(self, task: Task, authority: Authority, tool_name: str, arguments: dict[str, Any], executor: Any) -> dict[str, Any]:
        if not tool_name or not isinstance(arguments, dict) or not authority.allows(task, "execute"):
            self.metrics.authority_rejections_total.inc(reason="unauthorized_action")
            self.evidence.append("execution_rejected", task_id=task.task_id, tool_name=tool_name, failure_class="authority")
            return {"status": "blocked", "failure_class": "authority"}
        self.metrics.authority_validations_total.inc(outcome="accepted")
        self.evidence.append("execution_authorized", task_id=task.task_id, tool_name=tool_name, arguments_hash=_hash(arguments))
        try:
            result = executor(tool_name, arguments)
        except Exception as error:
            self.evidence.append("execution_failed", task_id=task.task_id, tool_name=tool_name, failure_class="execution", error=type(error).__name__)
            return {"status": "failed", "failure_class": "execution"}
        self.evidence.append("execution_verified", task_id=task.task_id, tool_name=tool_name, result_hash=_hash(result))
        return {"status": "executed", "result": result}
