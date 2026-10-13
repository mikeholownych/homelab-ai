"""Enterprise-grade Asynchronous ASGI Gateway for the AIHost Orchestrator.

Provides high-throughput async request handling, non-blocking SSE streaming,
native client disconnect cancellation without thread polling, and full OpenAI compatibility.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import urllib.parse
import uuid
from typing import Any, AsyncGenerator, Callable, Iterable

from starlette.applications import Starlette
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from starlette.routing import Route

from orchestrator_runtime import OrchestratorRuntime
from orchestrator_runtime.clients import Client, ClientRegistry, token_digest
from orchestrator_runtime.tracing import TraceContext
from .server import MONITORING_ROUTES, _is_local, _route_headers, host_addresses

_STATUS = {
    "rejected": 400,
    "unsupported": 422,
    "forbidden": 403,
    "limited": 429,
    "deadline": 504,
    "unavailable": 503,
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
) -> Starlette:
    """Construct a high-performance Starlette ASGI application for the gateway."""
    if clients is None:
        tokens = (client_tokens,) if isinstance(client_tokens, str) else tuple(client_tokens or ())
        if not tokens or any(not token for token in tokens):
            raise ValueError("at least one non-empty client token is required")
        clients = ClientRegistry.from_tokens([(f"client-{i}" if i else "default", t) for i, t in enumerate(tokens)])
    if getattr(runtime, "clients", None) is None:
        runtime.clients = clients

    monitoring_digest = token_digest(monitoring_token) if monitoring_token else None
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
        return clients.authenticate(auth_header)

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
        payload["evidence"] = {
            "chain_valid": getattr(runtime.evidence, "chain_valid", True),
            "head": getattr(runtime.evidence, "head", None),
        }
        runtime.metrics.http_requests_total.inc(route="health", method="GET", status_class=f"{status_code//100}xx")
        runtime.metrics.http_request_duration_seconds.observe(time.monotonic() - t0, route="health", method="GET")
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
        runtime.metrics.http_requests_total.inc(route="metrics", method="GET", status_class="2xx")
        runtime.metrics.http_request_duration_seconds.observe(time.monotonic() - t0, route="metrics", method="GET")
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
        runtime.metrics.http_requests_total.inc(route="v1_models", method="GET", status_class="2xx")
        runtime.metrics.http_request_duration_seconds.observe(time.monotonic() - t0, route="v1_models", method="GET")
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
        runtime.metrics.http_requests_total.inc(route="v1_routes", method="GET", status_class="2xx")
        runtime.metrics.http_request_duration_seconds.observe(time.monotonic() - t0, route="v1_routes", method="GET")
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
            body = await request.json()
        except Exception:
            return JSONResponse(status_code=400, content={"error": {"message": "invalid request", "type": "invalid_request_error"}})

        counted = runtime.count_tokens(body, client)
        status_code = 404 if counted.get("status") == "not_found" else 200
        runtime.metrics.http_requests_total.inc(route="v1_tokenize", method="POST", status_class=f"{status_code//100}xx")
        runtime.metrics.http_request_duration_seconds.observe(time.monotonic() - t0, route="v1_tokenize", method="POST")
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
            body = await request.json()
        except Exception:
            return JSONResponse(status_code=400, content={"error": {"message": "invalid request", "type": "invalid_request_error"}})

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

        # Cancellation event triggered if client disconnects
        cancel = asyncio.Event()

        if is_streaming:
            # High-performance async SSE streaming
            queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
            stream_state: dict[str, Any] = {}
            stream_timing: dict[str, Any] = {}

            def begin_stream(meta: dict[str, Any]) -> None:
                stream_state["meta"] = meta
                stream_state["started"] = True
                queue.put_nowait(("start", meta))

            def send_stream_delta(event: dict[str, Any]) -> None:
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
                queue.put_nowait(("chunk", chunk))

            # Run synchronous completion dispatcher in worker thread
            sync_cancel = threading.Event()

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
                    )
                except Exception as err:
                    return {"status": "error", "error": str(err)}

            future = asyncio.create_task(asyncio.to_thread(run_sync))

            async def sse_generator() -> AsyncGenerator[bytes, None]:
                try:
                    while not future.done() or not queue.empty():
                        # Check native ASGI client disconnect
                        if await request.is_disconnected():
                            sync_cancel.set()
                            break

                        try:
                            msg_type, item = await asyncio.wait_for(queue.get(), timeout=0.1)
                            if msg_type == "chunk":
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

            # Wait for stream start headers or early exit
            while not stream_state.get("started") and not future.done():
                if await request.is_disconnected():
                    sync_cancel.set()
                    return Response(status_code=499)
                try:
                    msg_type, item = await asyncio.wait_for(queue.get(), timeout=0.05)
                    if msg_type == "start":
                        break
                except asyncio.TimeoutError:
                    pass

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
                    return JSONResponse(status_code=status_code, content={"error": err_dict})

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
        result = await asyncio.to_thread(
            runtime.complete,
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
            trace_context=trace_context,
        )

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
            status_code = result.get("http_status", 503)
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

    routes = [
        Route("/health", handle_health, methods=["GET"]),
        Route("/metrics", handle_metrics, methods=["GET"]),
        Route("/v1/models", handle_models, methods=["GET"]),
        Route("/v1/routes", handle_routes, methods=["GET"]),
        Route("/v1/tokenize", handle_tokenize, methods=["POST"]),
        Route("/v1/chat/completions", handle_chat_completions, methods=["POST"]),
    ]

    return Starlette(routes=routes)


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
        import uvicorn

        self.host = host
        self.port = port
        self.config = uvicorn.Config(
            app=app,
            host=host,
            port=port,
            ssl_keyfile=ssl_keyfile,
            ssl_certfile=ssl_certfile,
            ssl_ca_certs=ssl_ca_certs,
            ssl_cert_reqs=ssl_cert_reqs,
            log_level=log_level,
            access_log=False,
        )
        self.server = uvicorn.Server(self.config)

    def serve_forever(self) -> None:
        self.server.run()

    def shutdown(self) -> None:
        self.server.should_exit = True
