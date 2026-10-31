"""Enterprise-grade Asynchronous ASGI Gateway for the AIHost Orchestrator.

Provides high-throughput async request handling, non-blocking SSE streaming,
bounded ingress, cancellation and the supported OpenAI-compatible chat API.
"""
from __future__ import annotations

import asyncio
import json
import os
import queue
import concurrent.futures
import socket
import threading
import time
import urllib.parse
import uuid
from typing import Any, AsyncGenerator, Callable, Iterable

from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from starlette.routing import Route

from orchestrator_runtime import OrchestratorRuntime
from orchestrator_runtime.clients import Client, ClientRegistry, token_digest
from orchestrator_runtime.tracing import TraceContext
from .asgi_limits import BoundedExecutor, ExecutionBusy, IngressError, read_object, watch_disconnect, GatewayMetricsMiddleware
from .server import MONITORING_ROUTES, _is_local, _route_headers, host_addresses

_EXECUTOR_LOCK = threading.Lock()

_STATUS = {
    "rejected": 400,
    "unsupported": 422,
    "forbidden": 403,
    "limited": 429,
    "deadline": 504,
    "unavailable": 503,
    "cancelled": 499,
}


def create_asgi_gateway(
    runtime: OrchestratorRuntime,
    client_tokens: str | Iterable[str] | None = None,
    *,
    max_body_bytes: int = 1_000_000,
    monitoring_token: str | None = None,
    require_monitoring_auth: bool = False,
    allow_worker_pinning: bool = False,
    clients: ClientRegistry | None = None,
    listener: str = "any",
    local_addresses: Callable[[], set[str]] | None = None,
    max_stream_queue_size: int = 64,
    stream_queue_timeout: float = 5.0,
) -> Starlette:
    """Construct a high-performance Starlette ASGI application for the gateway."""
    if clients is None:
        tokens = (client_tokens,) if isinstance(client_tokens, str) else tuple(client_tokens or ())
        if not tokens or any(not token for token in tokens):
            raise ValueError("at least one non-empty client token is required")
        clients = ClientRegistry.from_tokens([(f"client-{i}" if i else "default", t) for i, t in enumerate(tokens)])
    if getattr(runtime, "clients", None) is None:
        runtime.clients = clients

    with _EXECUTOR_LOCK:
        if not hasattr(runtime, "http_dispatch"):
            runtime.http_dispatch = BoundedExecutor(int(os.environ.get("ORCHESTRATOR_HTTP_DISPATCH_LIMIT", "32")), "gateway-dispatch",
                int(os.environ.get("ORCHESTRATOR_HTTP_CLIENT_DISPATCH_LIMIT", "8")))
            runtime.http_tokenize = BoundedExecutor(int(os.environ.get("ORCHESTRATOR_TOKENIZE_LIMIT", "4")), "gateway-tokenize")
    body_timeout = float(os.environ.get("ORCHESTRATOR_BODY_TIMEOUT_SECONDS", "15"))

    async def parse_body(request):
        return await read_object(request, max_body_bytes, body_timeout)

    def ingress_response(error):
        return JSONResponse(status_code=error.status, content={"error": {
            "message": error.message, "type": "invalid_request_error"}})

    def busy_response():
        return JSONResponse(status_code=503, headers={"Retry-After": "1"},
                            content={"error": {"message": "gateway execution capacity exhausted", "code": "overloaded"}})

    env_mon = monitoring_token or os.environ.get("ORCHESTRATOR_MONITORING_TOKEN")
    monitoring_digest = token_digest(env_mon) if env_mon else None
    if listener not in ("any", "local", "remote"):
        raise ValueError("listener must be any|local|remote")

    addresses_cache: dict[str, Any] = {"at": 0.0, "set": set()}

    def local_set() -> set[str]:
        if time.monotonic() - addresses_cache["at"] > 60:
            addresses_cache["set"] = (local_addresses or host_addresses)()
            addresses_cache["at"] = time.monotonic()
        return addresses_cache["set"]

    # ------------------------------------------------------------------ Auth & Origin helpers
    def get_client(request: Request) -> Client | None:
        auth_header = request.headers.get("Authorization", "")
        active_clients = getattr(runtime, "clients", None) or clients
        return active_clients.authenticate(auth_header)

    def is_admin_authorized(request: Request) -> bool:
        presented = request.headers.get("Authorization", "")
        if not presented and "token" in request.query_params:
            presented = f"Bearer {request.query_params['token']}"
        if monitoring_digest and presented.startswith("Bearer ") and \
                token_digest(presented[7:].strip()) == monitoring_digest:
            return True
        client = get_client(request)
        return client is not None and bool(client.scopes & {"admin"})

    def is_monitoring_authorized(request: Request) -> bool:
        if not require_monitoring_auth:
            return True
        presented = request.headers.get("Authorization", "")
        if monitoring_digest and presented.startswith("Bearer ") and \
                token_digest(presented[7:].strip()) == monitoring_digest:
            return True
        client = get_client(request)
        return client is not None and bool(client.scopes & {"monitoring", "workload", "admin"})

    def is_origin_refused(request: Request, route: str) -> bool:
        if listener == "any" or (route in MONITORING_ROUTES and listener == "local"):
            return False
        if listener == "local":
            return True
        client_host = request.client.host if request.client else "127.0.0.1"
        return _is_local(client_host, local_set())

    def refuse_origin_response(request_id: str, route: str, client_host: str) -> JSONResponse:
        runtime.metrics.local_origin_refused_total.inc(listener=listener)
        try:
            runtime.evidence.append(
                "local_origin_refused",
                request_id=request_id,
                listener=listener,
                route=route,
                peer=client_host,
            )
        except OSError:
            pass
        return JSONResponse(
            status_code=403,
            content={
                "error": {
                    "message": "work must be initiated by a remote client through the gateway's remote listener",
                    "type": "forbidden",
                    "code": "local_origin_forbidden",
                }
            },
            headers={"X-Request-ID": request_id},
        )

    def unauthorized_response(request_id: str, route: str, message: str = "authentication required") -> JSONResponse:
        runtime.metrics.http_auth_failures_total.inc(route=route)
        return JSONResponse(
            status_code=401,
            content={"error": {"message": message, "type": "authentication_error"}},
            headers={"X-Request-ID": request_id},
        )

    def forbidden_response(request_id: str, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=403,
            content={"error": {"message": message, "type": "forbidden", "code": "scope"}},
            headers={"X-Request-ID": request_id},
        )

    # ------------------------------------------------------------------ Endpoints
    async def handle_health(request: Request) -> Response:
        t0 = time.monotonic()
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        client_host = request.client.host if request.client else "127.0.0.1"
        if is_origin_refused(request, "health"):
            return refuse_origin_response(req_id, "health", client_host)
        if not is_monitoring_authorized(request):
            return unauthorized_response(req_id, "health", "monitoring authentication required")

        strict = request.query_params.get("strict", "").lower() in {"true", "1"}
        status_code, payload = runtime.health.check(strict=strict)
        if runtime.shutting_down.is_set():
            payload["status"], payload["ready"] = "draining", False
            status_code = 503
        payload["release_id"] = os.environ.get("ORCHESTRATOR_RELEASE_ID", "unknown")
        payload["evidence"] = {
            "chain_valid": getattr(runtime.evidence, "chain_valid", True),
            "head": getattr(runtime.evidence, "head", None),
        }
        return JSONResponse(status_code=status_code, content=payload, headers={"X-Request-ID": req_id})

    async def handle_metrics(request: Request) -> Response:
        t0 = time.monotonic()
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        client_host = request.client.host if request.client else "127.0.0.1"
        if is_origin_refused(request, "metrics"):
            return refuse_origin_response(req_id, "metrics", client_host)
        if not is_monitoring_authorized(request):
            return unauthorized_response(req_id, "metrics", "monitoring authentication required")

        body = runtime.metrics.render_prometheus_text()
        tracer = getattr(runtime, "tracer", None)
        if tracer is not None:
            body += (f"aihost_trace_export_dropped_spans_total {getattr(tracer, 'dropped_spans', 0)}\n"
                     f"aihost_trace_export_failures_total {getattr(tracer, 'export_failures', 0)}\n")
        return Response(
            content=body,
            media_type="text/plain; version=0.0.4; charset=utf-8",
            headers={"X-Request-ID": req_id},
        )

    async def handle_models(request: Request) -> Response:
        t0 = time.monotonic()
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        client_host = request.client.host if request.client else "127.0.0.1"
        if is_origin_refused(request, "v1_models"):
            return refuse_origin_response(req_id, "v1_models", client_host)
        client = get_client(request)
        if client is None:
            return unauthorized_response(req_id, "v1_models")
        if not client.scopes & {"workload", "qualification", "monitoring", "telemetry", "admin"}:
            return forbidden_response(req_id, "workload, qualification, monitoring, telemetry or admin scope required")

        models_view = runtime.alias_view(client)
        return JSONResponse(status_code=200, content={"object": "list", "data": models_view}, headers={"X-Request-ID": req_id})

    async def handle_routes(request: Request) -> Response:
        t0 = time.monotonic()
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        client_host = request.client.host if request.client else "127.0.0.1"
        if is_origin_refused(request, "v1_routes"):
            return refuse_origin_response(req_id, "v1_routes", client_host)
        client = get_client(request)
        if client is None:
            return unauthorized_response(req_id, "v1_routes")
        if not client.scopes & {"workload", "qualification", "monitoring", "telemetry", "admin"}:
            return forbidden_response(req_id, "workload, qualification, monitoring, telemetry or admin scope required")

        pools: dict[str, list[dict[str, Any]]] = {}
        for worker in runtime.registry.snapshot():
            pools.setdefault(worker.get("pool", "lead"), []).append({
                "worker_id": worker["worker_id"],
                "model_id": worker["model_id"],
                "role": worker.get("role", "production"),
                "context_limit": worker["context_limit"],
                "healthy": worker["healthy"],
            })
        table = runtime.router.describe() if runtime.router else None
        return JSONResponse(
            status_code=200,
            content={"object": "route_table", "router": table, "pools": pools},
            headers={"X-Request-ID": req_id},
        )

    async def handle_tokenize(request: Request) -> Response:
        t0 = time.monotonic()
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        client_host = request.client.host if request.client else "127.0.0.1"
        if is_origin_refused(request, "v1_tokenize"):
            return refuse_origin_response(req_id, "v1_tokenize", client_host)
        client = get_client(request)
        if client is None:
            return unauthorized_response(req_id, "v1_tokenize")
        if not client.scopes & {"workload", "qualification"}:
            return forbidden_response(req_id, "workload or qualification scope required")

        try:
            body = await parse_body(request)
        except IngressError as error:
            return ingress_response(error)

        try:
            counted = await runtime.http_tokenize.submit_for(client.client_id, runtime.count_tokens, body, client)
        except ExecutionBusy:
            return busy_response()
        status_code = 404 if counted.get("status") == "not_found" else 200
        return JSONResponse(status_code=status_code, content=counted, headers={"X-Request-ID": req_id})

    async def handle_chat_completions(request: Request) -> Response:
        t0 = time.monotonic()
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        client_host = request.client.host if request.client else "127.0.0.1"
        if is_origin_refused(request, "v1_chat_completions"):
            return refuse_origin_response(req_id, "v1_chat_completions", client_host)
        client = get_client(request)
        if client is None:
            return unauthorized_response(req_id, "v1_chat_completions")
        if not client.scopes & {"workload", "qualification"}:
            return forbidden_response(req_id, "workload or qualification scope required")

        trace_context = TraceContext.from_headers(request.headers)

        try:
            body = await parse_body(request)
        except IngressError as error:
            return ingress_response(error)

        if (not isinstance(body.get("messages"), list) or not body["messages"]
                or any(not isinstance(message, dict) for message in body["messages"])
                or ("stream" in body and not isinstance(body["stream"], bool))
                or any(type(body[key]) is not int or body[key] < 1
                       for key in ("max_tokens", "max_completion_tokens") if key in body)):
            return ingress_response(IngressError(400, "invalid chat request fields"))
        if len(req_id) > 128:
            return ingress_response(IngressError(400, "request id exceeds 128 characters"))
        body["request_id"] = req_id
        pinned_worker = request.headers.get("X-AIHost-Worker")
        pinning_enabled = allow_worker_pinning or os.environ.get("ORCHESTRATOR_ALLOW_WORKER_PINNING") == "true"
        if pinned_worker and not pinning_enabled:
            return JSONResponse(status_code=403, content={"error": {"message": "worker pinning is disabled", "type": "forbidden"}})

        def header_int(name: str) -> int | None:
            val = request.headers.get(name)
            try:
                return int(val) if val is not None else None
            except ValueError:
                return None

        raw_effort = request.headers.get("X-AIHost-Reasoning-Effort") or body.get("reasoning_effort")
        body_profile = None
        if isinstance(raw_effort, str) and raw_effort.strip():
            lowered = raw_effort.strip().lower()
            body_profile = {"medium": "standard", "high": "max", "none": "off"}.get(lowered, lowered)

        reasoning_profile = request.headers.get("X-AIHost-Reasoning") or body_profile
        is_streaming = bool(body.get("stream"))

        # Cancellation is propagated while queued, before response headers and during generation.

        if is_streaming:
            # High-performance async SSE streaming with thread-safe backpressure
            stream_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=max_stream_queue_size)
            loop = asyncio.get_running_loop()
            stream_state: dict[str, Any] = {}
            stream_timing: dict[str, Any] = {}
            stream_started = threading.Event()
            sync_cancel = threading.Event()

            def begin_stream(meta: dict[str, Any]) -> None:
                stream_state["meta"] = meta
                stream_state["started"] = True
                stream_started.set()

            def send_stream_delta(event: dict[str, Any]) -> None:
                if sync_cancel.is_set():
                    return
                meta = stream_state.get("meta")
                now = time.monotonic()
                choices = event.get("choices", [])
                worker_id = meta.get("worker_id") if meta else None

                if not stream_state.get("first_token_observed") and choices:
                    stream_state["first_token_observed"] = True
                    ttft = max(0.0, now - t0)
                    stream_timing["ttft"] = ttft
                    if worker_id:
                        runtime.metrics.inference_ttft_seconds.observe(ttft, worker_id=worker_id)
                    stream_state["last_chunk_time"] = now
                elif stream_state.get("first_token_observed") and choices:
                    last_time = stream_state.get("last_chunk_time")
                    if last_time is not None:
                        delta = max(0.0, now - last_time)
                        if worker_id:
                            runtime.metrics.inference_inter_token_latency_seconds.observe(delta, worker_id=worker_id)
                    stream_state["last_chunk_time"] = now

                chunk = {
                    "id": meta["id"] if meta else "chatcmpl-" + req_id[:24],
                    "object": "chat.completion.chunk",
                    "created": meta.get("created", int(time.time())) if meta else int(time.time()),
                    "model": meta.get("model", body.get("model")) if meta else body.get("model"),
                    "choices": choices,
                }
                try:
                    pending = asyncio.run_coroutine_threadsafe(stream_queue.put(chunk), loop)
                    pending.result(timeout=stream_queue_timeout)
                except concurrent.futures.TimeoutError:
                    pending.cancel()
                    runtime.metrics.streaming_slow_consumer_disconnects_total.inc(worker_id=worker_id or "unknown")
                    sync_cancel.set()

            # Run synchronous completion dispatcher in worker thread

            def run_sync() -> dict[str, Any]:
                try:
                    return runtime.complete(
                        body,
                        worker_id=pinned_worker,
                        affinity=request.headers.get("X-Session-ID"),
                        task_class=request.headers.get("X-Task-Class"),
                        client=client,
                        priority=request.headers.get("X-AIHost-Priority"),
                        deadline_ms=header_int("X-AIHost-Deadline-Ms"),
                        attempt=header_int("X-AIHost-Attempt") or 1,
                        previous_request=request.headers.get("X-AIHost-Previous-Request"),
                        reasoning_profile=reasoning_profile,
                        cancel=sync_cancel,
                        on_stream_start=begin_stream,
                        on_stream_chunk=send_stream_delta,
                        stream_timing=stream_timing,
                        trace_context=trace_context,
                        cache_headers=dict(request.headers),
                    )
                except Exception as err:
                    return {"status": "error", "error": str(err)}

            try:
                future = runtime.http_dispatch.submit_for(client.client_id, run_sync)
            except ExecutionBusy:
                return busy_response()
            watcher = asyncio.create_task(watch_disconnect(request, sync_cancel))

            async def sse_generator() -> AsyncGenerator[bytes, None]:
                try:
                    while not future.done() or not stream_queue.empty():
                        try:
                            item = await asyncio.wait_for(stream_queue.get(), timeout=0.05)
                            yield f"data: {json.dumps(item, separators=(',', ':'))}\n\n".encode("utf-8")
                        except asyncio.TimeoutError:
                            continue

                    res = await future
                    if res.get("status") == "ok":
                        response = res.get("response", {})
                        choice = (response.get("choices") or [{}])[0]
                        finish = {
                            "id": stream_state.get("meta", {}).get("id", "chatcmpl-" + req_id[:24]),
                            "object": "chat.completion.chunk",
                            "created": stream_state.get("meta", {}).get("created", int(time.time())),
                            "model": stream_state.get("meta", {}).get("model", body.get("model")),
                            "choices": [{"index": 0, "delta": {}, "finish_reason": choice.get("finish_reason", "stop")}],
                        }
                        if response.get("usage"):
                            finish["usage"] = response["usage"]
                        finish["x_aihost"] = {"termination": (res.get("headers") or {}).get("X-AIHost-Termination")}
                        yield f"data: {json.dumps(finish, separators=(',', ':'))}\n\n".encode("utf-8")
                        yield b"data: [DONE]\n\n"
                    elif res.get("status") != "cancelled" and not sync_cancel.is_set():
                        err_payload = {"error": {"message": res.get("message") or res.get("failure_class", "stream failed"), "code": res.get("failure_class", "stream_failed")}}
                        yield f"event: error\ndata: {json.dumps(err_payload, separators=(',', ':'))}\n\n".encode("utf-8")
                finally:
                    sync_cancel.set()
                    watcher.cancel()

            # Wait for stream start headers or early exit
            try:
                while not stream_started.is_set() and not future.done():
                    if sync_cancel.is_set():
                        watcher.cancel()
                        return Response(status_code=499)
                    await asyncio.sleep(0.01)
            except BaseException:
                sync_cancel.set()
                watcher.cancel()
                raise

            if future.done() and not stream_state.get("started"):
                res = future.result()
                if res.get("status") != "ok":
                    status_code = res.get("http_status") or _STATUS.get(res.get("status"), 500)
                    err_dict = {
                        "message": res.get("message") or res.get("failure_class", "error"),
                        "type": "invalid_request_error" if res.get("status") == "rejected" else res.get("status", "error"),
                        "code": res.get("failure_class", "error"),
                    }
                    for k in ("details", "missing_capabilities"):
                        if k in res:
                            err_dict[k] = res[k]
                    watcher.cancel()
                    error_headers = {"X-Request-ID": req_id, **trace_context.to_headers()}
                    if res.get("retry_after") is not None:
                        error_headers["Retry-After"] = str(int(res["retry_after"]))
                    return JSONResponse(status_code=status_code, content={"error": err_dict}, headers=error_headers)

            meta = stream_state.get("meta", {})
            hdrs = {
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "X-Request-ID": req_id,
                **trace_context.to_headers(),
                **_route_headers(meta.get("route")),
                **(meta.get("headers") or {}),
            }
            return StreamingResponse(sse_generator(), media_type="text/event-stream", headers=hdrs)

        # Non-streaming execution
        sync_cancel = threading.Event()
        try:
            future = runtime.http_dispatch.submit_for(
            client.client_id, runtime.complete,
            body,
            worker_id=pinned_worker,
            affinity=request.headers.get("X-Session-ID"),
            task_class=request.headers.get("X-Task-Class"),
            client=client,
            priority=request.headers.get("X-AIHost-Priority"),
            deadline_ms=header_int("X-AIHost-Deadline-Ms"),
            attempt=header_int("X-AIHost-Attempt") or 1,
            previous_request=request.headers.get("X-AIHost-Previous-Request"),
            reasoning_profile=reasoning_profile,
            cancel=sync_cancel,
            cache_headers=dict(request.headers),
            trace_context=trace_context,
            )
        except ExecutionBusy:
            return busy_response()
        watcher = asyncio.create_task(watch_disconnect(request, sync_cancel))
        try:
            result = await asyncio.shield(future)
        finally:
            sync_cancel.set()
            watcher.cancel()

        headers = {
            "X-Request-ID": req_id,
            **trace_context.to_headers(),
            **_route_headers(result.get("route")),
            **(result.get("headers") or {}),
        }
        status_str = result.get("status", "ok")
        if status_str == "cancelled":
            return Response(status_code=499, headers=headers)
        if status_str != "ok":
            status_code = result.get("http_status") or _STATUS.get(status_str, 503)
            if result.get("retry_after") is not None:
                headers["Retry-After"] = str(int(result["retry_after"]))
            err_dict = {
                "message": result.get("message") or result.get("failure_class", "error"),
                "type": "invalid_request_error" if status_str == "rejected" else status_str,
                "code": result.get("failure_class", "error"),
            }
            for k in ("details", "missing_capabilities"):
                if k in result:
                    err_dict[k] = result[k]
            return JSONResponse(status_code=status_code, content={"error": err_dict}, headers=headers)

        return JSONResponse(status_code=200, content=result["response"], headers=headers)

    async def handle_admin_workers(request: Request) -> Response:
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        if is_origin_refused(request, "admin_workers"):
            return refuse_origin_response(req_id, "admin_workers", request.client.host if request.client else "127.0.0.1")
        client = get_client(request)
        if client is None:
            return unauthorized_response(req_id, "admin_workers")
        if "admin" not in client.scopes:
            return forbidden_response(req_id, "admin scope required")
        return JSONResponse({"workers": {w["worker_id"]: runtime.worker_detail(w["worker_id"])
                                         for w in runtime.registry.snapshot()}}, headers={"X-Request-ID": req_id})

    async def handle_admin_worker_action(request: Request) -> Response:
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        if is_origin_refused(request, "admin_worker"):
            return refuse_origin_response(req_id, "admin_worker", request.client.host if request.client else "127.0.0.1")
        client = get_client(request)
        if client is None:
            return unauthorized_response(req_id, "admin_worker")
        if "admin" not in client.scopes:
            return forbidden_response(req_id, "admin scope required")
        action = request.path_params["action"]
        if action not in ("drain", "undrain"):
            return JSONResponse({"status": "not_found"}, status_code=404, headers={"X-Request-ID": req_id})
        handler = runtime.drain if action == "drain" else runtime.undrain
        result = handler(request.path_params["worker_id"], actor=client.client_id)
        return JSONResponse(result, status_code=404 if result["status"] == "not_found" else 200,
                            headers={"X-Request-ID": req_id})

    async def handle_admin_reload(request: Request) -> Response:
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        if not is_admin_authorized(request):
            return unauthorized_response(req_id, "admin_reload")
        try:
            result = runtime.reload_config()
            return JSONResponse(status_code=200, content={"status": "ok", "reloaded": result}, headers={"X-Request-ID": req_id})
        except Exception as err:
            return JSONResponse(status_code=400, content={"status": "error", "message": str(err)}, headers={"X-Request-ID": req_id})

    async def handle_admin_status(request: Request) -> Response:
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        if not is_admin_authorized(request):
            return unauthorized_response(req_id, "admin_status")
        _, health_payload = runtime.health.check()
        cache_stats = runtime.cache.stats() if runtime.cache else {}
        evidence_info = {
            "chain_valid": getattr(runtime.evidence, "chain_valid", True),
            "head": getattr(runtime.evidence, "head", None),
        }
        reloads_count = runtime.metrics.gateway_config_reloads_total.get() if hasattr(runtime.metrics, "gateway_config_reloads_total") else 0
        status_payload = {
            "status": health_payload.get("status"),
            "ready": health_payload.get("ready"),
            "timestamp": health_payload.get("timestamp"),
            "gateway": health_payload.get("gateway"),
            "scheduler": health_payload.get("scheduler"),
            "workers": health_payload.get("workers"),
            "cache": cache_stats,
            "evidence": evidence_info,
            "reloads_count": reloads_count,
        }
        return JSONResponse(status_code=200, content=status_payload, headers={"X-Request-ID": req_id})

    async def handle_admin_worker_recover(request: Request) -> Response:
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        if not is_admin_authorized(request):
            return unauthorized_response(req_id, "admin_worker_recover")
        worker_id = request.path_params.get("worker_id", "")
        res = runtime.health.recover_worker(worker_id, reason="admin_api")
        return JSONResponse(status_code=200, content={"status": "ok", "recovery": res}, headers={"X-Request-ID": req_id})

    def _render_admin_html(health_payload: dict[str, Any], cache_stats: dict[str, Any]) -> str:
        status_color = "#10b981" if health_payload.get("ready") else "#ef4444"
        workers = health_payload.get("workers", {})
        workers_html = ""
        for wid, w in workers.items():
            w_status = w.get("status", "unknown")
            w_color = "#10b981" if w.get("healthy") else ("#6b7280" if w_status == "stopped" else "#ef4444")
            cb = w.get("circuit_breaker", "closed")
            cb_color = "#10b981" if cb == "closed" else ("#f59e0b" if "half" in cb else "#ef4444")
            ewma = f"{w.get('ewma_duration', 0.0) * 1000.0:.0f} ms" if w.get("ewma_duration") else "N/A"
            workers_html += f"""
            <div class="card worker-card">
                <div class="card-header" style="margin-bottom:0.75rem;">
                    <span class="badge" style="background:{w_color}22; color:{w_color}; border:1px solid {w_color}44;">{w_status.upper()}</span>
                    <span class="badge" style="background:{cb_color}22; color:{cb_color}; border:1px solid {cb_color}44;">CB: {cb.upper()}</span>
                    <h3 style="margin:0.5rem 0 0 0; font-size:1.1rem;">{wid}</h3>
                </div>
                <div class="card-body" style="font-size:0.9rem;">
                    <p style="margin:0.25rem 0;"><strong>Pool:</strong> {w.get('pool', 'lead')} &nbsp;|&nbsp; <strong>Engine:</strong> {w.get('engine', 'unknown')}</p>
                    <p style="margin:0.25rem 0;"><strong>Model:</strong> <code>{w.get('model_id', '-')}</code></p>
                    <p style="margin:0.25rem 0;"><strong>EWMA Latency:</strong> {ewma} &nbsp;|&nbsp; <strong>Failures:</strong> {w.get('consecutive_failures', 0)}</p>
                </div>
            </div>"""

        c_size = cache_stats.get("size", 0)
        c_max = cache_stats.get("max_entries", 0)
        c_hits = cache_stats.get("hits", 0)
        c_sem_hits = cache_stats.get("semantic_hits", 0)
        c_miss = cache_stats.get("misses", 0)
        c_rate = f"{cache_stats.get('hit_rate', 0.0) * 100.0:.1f}%"

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>AIHost Enterprise Appliance Console</title>
    <style>
        :root {{ --bg: #0f172a; --surface: #1e293b; --border: #334155; --text: #f8fafc; --text-dim: #94a3b8; --primary: #38bdf8; }}
        body {{ margin: 0; padding: 2rem; font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); line-height: 1.5; }}
        .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 1.5rem; margin-bottom: 2rem; }}
        .title-group h1 {{ margin: 0 0 0.25rem 0; font-size: 1.75rem; }}
        .title-group p {{ margin: 0; color: var(--text-dim); font-size: 0.9rem; }}
        .badge {{ display: inline-block; padding: 0.25rem 0.6rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; letter-spacing: 0.05em; }}
        .btn {{ background: #0284c7; color: white; border: none; padding: 0.6rem 1.2rem; border-radius: 6px; cursor: pointer; font-weight: 600; }}
        .btn:hover {{ background: #0369a1; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1.5rem; margin-bottom: 2rem; }}
        .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 1.25rem; }}
        .card h2 {{ margin-top: 0; font-size: 1.15rem; color: var(--primary); }}
        .stat-val {{ font-size: 1.75rem; font-weight: 700; color: #fff; margin: 0.25rem 0; }}
        .stat-desc {{ font-size: 0.85rem; color: var(--text-dim); margin: 0; }}
        code {{ background: #090d16; padding: 0.2rem 0.4rem; border-radius: 4px; font-size: 0.85rem; color: #38bdf8; }}
    </style>
</head>
<body>
    <div class="header">
        <div class="title-group">
            <h1>AIHost Enterprise Appliance</h1>
            <p>Host: <code>{socket.gethostname()}</code> &nbsp;|&nbsp; Release: <code>{os.environ.get('ORCHESTRATOR_RELEASE_ID', 'dev')}</code> &nbsp;|&nbsp; Uptime: {health_payload.get('gateway', {}).get('uptime_seconds', 0):.0f}s</p>
        </div>
        <div>
            <span class="badge" style="background:{status_color}22; color:{status_color}; border:1px solid {status_color}44; font-size: 0.9rem; padding: 0.4rem 0.8rem;">
                ● {health_payload.get('status', 'UNKNOWN').upper()}
            </span>
            <button class="btn" style="margin-left: 1rem;" onclick="reloadConfig()">Hot Reload Config</button>
        </div>
    </div>
    <div class="grid">
        <div class="card">
            <h2>Scheduler & Queuing</h2>
            <div class="stat-val">{health_payload.get('scheduler', {}).get('available_workers', 0)} / {health_payload.get('scheduler', {}).get('total_workers', 0)}</div>
            <p class="stat-desc">Workers Available · Mode: {health_payload.get('scheduler', {}).get('scheduling_mode', 'B+')}</p>
            <p style="margin-top:0.75rem; font-size: 0.85rem; color: var(--text-dim);">Queued: {health_payload.get('scheduler', {}).get('queued_work', 0)} · Active: {health_payload.get('scheduler', {}).get('active_work', 0)}</p>
        </div>
        <div class="card">
            <h2>Response Cache</h2>
            <div class="stat-val">{c_rate}</div>
            <p class="stat-desc">Hit Rate ({c_hits} hits, {c_miss} misses)</p>
            <p style="margin-top:0.75rem; font-size: 0.85rem; color: var(--text-dim);">{c_size} / {c_max} entries · Semantic hits: <strong style="color:var(--primary);">{c_sem_hits}</strong></p>
        </div>
        <div class="card">
            <h2>Evidence Ledger</h2>
            <div class="stat-val" style="font-size: 1.1rem; word-break: break-all; font-family: monospace; color: #a7f3d0;">
                {str(health_payload.get('evidence', {}).get('head', 'GENESIS'))[:24]}...
            </div>
            <p class="stat-desc">Cryptographic Head Hash · Chain Valid: {str(health_payload.get('evidence', {}).get('chain_valid', True)).upper()}</p>
        </div>
    </div>
    <h2 style="color: #cbd5e1; margin-bottom: 1rem;">Worker Fleet & Hardware Status</h2>
    <div class="grid">
        {workers_html}
    </div>
    <script>
        async function reloadConfig() {{
            try {{
                const res = await fetch('/v1/admin/reload', {{ method: 'POST' }});
                const data = await res.json();
                alert('Config Reloaded: ' + JSON.stringify(data));
                window.location.reload();
            }} catch (e) {{
                alert('Reload failed: ' + e);
            }}
        }}
    </script>
</body>
</html>"""

    async def handle_admin_ui(request: Request) -> Response:
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        if not is_admin_authorized(request):
            return unauthorized_response(req_id, "admin_ui")
        _, health_payload = runtime.health.check()
        cache_stats = runtime.cache.stats() if runtime.cache else {}
        html = _render_admin_html(health_payload, cache_stats)
        return HTMLResponse(content=html, headers={"X-Request-ID": req_id})

    async def handle_outcomes(request):
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        if is_origin_refused(request, "v1_outcomes"):
            return refuse_origin_response(req_id, "v1_outcomes", request.client.host if request.client else "")
        client = get_client(request)
        if client is None:
            return unauthorized_response(req_id, "v1_outcomes")
        if not client.scopes & {"workload", "qualification"}:
            return forbidden_response(req_id, "workload or qualification scope required")
        if request.method == "GET":
            return JSONResponse({"object": "outcome_summary", "rows": runtime.outcome_summary()})
        try:
            body = await parse_body(request)
        except IngressError as error:
            return ingress_response(error)
        result = runtime.report_outcome(client, str(body.get("request_id", "")),
                                        str(body.get("outcome", "")), body.get("detail"))
        return JSONResponse(result, status_code={"recorded": 200, "not_found": 404}.get(result["status"], 400))

    routes = [
        Route("/health", handle_health, methods=["GET"]),
        Route("/metrics", handle_metrics, methods=["GET"]),
        Route("/v1/outcomes", handle_outcomes, methods=["POST"]),
        Route("/v1/outcomes/summary", handle_outcomes, methods=["GET"]),
        Route("/v1/models", handle_models, methods=["GET"]),
        Route("/v1/routes", handle_routes, methods=["GET"]),
        Route("/v1/tokenize", handle_tokenize, methods=["POST"]),
        Route("/v1/chat/completions", handle_chat_completions, methods=["POST"]),
        Route("/v1/admin/reload", handle_admin_reload, methods=["POST"]),
        Route("/v1/admin/status", handle_admin_status, methods=["GET"]),
        Route("/v1/admin/workers/{worker_id}/recover", handle_admin_worker_recover, methods=["POST"]),
        Route("/admin/workers", handle_admin_workers, methods=["GET"]),
        Route("/admin/workers/{worker_id}/{action}", handle_admin_worker_action, methods=["POST"]),
        Route("/admin", handle_admin_ui, methods=["GET"]),
    ]

    app = Starlette(routes=routes)
    app.add_middleware(GatewayMetricsMiddleware, runtime=runtime)
    return app


class AsgiServerWrapper:
    """Production wrapper running an ASGI application with uvicorn."""

    def __init__(
        self,
        app: Any,
        host: str,
        port: int,
        ssl_keyfile: str | None = None,
        ssl_certfile: str | None = None,
        ssl_ca_certs: str | None = None,
        ssl_cert_reqs: int | None = None,
        log_level: str = "info",
    ) -> None:
        import ssl
        import uvicorn

        self.host = host
        self.port = port
        config_kwargs: dict[str, Any] = {
            "app": app,
            "host": host,
            "port": port,
            "log_level": log_level,
            "access_log": False,
            "limit_concurrency": int(os.environ.get("ORCHESTRATOR_HTTP_CONNECTION_LIMIT", "128")),
            "timeout_graceful_shutdown": float(os.environ.get("ORCHESTRATOR_SHUTDOWN_GRACE_SECONDS", "600")),
            "proxy_headers": False,
        }
        if ssl_keyfile and ssl_certfile:
            config_kwargs["ssl_keyfile"] = ssl_keyfile
            config_kwargs["ssl_certfile"] = ssl_certfile
            if ssl_ca_certs:
                config_kwargs["ssl_ca_certs"] = ssl_ca_certs
            config_kwargs["ssl_cert_reqs"] = ssl_cert_reqs if ssl_cert_reqs is not None else ssl.CERT_NONE

        self.config = uvicorn.Config(**config_kwargs)
        self.server = uvicorn.Server(self.config)

    def serve_forever(self) -> None:
        self.server.run()

    def shutdown(self) -> None:
        self.server.should_exit = True
