from __future__ import annotations

import hashlib
import http.client
import json
import os
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from orchestrator_contract import Authority, Task

from . import reasoning as reasoning_policy
from .admission import AdmissionCancelled, AdmissionController, AdmissionRejected, PoolUnavailable, PRIORITIES
from .capabilities import intersect, requirements as capability_requirements
from .capacity import CapacityTracker
from .clients import Client, QuotaExceeded, clamp_priority
from .engines import adapter_for
from .evidence import EvidenceStore, scrub
from .health import HealthManager
from .metrics import MetricsRegistry
from .routing import RouteDecision, Router

# Tokens kept free between prompt + completion and the context window (template/stop tokens the count may not see).
SAFETY_MARGIN_TOKENS = 16
# Smallest completion worth dispatching; below this the request is rejected as context overflow instead.
MIN_COMPLETION_TOKENS = 64
# Remembered requests for outcome reporting (R10) and escalation lookups (R3).
_OUTCOME_INDEX_SIZE = 10_000


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _completion_headers(plan: Any, worker: Any) -> dict[str, str]:
    return {
        "X-AIHost-Context-Limit": str(plan.context_length),
        "X-AIHost-Prompt-Tokens": str(plan.prompt_tokens) if plan.token_source == "exact" else f"~{plan.prompt_tokens}",
        "X-AIHost-Prompt-Tokens-Source": plan.token_source,
        "X-AIHost-Context-Remaining": str(max(0, plan.context_length - plan.prompt_tokens)),
        "X-AIHost-Max-Completion": str(plan.max_completion),
        "X-AIHost-Limits-Version": plan.limits_version,
        "X-AIHost-Served-Model": worker.model_id,
    }


def _affinity_key(request: dict[str, Any], explicit: str | None) -> str | None:
    """Stable per-conversation key: an explicit session id, else the leading system/user messages."""
    if explicit:
        return "session:" + explicit
    messages = request.get("messages")
    if not isinstance(messages, list) or not messages:
        return None
    head = [(m.get("role"), str(m.get("content", ""))[:2000]) for m in messages[:2] if isinstance(m, dict)]
    return "prefix:" + _hash([request.get("model"), head])


def _conservative_prompt_estimate(request: dict[str, Any]) -> int:
    """Fallback prompt size when the worker cannot count: the whole template-relevant request (messages incl. tool
    calls, tools schema) at 3 characters per token. Real tokenizers average ~3.5-4 for code/prose, so this over-counts
    on purpose: a sizing error must shrink the completion, never overflow the context."""
    relevant = {k: request[k] for k in ("messages", "tools", "tool_choice", "response_format") if k in request}
    return -(-len(_canonical(relevant)) // 3)


def _split_hit(key: str, percent: float) -> bool:
    """Deterministic percentage split (canary/shadow) on a stable key."""
    return int(_hash(["split", key])[:8], 16) % 10_000 < int(percent * 100)


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
    # Worker-side hard reasoning cap (--reasoning-budget); None = the model does not reason (Design 02 L1).
    reasoning_budget: int | None = None
    # production | candidate (R4): candidates are reachable only through explicit candidate aliases / canary / shadow.
    role: str = "production"

    def __post_init__(self) -> None:
        if self.revision in {"", "main", "latest"}:
            raise ValueError("worker revision must be exact")
        if not self.evidence_ids:
            raise ValueError("worker capability records require evidence")
        if self.role not in ("production", "candidate"):
            raise ValueError("worker role must be production or candidate")

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

    def record(self, worker_id: str) -> WorkerRecord | None:
        with self._lock:
            return self._workers.get(worker_id)

    def candidates(
        self, required: frozenset[str], *, pool: str | None = None, public_model_id: str | None = None,
        include_candidates: bool = True,
    ) -> list[WorkerRecord]:
        """Workers that pass the static gates (status, validity, inventory capabilities, health), unordered."""
        with self._lock:
            return [
                worker for worker in self._workers.values()
                if (public_model_id is None or worker.public_model_id == public_model_id)
                and (pool is None or worker.pool == pool)
                and (include_candidates or worker.role != "candidate")
                and worker.eligible(required, 0, 1)
            ]

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
        return self.prefer(candidates, affinity_key, public_model_id)[0]

    def prefer(self, candidates: list[WorkerRecord], affinity_key: str | None, cursor_key: str | None) -> list[WorkerRecord]:
        """Order candidates by preference: rendezvous hashing on the conversation (keeps its prefix cache warm and only
        remaps a lost worker's conversations), else round robin."""
        if affinity_key:
            return sorted(candidates, key=lambda worker: _hash([affinity_key, worker.worker_id]), reverse=True)
        ordered = sorted(candidates, key=lambda worker: worker.worker_id)
        with self._lock:
            cursor = self._selection_cursors.get(cursor_key, 0)
            self._selection_cursors[cursor_key] = cursor + 1
        start = cursor % len(ordered)
        return ordered[start:] + ordered[:start]

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
                if worker.role != "candidate" and worker.eligible(frozenset(), 0, 1)
            })

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [worker.__dict__.copy() for worker in self._workers.values()]


class ProviderAdapter(Protocol):
    def complete(self, request: dict[str, Any], timeout: float) -> dict[str, Any]: ...


def _token_counts(output: dict[str, Any], context_tokens: int) -> tuple[int, int, tuple[str, str]]:
    """Prompt and completion token counts plus where each came from.

    The engine's own ``usage`` is exact and wins. Only when it is missing do we estimate: the prompt from the
    gateway's pre-flight count, the completion from the characters of the content *and* tool-call arguments
    (a tool-call-only reply still generated tokens).
    """
    usage = output.get("usage") if isinstance(output.get("usage"), dict) else {}

    def exact(key: str) -> int | None:
        value = usage.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None

    prompt, completion = exact("prompt_tokens"), exact("completion_tokens")
    if completion is None:
        text = str(output.get("content", "") or "")
        for call in output.get("tool_calls") or []:
            function = call.get("function", {}) if isinstance(call, dict) else {}
            text += str(function.get("name", "")) + str(function.get("arguments", ""))
        completion_source, completion = "estimated", (max(1, len(text) // 4) if text else 0)
    else:
        completion_source = "provider"
    if prompt is None:
        return context_tokens, completion, ("estimated", completion_source)
    return prompt, completion, ("provider", completion_source)


class ProviderError(RuntimeError):
    """A worker call failed. ``pre_generation`` is True only when the worker provably produced nothing (the connection
    was refused, or it answered 503 before generating): only those failures may be retried elsewhere (R7)."""

    def __init__(self, message: str, *, status: int | None = None, body: str = "", pre_generation: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.body = body
        self.pre_generation = pre_generation


class RequestCancelled(RuntimeError):
    """The gateway closed the worker connection because the client left or the deadline passed (R1/R7)."""


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
    # The gateway can abort a call mid-generation by closing the worker connection (R1); engines stop generating
    # when the client connection closes.
    supports_cancel = True
    supports_streaming = True

    def _send(self, path: str, payload: bytes, headers: dict[str, str], timeout: float,
              cancel: threading.Event | None) -> tuple[int, bytes]:
        parts = urllib.parse.urlsplit(self.endpoint.rstrip("/") + path)
        connection_cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        connection = connection_cls(parts.hostname, parts.port, timeout=timeout)
        outcome: dict[str, Any] = {}

        def call() -> None:
            try:
                connection.request("POST", parts.path, body=payload, headers=headers)
                response = connection.getresponse()
                outcome["status"] = response.status
                outcome["body"] = response.read()
            except BaseException as error:  # noqa: BLE001 - re-raised in the caller thread below
                outcome["error"] = error

        worker = threading.Thread(target=call, daemon=True, name="worker-call")
        worker.start()
        deadline = time.monotonic() + timeout
        try:
            while worker.is_alive():
                worker.join(0.2)
                if not worker.is_alive():
                    break
                if cancel is not None and cancel.is_set():
                    raise RequestCancelled()
                if time.monotonic() >= deadline:
                    raise TimeoutError("worker call exceeded its deadline")
        except (RequestCancelled, TimeoutError):
            # Closing the socket is what makes the engine stop generating and free its slot.
            try:
                if connection.sock is not None:
                    connection.sock.shutdown(2)
            except OSError:
                pass
            connection.close()
            worker.join(2.0)
            raise
        connection.close()
        error = outcome.get("error")
        if isinstance(error, (ConnectionRefusedError, ConnectionResetError)) and "status" not in outcome:
            raise ProviderError(f"provider connection failed: {error}", pre_generation=True) from error
        if isinstance(error, TimeoutError):
            raise error
        if error is not None:
            raise ProviderError(f"provider request failed: {error}") from error
        return outcome["status"], outcome["body"]

    def complete(self, request: dict[str, Any], timeout: float, cancel: threading.Event | None = None,
                 on_stream_start: Callable[[], None] | None = None,
                 on_stream_chunk: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
        provider_request = dict(request)
        if self.model_id is not None:
            provider_request["model"] = self.model_id
        streaming = bool(request.get("stream"))
        provider_request["stream"] = streaming
        if streaming:
            if on_stream_start is None or on_stream_chunk is None:
                raise ProviderError("streaming requires gateway stream callbacks")
            return self._complete_stream(provider_request, timeout, cancel, on_stream_start, on_stream_chunk)
        provider_request.pop("stream_options", None)
        payload = json.dumps(provider_request).encode()
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.auth_token}"}
        status, raw = self._send("/v1/chat/completions", payload, headers, timeout, cancel)
        if status >= 400:
            body = raw.decode(errors="replace")[:512]
            raise ProviderError(f"provider HTTP {status}: {body}", status=status, body=body, pre_generation=status == 503)
        try:
            body = json.loads(raw.decode())
        except (ValueError, UnicodeDecodeError) as error:
            raise ProviderError(f"provider request failed: {error}") from error
        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        output = {
            "content": message.get("content", ""),
            "tool_calls": message.get("tool_calls", []),
            "provider_status": status,
            "provider_finish_reason": choice.get("finish_reason"),
        }
        if message.get("reasoning_content"):
            output["reasoning_content"] = message["reasoning_content"]
        if isinstance(body.get("usage"), dict):
            output["usage"] = body["usage"]
        if isinstance(body.get("timings"), dict):
            output["timings"] = body["timings"]
        return output

    def _complete_stream(self, provider_request: dict[str, Any], timeout: float,
                         cancel: threading.Event | None, on_start: Callable[[], None],
                         on_chunk: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        """Read real OpenAI-compatible SSE while forwarding deltas and retaining the full response for validation."""
        parts = urllib.parse.urlsplit(self.endpoint.rstrip("/") + "/v1/chat/completions")
        connection_cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        connection = connection_cls(parts.hostname, parts.port, timeout=timeout)
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.auth_token}"}
        payload = json.dumps(provider_request).encode()
        reader: threading.Thread | None = None
        messages: queue.Queue[tuple[str, Any]] = queue.Queue()
        deadline = time.monotonic() + timeout
        upstream_socket = None
        response = None
        try:
            try:
                connection.request("POST", parts.path, body=payload, headers=headers)
                upstream_socket = connection.sock
                response = connection.getresponse()
            except (ConnectionRefusedError, ConnectionResetError) as error:
                # Nothing generated and nothing sent to the client yet: safe to retry elsewhere (R7).
                raise ProviderError(f"provider connection failed: {error}", pre_generation=True) from error
            if response.status >= 400:
                body = response.read(512).decode(errors="replace")
                raise ProviderError(f"provider HTTP {response.status}: {body}", status=response.status,
                                    body=body, pre_generation=response.status == 503)
            on_start()

            def read_events() -> None:
                data_lines: list[bytes] = []
                try:
                    while True:
                        line = response.readline()
                        if not line:
                            if data_lines:
                                messages.put(("data", b"\n".join(data_lines)))
                            messages.put(("eof", None))
                            return
                        if line in (b"\n", b"\r\n"):
                            if data_lines:
                                messages.put(("data", b"\n".join(data_lines)))
                                data_lines.clear()
                        elif line.startswith(b"data:"):
                            data_lines.append(line[5:].strip())
                except BaseException as error:  # forwarded to the consumer thread
                    messages.put(("error", error))

            reader = threading.Thread(target=read_events, daemon=True, name="provider-sse-reader")
            reader.start()
            content: list[str] = []
            reasoning: list[str] = []
            tool_calls: dict[int, dict[str, Any]] = {}
            finish_reason: str | None = None
            usage: dict[str, Any] | None = None
            while True:
                if cancel is not None and cancel.is_set():
                    raise RequestCancelled()
                if time.monotonic() >= deadline:
                    raise TimeoutError("streaming worker call exceeded its deadline")
                try:
                    kind, value = messages.get(timeout=0.1)
                except queue.Empty:
                    continue
                if kind == "error":
                    if cancel is not None and cancel.is_set():
                        raise RequestCancelled()
                    raise ProviderError(f"provider stream failed: {type(value).__name__}") from value
                if kind == "eof":
                    break
                raw = value.decode(errors="replace")
                if raw == "[DONE]":
                    break
                try:
                    event = json.loads(raw)
                except ValueError as error:
                    raise ProviderError("provider returned malformed SSE data") from error
                choices = event.get("choices") or []
                if choices:
                    choice = choices[0]
                    delta = choice.get("delta") or {}
                    if isinstance(delta.get("content"), str):
                        content.append(delta["content"])
                    if isinstance(delta.get("reasoning_content"), str):
                        reasoning.append(delta["reasoning_content"])
                    for call in delta.get("tool_calls") or []:
                        index = int(call.get("index", 0))
                        current = tool_calls.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                        if call.get("id"):
                            current["id"] = call["id"]
                        function = call.get("function") or {}
                        current["function"]["name"] += function.get("name", "")
                        current["function"]["arguments"] += function.get("arguments", "")
                    if choice.get("finish_reason") is not None:
                        finish_reason = choice["finish_reason"]
                if isinstance(event.get("usage"), dict):
                    usage = event["usage"]
                # A normalized frame: the gateway owns its response id/model and sends its own final frame.
                if choices:
                    on_chunk({"choices": [{"index": choices[0].get("index", 0),
                                            "delta": choices[0].get("delta") or {}, "finish_reason": None}]})
            return {"content": "".join(content), "reasoning_content": "".join(reasoning),
                    "tool_calls": [tool_calls[i] for i in sorted(tool_calls)], "provider_status": response.status,
                    "provider_finish_reason": finish_reason, "usage": usage}
        except (RequestCancelled, TimeoutError):
            try:
                if upstream_socket is not None:
                    upstream_socket.shutdown(2)
            except OSError:
                pass
            raise
        finally:
            if response is not None:
                response.close()
            connection.close()
            if reader is not None:
                reader.join(1.0)


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


@dataclass
class _Plan:
    """A fully sized request for one worker: reasoning policy applied, prompt counted, completion bounded."""

    worker: WorkerRecord
    forwarded: dict[str, Any]
    thinking: bool
    reasoning_budget: int
    prompt_tokens: int
    token_source: str
    context_length: int
    max_completion: int
    limits_version: str
    clamped: tuple[str, ...]


@dataclass
class _ContextReject:
    prompt_tokens: int
    token_source: str
    context_length: int
    requested: int | None
    available: int
    worker_id: str
    limits_version: str


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
        engines: dict[str, Any] | None = None,
        capability_evidence: dict[str, dict[str, Any]] | None = None,
        admission: AdmissionController | None = None,
        prompt_policy: str | None = None,
        state_path: str | Path | None = None,
        budget_message: str | None = None,
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
        self.prompt_policy = prompt_policy or os.environ.get("ORCHESTRATOR_PROMPT_POLICY", "hash")
        self.budget_message = budget_message or os.environ.get("ORCHESTRATOR_REASONING_BUDGET_MESSAGE",
                                                              reasoning_policy.DEFAULT_BUDGET_MESSAGE)
        self.admission = admission or AdmissionController(
            queue_max=int(os.environ.get("ORCHESTRATOR_QUEUE_MAX", "32")),
            max_wait_seconds=float(os.environ.get("ORCHESTRATOR_QUEUE_MAX_WAIT_SECONDS", "120")),
            metrics=self.metrics,
        )
        if engines is None:
            engines = {}
            for record in self.registry.snapshot():
                adapter = adapter_for(record.get("engine", "unknown"), record.get("endpoint"), record.get("auth_token"))
                if adapter is not None:
                    engines[record["worker_id"]] = adapter
        self.capacity = CapacityTracker(self.registry.snapshot, engines, evidence=self.evidence, metrics=self.metrics,
                                        verified=capability_evidence)
        self.state_path = Path(state_path) if state_path else None
        self.shutting_down = threading.Event()
        self._inflight: dict[str, dict[str, Any]] = {}
        self._inflight_lock = threading.Lock()
        self._outcome_index: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._outcome_totals: dict[tuple[str, str, str], dict[str, int]] = {}
        self._outcome_lock = threading.Lock()
        self.metrics.evidence_chain_valid.set(1.0 if getattr(self.evidence, "chain_valid", True) else 0.0)
        self._load_state()
        self.refresh_capacity()
        if hasattr(self.health, "cycle_hooks"):
            self.health.cycle_hooks.append(self.refresh_capacity)
            self.health.worker_detail = self.worker_detail

    # ================================================================== capacity / state
    def refresh_capacity(self) -> None:
        self.capacity.refresh_all()
        drained = self.admission.drained()
        for record in self.registry.snapshot():
            state = self.capacity.state(record["worker_id"])
            if state is not None:
                self.admission.set_slots(record["worker_id"], state.slots_total)
            self.metrics.worker_drained.set(1.0 if record["worker_id"] in drained else 0.0, worker_id=record["worker_id"])

    def _load_state(self) -> None:
        if not self.state_path or not self.state_path.exists():
            return
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for worker_id in state.get("drained", {}):
            if self.registry.record(worker_id) is not None:
                self.admission.drain(worker_id)

    def save_state(self) -> None:
        if not self.state_path:
            return
        tmp = self.state_path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps({"drained": self.admission.drained()}), encoding="utf-8")
            tmp.replace(self.state_path)
        except OSError:
            pass

    def worker_detail(self, worker_id: str) -> dict[str, Any]:
        """Per-worker fields for /health: what the gateway observes and enforces (Design 01 section 6)."""
        record = self.registry.record(worker_id)
        if record is not None and record.status == "stopped":
            return {
                "registered": True,
                "endpoint": record.endpoint,
                "role": record.role,
                "expected_state": "stopped",
                "blocked_reason": "operator_stopped",
                "drain": {"state": "drained" if worker_id in self.admission.drained() else "active",
                          "since": self.admission.drained().get(worker_id),
                          "inflight": self.admission.inflight(worker_id)},
            }
        state = self.capacity.state(worker_id)
        drained = self.admission.drained()
        detail: dict[str, Any] = {
            "registered": True,
            "endpoint": record.endpoint if record else None,
            "role": record.role if record else None,
            "reasoning_budget": record.reasoning_budget if record else None,
            "capacity": None if state is None else {
                **state.as_dict(), "inflight": self.admission.inflight(worker_id),
                "concurrency_limit": self.admission.limit(worker_id),
            },
            "inventory_mismatch": self.capacity.mismatch(worker_id),
            "blocked_reason": self.capacity.blocked_reason(worker_id),
            "capabilities": {name: cap.as_dict() for name, cap in self.capacity.capabilities(worker_id).items()},
            "drain": {"state": "drained" if worker_id in drained else "active",
                      "since": drained.get(worker_id), "inflight": self.admission.inflight(worker_id)},
        }
        return detail

    # ================================================================== R5 drain
    def drain(self, worker_id: str, *, actor: str = "admin") -> dict[str, Any]:
        if self.registry.record(worker_id) is None:
            return {"status": "not_found", "worker_id": worker_id}
        self.admission.drain(worker_id)
        self.save_state()
        self.metrics.worker_drained.set(1.0, worker_id=worker_id)
        self.evidence.append("worker_drained", worker_id=worker_id, actor=actor, inflight=self.admission.inflight(worker_id))
        return {"status": "drained", "worker_id": worker_id, "inflight": self.admission.inflight(worker_id)}

    def undrain(self, worker_id: str, *, actor: str = "admin") -> dict[str, Any]:
        if self.registry.record(worker_id) is None:
            return {"status": "not_found", "worker_id": worker_id}
        self.admission.undrain(worker_id)
        self.save_state()
        self.metrics.worker_drained.set(0.0, worker_id=worker_id)
        self.evidence.append("worker_undrained", worker_id=worker_id, actor=actor)
        return {"status": "active", "worker_id": worker_id}

    # ================================================================== R12 graceful stop
    def begin_shutdown(self) -> None:
        self.shutting_down.set()

    def inflight_count(self) -> int:
        with self._inflight_lock:
            return len(self._inflight)

    def wait_idle(self, grace_seconds: float) -> bool:
        deadline = time.monotonic() + grace_seconds
        while time.monotonic() < deadline:
            if self.inflight_count() == 0:
                return True
            time.sleep(0.2)
        with self._inflight_lock:
            entries = list(self._inflight.values())
        for entry in entries:
            entry["cancel"].set()
            entry["cancel_reason"] = "gateway_shutdown"
        return False

    # ================================================================== R10 outcomes
    def report_outcome(self, client: Client | None, request_id: str, outcome: str, detail: str | None = None) -> dict[str, Any]:
        if outcome not in ("pass", "fail", "partial"):
            return {"status": "rejected", "message": "outcome must be pass|fail|partial"}
        client_id = client.client_id if client else "default"
        with self._outcome_lock:
            served = self._outcome_index.get(request_id)
            if served is None or served["client_id"] != client_id:
                return {"status": "not_found", "message": "unknown request id for this client"}
            served["outcome"] = outcome
            key = (served["rule"], served["pool"], served["model"])
            totals = self._outcome_totals.setdefault(key, {"pass": 0, "fail": 0, "partial": 0})
            totals[outcome] += 1
        self.metrics.outcomes_total.inc(rule=served["rule"], pool=served["pool"], model=served["model"], outcome=outcome)
        self.evidence.append("outcome_reported", request_id=request_id, client_id=client_id, outcome=outcome,
                             route_rule=served["rule"], route_pool=served["pool"], worker_id=served["worker_id"],
                             model_artifact=served["artifact"], source="client_reported",
                             detail=scrub(detail, self.prompt_policy) if detail else None)
        return {"status": "recorded", "request_id": request_id, "outcome": outcome}

    def outcome_summary(self) -> list[dict[str, Any]]:
        with self._outcome_lock:
            rows = []
            for (rule, pool, model), counts in sorted(self._outcome_totals.items()):
                total = sum(counts.values())
                rows.append({"rule": rule, "pool": pool, "model": model, **counts, "total": total,
                             "pass_rate": round(counts["pass"] / total, 4) if total else None,
                             "source": "client_reported"})
            return rows

    def _remember(self, request_id: str, entry: dict[str, Any]) -> None:
        with self._outcome_lock:
            self._outcome_index[request_id] = entry
            while len(self._outcome_index) > _OUTCOME_INDEX_SIZE:
                self._outcome_index.popitem(last=False)

    def previous_outcome(self, request_id: str | None, client_id: str) -> str | None:
        if not request_id:
            return None
        with self._outcome_lock:
            entry = self._outcome_index.get(request_id)
            return entry.get("outcome") if entry and entry["client_id"] == client_id else None

    # ================================================================== client-facing views
    def alias_view(self, client: Client | None = None) -> list[dict[str, Any]]:
        """/v1/models: per alias the limits and capabilities the gateway can guarantee (intersection / minimum over
        every worker the alias can reach). Candidate aliases are shown only to qualification-scoped clients."""
        scopes = client.scopes if client else frozenset({"workload"})
        entries: dict[str, list[str]] = {}
        if self.router is not None:
            for name, spec in self.router.alias_specs.items():
                if spec.scope == "qualification" and "qualification" not in scopes:
                    continue
                entries[name] = [spec.pool]
            for rule in self.router.rules:
                if rule.models:
                    for model in rule.models:
                        entries.setdefault(model, [rule.pool, *rule.fallback])
        for model in self.registry.public_models():
            if model not in entries:
                pools = [] if self.router is None else None
                entries[model] = pools if pools is not None else sorted({w["pool"] for w in self.registry.snapshot()
                                                                          if w["public_model_id"] == model})
        views = []
        for name, pools in sorted(entries.items()):
            workers = [w for w in self.registry.snapshot()
                       if (w["pool"] in pools if pools else w["public_model_id"] == name)]
            views.append(self._describe_alias(name, workers))
        return views

    def _describe_alias(self, name: str, workers: list[dict[str, Any]]) -> dict[str, Any]:
        states = [self.capacity.state(w["worker_id"]) for w in workers]
        known = [s for s in states if s is not None]
        context = min((s.ctx_per_slot for s in known), default=0)
        # The policy a plain request for this model gets: an alias's own policy, else the rule table's decision for a
        # first attempt with no task class (what the client receives unless it sends routing signals). Reporting a
        # blank "default" here once told clients engineering/b0 reasoned while the default rule turned it off.
        policy = (self.router.decide(model=name, task_class=None, has_tools=False, prompt_tokens=0).policy
                  if self.router else reasoning_policy.RoutePolicy())
        caps = intersect(self.capacity.capabilities(w["worker_id"]) for w in workers)
        budgets = [w.get("reasoning_budget") for w in workers if w.get("reasoning_budget")]
        reasoning_budget = min(budgets) if budgets and len(budgets) == len(workers) else 0
        if policy.budget:
            reasoning_budget = min(reasoning_budget, policy.budget) if reasoning_budget else 0
        max_completion = max(0, min(context - SAFETY_MARGIN_TOKENS, (reasoning_budget if policy.mode != "off" else 0) + policy.answer_allowance)) if context else 0
        version = _hash(sorted(s.limits_version for s in known))[:16] if known else None
        return {
            "id": name, "object": "model", "owned_by": "aihost-orchestrator",
            "context_length": context or None, "max_model_len": context or None,
            "max_completion_tokens": max_completion or None, "limits_version": version,
            "reasoning": {"budget": reasoning_budget, "mode": policy.mode},
            "serving": [{"worker_id": w["worker_id"], "pool": w["pool"], "role": w.get("role", "production"),
                         "model_id": w["model_id"], "artifact_digest": w["artifact_digest"],
                         "quantization": s.quantization if s else None, "engine": s.engine if s else w.get("engine"),
                         "engine_version": s.engine_version if s else None, "capacity_source": s.source if s else "unknown"}
                        for w, s in zip(workers, states)],
            "capabilities": {cap: value.as_dict() for cap, value in caps.items()},
        }

    def count_tokens(self, request: dict[str, Any], client: Client | None = None) -> dict[str, Any]:
        """POST /v1/tokenize: the exact prompt size of a request on a worker its model/alias reaches."""
        model = request.get("model")
        for view in self.alias_view(client):
            if view["id"] != model:
                continue
            for served in view["serving"]:
                record = self.registry.record(served["worker_id"])
                if record is None or self.capacity.blocked_reason(record.worker_id):
                    continue
                engine = self.capacity.engines.get(record.worker_id)
                count = engine.count_prompt(request) if engine else None
                source = "exact" if count is not None else "estimated_conservative"
                return {"model": model, "prompt_tokens": count if count is not None else _conservative_prompt_estimate(request),
                        "source": source, "context_length": view["context_length"], "limits_version": view["limits_version"],
                        "worker_id": record.worker_id}
        return {"status": "not_found", "message": f"unknown model {model!r}"}

    # ================================================================== request path
    def _requirements_ok(self, worker_id: str, needs: frozenset[str]) -> list[str]:
        caps = self.capacity.capabilities(worker_id)
        return sorted(name for name in needs if not caps.get(name) or not caps[name].available)

    def _eligible(self, pool: str | None, required: frozenset[str], public_model: str | None,
                  needs: frozenset[str], include_candidates: bool, missing: set[str]) -> list[WorkerRecord]:
        drained = self.admission.drained()
        out = []
        for worker in self.registry.candidates(required, pool=pool, public_model_id=public_model,
                                               include_candidates=include_candidates):
            if worker.worker_id in drained or self.capacity.blocked_reason(worker.worker_id):
                continue
            lacking = self._requirements_ok(worker.worker_id, needs)
            if lacking:
                missing.update(lacking)
                continue
            out.append(worker)
        return out

    def _plan(self, request: dict[str, Any], worker: WorkerRecord, policy: reasoning_policy.RoutePolicy,
              profile: str | None) -> _Plan | _ContextReject:
        caps = self.capacity.capabilities(worker.worker_id)
        # Deliberately wider than the capability gate: a worker configured with a server budget may reason, so it is
        # bounded (fail closed). Routing a reasoning requirement to it still needs the engine's declaration or
        # verified evidence; configuration is not proof the model reasons.
        worker_reasons = worker.reasoning_budget is not None or bool(caps.get("reasoning") and caps["reasoning"].available)
        applied = reasoning_policy.apply(request, policy, worker_cap=worker.reasoning_budget,
                                         worker_reasons=worker_reasons, profile=profile)
        forwarded = applied.request
        for key in ("request_id",):
            forwarded.pop(key, None)
        engine = self.capacity.engines.get(worker.worker_id)
        counted = engine.count_prompt(forwarded) if engine is not None else None
        source = "exact" if counted is not None else "estimated_conservative"
        prompt_tokens = counted if counted is not None else _conservative_prompt_estimate(forwarded)
        self.metrics.prompt_token_counts_total.inc(source=source)
        state = self.capacity.state(worker.worker_id)
        context = state.ctx_per_slot if state is not None else worker.context_limit
        limits_version = state.limits_version if state is not None else "unknown"
        available = context - prompt_tokens - SAFETY_MARGIN_TOKENS
        asked = [v for k in ("max_tokens", "max_completion_tokens")
                 if isinstance(v := request.get(k), int) and not isinstance(v, bool) and v > 0]
        requested = min(asked) if asked else None
        if available < MIN_COMPLETION_TOKENS:
            return _ContextReject(prompt_tokens, source, context, requested, max(0, available), worker.worker_id, limits_version)
        bound = min(applied.output_cap, available, requested or applied.output_cap)
        forwarded["max_tokens"] = bound
        if "max_completion_tokens" in forwarded:
            forwarded["max_completion_tokens"] = bound
        clamped = applied.clamped + (("max_tokens",) if requested and requested > bound else ())
        return _Plan(worker, forwarded, applied.thinking, applied.budget, prompt_tokens, source, context, bound,
                     limits_version, clamped)

    def _reject_context(self, request_id: str, reject: _ContextReject, client_id: str) -> dict[str, Any]:
        self.metrics.inference_requests_total.inc(status="rejected")
        self.evidence.append("routing_rejected", request_id=request_id, client_id=client_id,
                             failure_class="context_length_exceeded", worker_id=reject.worker_id,
                             prompt_tokens=reject.prompt_tokens, token_source=reject.token_source,
                             context_length=reject.context_length, available_completion=reject.available)
        return {
            "status": "rejected", "failure_class": "context_length_exceeded", "request_id": request_id, "http_status": 400,
            "message": (f"Prompt is {reject.prompt_tokens} tokens ({reject.token_source}); the model context limit is "
                        f"{reject.context_length}. {reject.available} tokens remain for the completion (minimum "
                        f"{MIN_COMPLETION_TOKENS}). Reduce the conversation size."),
            "details": {"prompt_tokens": reject.prompt_tokens, "prompt_tokens_source": reject.token_source,
                        "context_length": reject.context_length, "requested_completion": reject.requested,
                        "available_completion": reject.available, "min_completion": MIN_COMPLETION_TOKENS,
                        "worker_id": reject.worker_id, "limits_version": reject.limits_version},
        }

    def complete(
        self,
        request: dict[str, Any],
        *,
        capabilities: frozenset[str] = frozenset({"navigation"}),
        timeout: float | None = None,
        worker_id: str | None = None,
        affinity: str | None = None,
        task_class: str | None = None,
        client: Client | None = None,
        priority: str | None = None,
        deadline_ms: int | None = None,
        attempt: int = 1,
        previous_request: str | None = None,
        reasoning_profile: str | None = None,
        cancel: threading.Event | None = None,
        on_stream_start: Callable[[dict[str, Any]], None] | None = None,
        on_stream_chunk: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        timeout = self.upstream_timeout if timeout is None else timeout
        request_id = request.get("request_id") or str(uuid.uuid4())
        client_id = client.client_id if client else "default"
        cancel = cancel or threading.Event()
        self.metrics.inference_requests_total.inc(status="received")
        if self.shutting_down.is_set():
            return {"status": "unavailable", "failure_class": "gateway_restarting", "request_id": request_id,
                    "http_status": 503, "retry_after": 15, "message": "gateway is restarting; retry shortly"}
        messages = request.get("messages")
        if not isinstance(messages, list) or not messages:
            self.metrics.inference_requests_total.inc(status="rejected")
            self.metrics.scheduler_admission_backpressure_total.inc(reason="request_shape")
            return {"status": "rejected", "failure_class": "request_shape", "request_id": request_id}

        # R6 quotas, R2 priority (monotonic), R7 deadline
        clamped_fields: list[str] = []
        if client is not None:
            try:
                self.registry_clients_admit(client)
            except QuotaExceeded as error:
                self.metrics.admission_rejections_total.inc(code="quota_exceeded", pool="-")
                self.evidence.append("admission_rejected", request_id=request_id, client_id=client_id, failure_class="quota_exceeded")
                return {"status": "limited", "failure_class": "quota_exceeded", "request_id": request_id, "http_status": 429,
                        "retry_after": error.retry_after, "message": str(error)}
            priority, was_clamped = clamp_priority(priority, client, PRIORITIES)
            if was_clamped:
                clamped_fields.append("priority")
        elif priority not in PRIORITIES:
            priority = "interactive"
        deadline = None
        if deadline_ms is not None:
            deadline = time.monotonic() + max(0, deadline_ms) / 1000.0
            timeout = min(timeout, max(0.001, deadline_ms / 1000.0))

        estimate = _conservative_prompt_estimate(request)
        public_model = request.get("model")
        affinity_key = _affinity_key(request, affinity)
        include_candidates = False
        policy = reasoning_policy.RoutePolicy()
        decision: RouteDecision | None = None
        if worker_id:
            pinned = self.registry.record(worker_id)
            if pinned is None or not pinned.eligible(capabilities, 0, 1):
                return self._capability_reject(request_id, client_id)
            pools: list[str | None] = [pinned.pool]
            route: dict[str, Any] = {"rule_id": "pinned", "pool": pinned.pool, "fallback_used": False, "reason": "explicit worker pin"}
            include_candidates = True
        elif self.router is not None:
            decision = self.router.decide(model=public_model, task_class=task_class, has_tools=bool(request.get("tools")),
                                          prompt_tokens=estimate, attempt=attempt,
                                          previous_outcome=self.previous_outcome(previous_request, client_id))
            if decision.scope == "qualification":
                if client is not None and "qualification" not in client.scopes:
                    self.evidence.append("routing_rejected", request_id=request_id, client_id=client_id, failure_class="scope",
                                         route_rule=decision.rule_id)
                    return {"status": "forbidden", "failure_class": "scope", "request_id": request_id, "http_status": 403,
                            "message": f"model {public_model!r} requires the qualification scope"}
                include_candidates = True
            policy = decision.policy
            pools = list(decision.pools)
            route = {"rule_id": decision.rule_id, "pool": decision.pool, "fallback_used": False, "reason": decision.reason}
            if decision.canary and _split_hit(affinity_key or request_id, decision.canary[1]):
                pools = [decision.canary[0], *pools]
                include_candidates = True
                route["canary"] = decision.canary[0]
        else:
            pools = [None]
            route = {"rule_id": "legacy", "pool": None, "fallback_used": False, "reason": "no route table configured"}

        try:
            needs = capability_requirements(request, reasoning_requested=policy.mode == "on" and reasoning_profile != "off")
        except Exception:  # noqa: BLE001 - malformed parts are the provider's problem, not a routing requirement
            needs = frozenset()
        if reasoning_profile is not None and reasoning_profile not in reasoning_policy.PROFILES:
            return {"status": "rejected", "failure_class": "invalid_reasoning_profile", "request_id": request_id,
                    "http_status": 400, "message": f"unknown reasoning profile {reasoning_profile!r}"}

        missing: set[str] = set()
        context_reject: _ContextReject | None = None
        any_candidate = False
        excluded: set[str] = set()
        retried = False
        index = 0
        while index < len(pools):
            pool = pools[index]
            ordered_all = self._eligible(pool, capabilities, public_model if (pool is None and worker_id is None) else None,
                                         needs, include_candidates or (pool is not None and route.get("canary") == pool), missing)
            if worker_id:
                ordered_all = [w for w in ordered_all if w.worker_id == worker_id]
            ordered_all = [w for w in ordered_all if w.worker_id not in excluded]
            if not ordered_all:
                index += 1
                continue
            any_candidate = True
            ordered = self.registry.prefer(ordered_all, affinity_key, public_model if pool is None else pool)
            plan = self._plan(request, ordered[0], policy, reasoning_profile)
            if isinstance(plan, _ContextReject):
                context_reject = plan  # fit-checked fallback: a later pool may have a larger window
                index += 1
                continue
            # Workers that can take this exact sized request: same served model (same tokenizer, so the count holds)
            # and a window at least as large. Anything else is re-planned only if it ends up being granted.
            planned_state = self.capacity.state(plan.worker.worker_id)
            same_model = [w for w in ordered if w.worker_id == plan.worker.worker_id or (
                planned_state is not None and (s := self.capacity.state(w.worker_id)) is not None
                and s.model_alias == planned_state.model_alias and s.ctx_per_slot >= planned_state.ctx_per_slot)]
            ticket = self.admission.new_ticket(pool or "default", priority=priority, client_id=client_id, deadline=deadline)
            ticket.cancelled = cancel
            entry = {"cancel": cancel, "client_id": client_id, "started": time.monotonic(), "cancel_reason": None}
            with self._inflight_lock:
                self._inflight[request_id] = entry
            try:
                granted_id = self.admission.acquire(ticket, lambda: [w.worker_id for w in same_model
                                                                     if w.worker_id not in self.admission.drained()
                                                                     and not self.capacity.blocked_reason(w.worker_id)])
            except PoolUnavailable:
                self._forget(request_id)
                index += 1
                continue
            except AdmissionCancelled:
                self._forget(request_id)
                return self._cancelled(request_id, client_id, pool, entry.get("cancel_reason") or
                                       ("gateway_shutdown" if self.shutting_down.is_set() else "client_disconnect"), queued=True)
            except AdmissionRejected as rejection:
                self._forget(request_id)
                if rejection.code == "capacity_exhausted" and decision is not None and decision.fallback_on_saturation \
                        and index + 1 < len(pools):
                    self.evidence.append("saturation_fallback", request_id=request_id, client_id=client_id, from_pool=pool)
                    index += 1
                    continue
                self.metrics.admission_rejections_total.inc(code=rejection.code, pool=str(pool))
                self.evidence.append("admission_rejected", request_id=request_id, client_id=client_id,
                                     failure_class=rejection.code, route_pool=pool)
                return {"status": "limited" if rejection.status == 429 else "deadline", "failure_class": rejection.code,
                        "request_id": request_id, "http_status": rejection.status, "retry_after": rejection.retry_after,
                        "message": rejection.message, "route": route}
            worker = self.registry.record(granted_id) or plan.worker
            if worker.worker_id != plan.worker.worker_id:
                replanned = self._plan(request, worker, policy, reasoning_profile)
                if isinstance(replanned, _ContextReject):
                    self.admission.release(worker.worker_id, ok=True)
                    self._forget(request_id)
                    context_reject = replanned
                    index += 1
                    continue
                plan = replanned
            route_now = {**route, "pool": pool if pool is not None else worker.pool, "fallback_used": index > 0 and not route.get("canary")}
            outcome = self._dispatch(request_id, plan, route_now, client, client_id, priority, timeout, cancel, entry,
                                     clamped_fields, deadline, decision, request, on_stream_start, on_stream_chunk)
            if outcome.get("status") == "retry" and not retried:
                retried = True
                excluded.add(worker.worker_id)
                self.metrics.retries_total.inc(reason=outcome.get("failure_class", "pre_generation"))
                continue  # same pool first (other workers), then fallbacks
            if outcome.get("status") == "retry":
                outcome = {"status": "blocked", "failure_class": "provider", "request_id": request_id}
            return outcome

        if context_reject is not None:
            return self._reject_context(request_id, context_reject, client_id)
        if not any_candidate and missing:
            self.metrics.scheduler_dispatch_decisions_total.inc(worker_id="none", decision="rejected_capability")
            self.metrics.inference_completions_total.inc(worker_id="none", outcome="rejected", failure_class="capability")
            self.evidence.append("routing_rejected", request_id=request_id, client_id=client_id,
                                 failure_class="capability_unsupported", missing=sorted(missing))
            return {"status": "unsupported", "failure_class": "capability_unsupported", "request_id": request_id,
                    "http_status": 422, "missing_capabilities": sorted(missing),
                    "message": f"no reachable worker provides: {', '.join(sorted(missing))}"}
        if decision is not None:
            self.metrics.scheduler_dispatch_decisions_total.inc(worker_id="none", decision="rejected_pool_unavailable")
            self.metrics.inference_completions_total.inc(worker_id="none", outcome="failed", failure_class="pool_unavailable")
            self.evidence.append("routing_rejected", request_id=request_id, client_id=client_id, failure_class="pool_unavailable",
                                 route_rule=decision.rule_id, route_pools=list(decision.pools))
            return {"status": "blocked", "failure_class": "pool_unavailable", "request_id": request_id,
                    "message": f"No healthy worker is available in pool(s) {list(decision.pools)} (rule '{decision.rule_id}').",
                    "route": {"rule_id": decision.rule_id, "pool": decision.pool, "fallback_used": False, "reason": decision.reason}}
        return self._capability_reject(request_id, client_id)

    def registry_clients_admit(self, client: Client) -> None:
        clients = getattr(self, "clients", None)
        if clients is not None:
            clients.admit(client)

    def _capability_reject(self, request_id: str, client_id: str) -> dict[str, Any]:
        self.metrics.scheduler_dispatch_decisions_total.inc(worker_id="none", decision="rejected_capability")
        self.metrics.inference_completions_total.inc(worker_id="none", outcome="rejected", failure_class="capability")
        self.evidence.append("routing_rejected", request_id=request_id, client_id=client_id, failure_class="capability")
        return {"status": "unsupported", "failure_class": "capability", "request_id": request_id}

    def _forget(self, request_id: str) -> None:
        with self._inflight_lock:
            self._inflight.pop(request_id, None)

    def _cancelled(self, request_id: str, client_id: str, pool: Any, reason: str, *, queued: bool) -> dict[str, Any]:
        self.metrics.requests_cancelled_total.inc(reason=reason, pool=str(pool))
        self.evidence.append("request_cancelled", request_id=request_id, client_id=client_id, reason=reason,
                             stage="queued" if queued else "in_flight", route_pool=pool)
        if reason == "gateway_shutdown":
            return {"status": "unavailable", "failure_class": "gateway_restarting", "request_id": request_id,
                    "http_status": 503, "retry_after": 15, "message": "gateway is restarting; retry shortly"}
        if reason == "deadline":
            return {"status": "deadline", "failure_class": "deadline_exceeded", "request_id": request_id, "http_status": 504,
                    "message": "deadline passed before the worker finished"}
        return {"status": "cancelled", "failure_class": "client_disconnect", "request_id": request_id, "http_status": 499}

    def _dispatch(self, request_id: str, plan: _Plan, route: dict[str, Any], client: Client | None, client_id: str,
                  priority: str, timeout: float, cancel: threading.Event, entry: dict[str, Any],
                  clamped_fields: list[str], deadline: float | None, decision: RouteDecision | None,
                  original: dict[str, Any], on_stream_start: Callable[[dict[str, Any]], None] | None = None,
                  on_stream_chunk: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
        worker = plan.worker
        clamped = tuple(clamped_fields) + plan.clamped
        for name in clamped:
            self.metrics.client_limit_clamped_total.inc(client_id=client_id, field=name)
        adapter = self.adapters.get(worker.worker_id)
        if adapter is None:
            self.admission.release(worker.worker_id, ok=False, distress=True)
            self._forget(request_id)
            self.metrics.scheduler_dispatch_decisions_total.inc(worker_id=worker.worker_id, decision="rejected_unhealthy")
            self.metrics.inference_completions_total.inc(worker_id=worker.worker_id, outcome="failed", failure_class="adapter_unavailable")
            self.health.record_worker_observation(worker.worker_id, healthy=False, error="adapter_unavailable")
            self.evidence.append("routing_rejected", request_id=request_id, client_id=client_id,
                                 failure_class="adapter_unavailable", worker_id=worker.worker_id)
            return {"status": "blocked", "failure_class": "adapter_unavailable", "request_id": request_id}

        self.metrics.scheduler_dispatch_decisions_total.inc(worker_id=worker.worker_id, decision="dispatched")
        self.metrics.inference_dispatches_total.inc(worker_id=worker.worker_id, model=worker.public_model_id)
        self.metrics.route_decisions_total.inc(rule=str(route["rule_id"]), pool=str(route["pool"]))
        self.evidence.append(
            "worker_selected", request_id=request_id, client_id=client_id, worker_id=worker.worker_id,
            worker_identity=worker.identity_hash, route_rule=route["rule_id"], route_pool=route["pool"],
            route_fallback=route["fallback_used"], priority=priority, prompt_tokens=plan.prompt_tokens,
            prompt_tokens_source=plan.token_source, max_completion=plan.max_completion, context_length=plan.context_length,
            limits_version=plan.limits_version, thinking=plan.thinking, reasoning_budget=plan.reasoning_budget,
            clamped=list(clamped), request_hash=_hash({k: original.get(k) for k in ("messages", "tools")}),
            message_count=len(original.get("messages") or []), tools=[(t.get("function") or {}).get("name")
                                                                       for t in original.get("tools") or [] if isinstance(t, dict)],
        )

        started = time.monotonic()
        self.metrics.scheduler_active_work.inc()
        self.metrics.worker_inflight.inc(worker_id=worker.worker_id)
        self.metrics.worker_max_concurrency.set(self.admission.limit(worker.worker_id) or worker.max_concurrency,
                                                worker_id=worker.worker_id)
        released = False

        def release(ok: bool, distress: bool = False, duration: float | None = None) -> None:
            nonlocal released
            if not released:
                released = True
                self.admission.release(worker.worker_id, ok=ok, duration=duration, distress=distress)

        try:
            if original.get("stream"):
                if not getattr(adapter, "supports_streaming", False) or on_stream_start is None or on_stream_chunk is None:
                    release(False)
                    return {"status": "unsupported", "failure_class": "streaming_unavailable", "request_id": request_id,
                            "http_status": 422, "message": "the selected worker adapter does not support streaming"}

                def start_stream() -> None:
                    if on_stream_start is not None:
                        on_stream_start({
                            "id": "chatcmpl-" + request_id.replace("-", "")[:24],
                            "created": int(time.time()), "model": worker.public_model_id,
                            "headers": _completion_headers(plan, worker),
                            "route": {**route, "worker_id": worker.worker_id},
                            "worker_id": worker.worker_id,
                        })

                output = adapter.complete(plan.forwarded, timeout, cancel=cancel,
                                          on_stream_start=start_stream, on_stream_chunk=on_stream_chunk)
            elif getattr(adapter, "supports_cancel", False):
                output = adapter.complete(plan.forwarded, timeout, cancel=cancel)
            else:
                output = adapter.complete(plan.forwarded, timeout)
            call_duration = time.monotonic() - started
            self.health.record_worker_observation(worker.worker_id, healthy=True, duration=call_duration)
            release(True, duration=call_duration)
        except RequestCancelled:
            release(True)
            reason = entry.get("cancel_reason") or ("deadline" if deadline is not None and time.monotonic() >= deadline
                                                    else "gateway_shutdown" if self.shutting_down.is_set() else "client_disconnect")
            return self._cancelled(request_id, client_id, route["pool"], reason, queued=False)
        except TimeoutError:
            call_duration = time.monotonic() - started
            release(False, distress=True)
            if deadline is not None and time.monotonic() >= deadline - 0.05:
                return self._cancelled(request_id, client_id, route["pool"], "deadline", queued=False)
            self.metrics.inference_completions_total.inc(worker_id=worker.worker_id, outcome="timed_out", failure_class="timeout")
            self.health.record_worker_observation(worker.worker_id, healthy=False, duration=call_duration, error="timeout")
            self.evidence.append("execution_failed", request_id=request_id, client_id=client_id, worker_id=worker.worker_id,
                                 failure_class="timeout")
            return {"status": "blocked", "failure_class": "timeout", "request_id": request_id}
        except ProviderError as error:
            call_duration = time.monotonic() - started
            malformed_history = error.status == 500 and "Failed to parse tool call arguments" in error.body
            if malformed_history or (error.status is not None and 400 <= error.status < 500 and error.status not in (401, 403, 408, 429)):
                # The worker answered correctly; the request was invalid for it (e.g. context overflow, or an
                # assistant tool call in the history whose arguments are not valid JSON: llama.cpp reports that as 500).
                release(True)
                self.health.record_worker_observation(worker.worker_id, healthy=True, duration=call_duration)
                failure_class = "context_length_exceeded" if ("maximum context length" in error.body or "context size" in error.body) else "invalid_request"
                self.metrics.inference_completions_total.inc(worker_id=worker.worker_id, outcome="rejected", failure_class=failure_class)
                self.evidence.append("execution_failed", request_id=request_id, client_id=client_id, worker_id=worker.worker_id,
                                     failure_class=failure_class, error=type(error).__name__, detail=scrub(error.body[:512], self.prompt_policy))
                message = error.body
                try:
                    message = json.loads(error.body)["error"]["message"]
                except (ValueError, KeyError, TypeError):
                    pass
                return {"status": "rejected", "failure_class": failure_class, "request_id": request_id, "message": str(message)[:1000]}
            release(False, distress=True)
            self.metrics.inference_completions_total.inc(worker_id=worker.worker_id, outcome="failed", failure_class="provider")
            self.health.record_worker_observation(worker.worker_id, healthy=False, duration=call_duration, error=str(error))
            self.evidence.append("execution_failed", request_id=request_id, client_id=client_id, worker_id=worker.worker_id,
                                 failure_class="provider", error=type(error).__name__,
                                 detail=scrub(str(error)[:512], self.prompt_policy), pre_generation=error.pre_generation)
            if error.pre_generation:
                # Nothing was generated and nothing was sent to the client: a retry elsewhere is safe (R7).
                return {"status": "retry", "failure_class": "pre_generation", "request_id": request_id}
            return {"status": "blocked", "failure_class": "provider", "request_id": request_id}
        except Exception as error:
            call_duration = time.monotonic() - started
            release(False, distress=True)
            self.metrics.inference_completions_total.inc(worker_id=worker.worker_id, outcome="failed", failure_class="worker")
            self.health.record_worker_observation(worker.worker_id, healthy=False, duration=call_duration, error=str(error))
            self.evidence.append("execution_failed", request_id=request_id, client_id=client_id, worker_id=worker.worker_id,
                                 failure_class="worker", error=type(error).__name__)
            return {"status": "blocked", "failure_class": "worker", "request_id": request_id}
        finally:
            if not released:
                release(False, distress=True)
            self.metrics.scheduler_active_work.dec()
            self.metrics.worker_inflight.dec(worker_id=worker.worker_id)
            self._forget(request_id)

        if self.validator is not None:
            is_valid = bool(self.validator(output))
            self.metrics.authority_validations_total.inc(outcome="accepted" if is_valid else "rejected")
            if not is_valid:
                self.metrics.inference_completions_total.inc(worker_id=worker.worker_id, outcome="failed", failure_class="external_validation")
                self.evidence.append("response_rejected", request_id=request_id, client_id=client_id, worker_id=worker.worker_id,
                                     failure_class="external_validation")
                return {"status": "blocked", "failure_class": "external_validation", "request_id": request_id}
        else:
            self.metrics.authority_validations_total.inc(outcome="accepted")

        total_duration = time.monotonic() - started
        pool_label = str(route["pool"] or worker.pool)
        self.metrics.inference_duration_seconds.observe(total_duration, worker_id=worker.worker_id, model=worker.public_model_id, pool=pool_label)
        self.metrics.inference_completions_total.inc(worker_id=worker.worker_id, outcome="completed", failure_class="none")

        prompt_tokens, completion_tokens, usage_source = _token_counts(output, plan.prompt_tokens)
        self.metrics.inference_prompt_tokens_total.inc(prompt_tokens, worker_id=worker.worker_id, model=worker.public_model_id, source=usage_source[0])
        self.metrics.inference_completion_tokens_total.inc(completion_tokens, worker_id=worker.worker_id, model=worker.public_model_id, source=usage_source[1])
        if client is not None and getattr(self, "clients", None) is not None:
            self.clients.charge_tokens(client, prompt_tokens + completion_tokens)

        termination, exhausted = reasoning_policy.classify(output, budget=plan.reasoning_budget, budget_message=self.budget_message)
        self.metrics.completion_terminations_total.inc(worker_id=worker.worker_id, pool=pool_label, termination=termination)
        if exhausted:
            self.metrics.reasoning_budget_exhausted_total.inc(worker_id=worker.worker_id, pool=pool_label)

        tool_calls = output.get("tool_calls", [])
        provider_finish = output.get("provider_finish_reason")
        # N1: the provider's finish_reason is passed through. A truncated generation is never reported as "stop".
        finish_reason = "length" if provider_finish == "length" else ("tool_calls" if tool_calls else (provider_finish or "stop"))
        if finish_reason not in ("stop", "length", "tool_calls", "content_filter"):
            finish_reason = "stop"
        message = {"role": "assistant", "content": output.get("content", ""), "tool_calls": tool_calls}
        if output.get("reasoning_content"):
            message["reasoning_content"] = output["reasoning_content"]
        response = {
            "id": "chatcmpl-" + request_id.replace("-", "")[:24],
            "object": "chat.completion",
            "created": int(time.time()),
            "model": worker.public_model_id,
            "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        }
        if isinstance(output.get("usage"), dict):
            response["usage"] = output["usage"]
        if isinstance(output.get("timings"), dict):
            response["timings"] = output["timings"]
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
                normalized_finish_reason=finish_reason,
            )
        self.evidence.append("response_validated", request_id=request_id, client_id=client_id, worker_id=worker.worker_id,
                             elapsed_ms=round((time.monotonic() - started) * 1000, 3), response_hash=_hash(response),
                             termination=termination, reasoning_budget_exhausted=exhausted, finish_reason=finish_reason)
        self._remember(request_id, {"client_id": client_id, "rule": str(route["rule_id"]), "pool": pool_label,
                                    "model": worker.model_id, "worker_id": worker.worker_id,
                                    "artifact": worker.artifact_digest, "outcome": None})
        headers = _completion_headers(plan, worker)
        headers["X-AIHost-Termination"] = termination + (";reasoning_budget_exhausted" if exhausted else "")
        if clamped:
            headers["X-AIHost-Clamped"] = ",".join(clamped)
        if decision is not None and decision.shadow and _split_hit("shadow:" + request_id, decision.shadow[1]):
            self._shadow(decision.shadow[0], request_id, original, response, plan, decision)
        return {"status": "ok", "request_id": request_id, "response": response,
                "route": {**route, "worker_id": worker.worker_id}, "headers": headers}

    # ================================================================== R4 shadow
    def _shadow(self, pool: str, request_id: str, original: dict[str, Any], primary: dict[str, Any], plan: _Plan,
                decision: RouteDecision) -> None:
        """Replay the request on a candidate pool in the background; never returned, only compared and evidenced."""

        def run() -> None:
            missing: set[str] = set()
            workers = self._eligible(pool, frozenset(), None, frozenset(), True, missing)
            if not workers:
                self.metrics.shadow_comparisons_total.inc(pool=pool, result="no_capacity")
                return
            shadow_plan = self._plan(original, workers[0], decision.policy, None)
            if isinstance(shadow_plan, _ContextReject):
                self.metrics.shadow_comparisons_total.inc(pool=pool, result="context")
                return
            ticket = self.admission.new_ticket(pool, priority="background", client_id="shadow",
                                               deadline=time.monotonic() + 5.0)
            try:
                granted = self.admission.acquire(ticket, lambda: [w.worker_id for w in workers])
            except (AdmissionRejected, AdmissionCancelled, PoolUnavailable):
                self.metrics.shadow_comparisons_total.inc(pool=pool, result="no_capacity")
                return
            adapter = self.adapters.get(granted)
            started = time.monotonic()
            try:
                output = adapter.complete(shadow_plan.forwarded, self.upstream_timeout) if adapter else None
                ok = output is not None
            except Exception:  # noqa: BLE001
                output, ok = None, False
            finally:
                self.admission.release(granted, ok=True, duration=time.monotonic() - started)
            primary_message = primary["choices"][0]["message"]
            if not ok:
                self.metrics.shadow_comparisons_total.inc(pool=pool, result="error")
                return
            names = lambda calls: [(c.get("function") or {}).get("name") for c in calls or []]  # noqa: E731
            same_tools = names(primary_message.get("tool_calls")) == names(output.get("tool_calls"))
            same_content = _hash(primary_message.get("content")) == _hash(output.get("content"))
            result = "identical" if same_tools and same_content else ("same_tools" if same_tools else "different")
            self.metrics.shadow_comparisons_total.inc(pool=pool, result=result)
            self.evidence.append("shadow_compared", request_id=request_id, shadow_pool=pool, shadow_worker=granted,
                                 primary_hash=_hash(primary_message), shadow_hash=_hash({"content": output.get("content"),
                                                                                         "tool_calls": output.get("tool_calls")}),
                                 tool_call_names_equal=same_tools, content_equal=same_content,
                                 shadow_finish=output.get("provider_finish_reason"),
                                 shadow_latency_ms=round((time.monotonic() - started) * 1000, 1))

        threading.Thread(target=run, daemon=True, name="shadow").start()

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
