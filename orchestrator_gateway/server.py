from __future__ import annotations

import ipaddress
import json
import os
import select
import socket
import threading
import time
import urllib.parse
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Iterable

from orchestrator_runtime import OrchestratorRuntime
from orchestrator_runtime.clients import Client, ClientRegistry, token_digest

# Endpoints that only read gateway state (allowed on the loopback monitoring listener).
MONITORING_ROUTES = {"health", "metrics", "v1_telemetry_capabilities", "v1_telemetry_inference"}
# HTTP status for each runtime result status when the runtime did not pick one.
_STATUS = {"rejected": HTTPStatus.BAD_REQUEST, "unsupported": HTTPStatus.UNPROCESSABLE_ENTITY,
           "forbidden": HTTPStatus.FORBIDDEN, "limited": HTTPStatus.TOO_MANY_REQUESTS,
           "deadline": HTTPStatus.GATEWAY_TIMEOUT, "unavailable": HTTPStatus.SERVICE_UNAVAILABLE}


def _route_headers(route: dict[str, Any] | None) -> dict[str, str]:
    if not route:
        return {}
    value = f"rule={route.get('rule_id')};pool={route.get('pool')};worker={route.get('worker_id', '-')};fallback={str(bool(route.get('fallback_used'))).lower()}"
    if route.get("canary"):
        value += f";canary={route['canary']}"
    return {"X-AIHost-Route": value}


def host_addresses() -> set[str]:
    """Every address configured on this host (loopback included): a request from any of them originated here.

    Read from the kernel's own tables (no subprocess): IPv4 LOCAL routes in /proc/net/fib_trie, IPv6 interface
    addresses in /proc/net/if_inet6.
    """
    addresses = {"127.0.0.1", "::1"}
    try:
        lines = open("/proc/net/fib_trie", encoding="utf-8").read().splitlines()
        for previous, line in zip(lines, lines[1:]):
            if line.strip() == "/32 host LOCAL" and "--" in previous:
                addresses.add(previous.split("--")[-1].strip())
    except OSError:
        pass
    try:
        with open("/proc/net/if_inet6", encoding="utf-8") as stream:
            for line in stream:
                addresses.add(str(ipaddress.IPv6Address(int(line.split()[0], 16))))
    except (OSError, ValueError, IndexError):
        pass
    return addresses


def _is_local(peer: str, local: set[str]) -> bool:
    try:
        address = ipaddress.ip_address(peer.split("%")[0])
    except ValueError:
        return False
    if address.is_loopback:
        return True
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        mapped = address.ipv4_mapped
        return mapped.is_loopback or str(mapped) in local
    return str(address) in local


def _client_gone(connection: Any) -> bool:
    """True when the client closed its connection. Peeks on a duplicate of the raw socket so neither plain nor TLS
    streams are consumed (TLS records stay intact for the handler)."""
    try:
        readable, _, _ = select.select([connection], [], [], 0)
    except (OSError, ValueError):
        return True
    if not readable:
        return False
    try:
        duplicate = socket.socket(fileno=os.dup(connection.fileno()))
    except OSError:
        return True
    try:
        duplicate.setblocking(False)
        return duplicate.recv(1, socket.MSG_PEEK) == b""
    except BlockingIOError:
        return False
    except OSError:
        return True
    finally:
        duplicate.close()  # closes only the duplicate descriptor; the handler's socket stays open


def create_gateway(
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
):
    """Build the request handler for one listener.

    listener="local": the loopback monitoring listener; only /health and /metrics are served, workload is refused
    (remote-origin-only, docs/design/05). listener="remote": workload listener; requests from the host's own
    addresses are refused. listener="any": no origin policy (tests, legacy).
    """
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

    class Handler(BaseHTTPRequestHandler):
        server_version = "aihost-orchestrator/2.0"

        # ---------------------------------------------------------------- identity and policy
        def _client(self) -> Client | None:
            return clients.authenticate(self.headers.get("Authorization", ""))

        def _monitoring_authorized(self) -> bool:
            if not require_monitoring_auth:
                return True
            presented = self.headers.get("Authorization", "")
            if monitoring_digest and presented.startswith("Bearer ") and \
                    token_digest(presented[7:].strip()) == monitoring_digest:
                return True
            client = self._client()
            return client is not None and bool(client.scopes & {"monitoring", "workload", "admin"})

        def _origin_refused(self, route: str) -> bool:
            if listener == "any" or route in MONITORING_ROUTES and listener == "local":
                return False
            if listener == "local":
                return True
            return _is_local(self.client_address[0], local_set())

        def _refuse_origin(self, route: str, request_id: str) -> int:
            runtime.metrics.local_origin_refused_total.inc(listener=listener)
            try:
                runtime.evidence.append("local_origin_refused", request_id=request_id, listener=listener, route=route,
                                        peer=self.client_address[0])
            except OSError:
                pass
            self._send(HTTPStatus.FORBIDDEN, {"error": {
                "message": "work must be initiated by a remote client through the gateway's remote listener",
                "type": "forbidden", "code": "local_origin_forbidden"}}, request_id)
            return HTTPStatus.FORBIDDEN

        # ---------------------------------------------------------------- output
        def _send(self, status: int, payload: dict[str, Any], request_id: str | None = None,
                  extra_headers: dict[str, str] | None = None) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Request-ID", request_id or str(uuid.uuid4()))
            for name, value in (extra_headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _unauthorized(self, route: str, request_id: str, message: str = "authentication required") -> int:
            runtime.metrics.http_auth_failures_total.inc(route=route)
            self._send(HTTPStatus.UNAUTHORIZED, {"error": {"message": message, "type": "authentication_error"}}, request_id)
            return HTTPStatus.UNAUTHORIZED

        def _forbidden(self, request_id: str, message: str) -> int:
            self._send(HTTPStatus.FORBIDDEN, {"error": {"message": message, "type": "forbidden", "code": "scope"}}, request_id)
            return HTTPStatus.FORBIDDEN

        def _record_metrics(self, route: str, method: str, status_code: int, duration: float) -> None:
            status_class = f"{status_code // 100}xx"
            runtime.metrics.http_requests_total.inc(route=route, method=method, status_class=status_class)
            runtime.metrics.http_request_duration_seconds.observe(duration, route=route, method=method)

        def _read_json(self) -> dict[str, Any] | None:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length <= 0 or length > max_body_bytes:
                runtime.metrics.scheduler_admission_backpressure_total.inc(reason="body_limit")
                return None
            try:
                body = json.loads(self.rfile.read(length))
            except (ValueError, json.JSONDecodeError):
                return None
            return body if isinstance(body, dict) else None

        # ---------------------------------------------------------------- GET
        def do_GET(self) -> None:  # noqa: N802
            t0 = time.monotonic()
            request_id = self.headers.get("X-Request-ID") or str(uuid.uuid4())
            parsed = urllib.parse.urlsplit(self.path)
            path = parsed.path
            route = {"/health": "health", "/metrics": "metrics", "/v1/models": "v1_models", "/v1/routes": "v1_routes",
                     "/v1/outcomes/summary": "v1_outcomes_summary", "/admin/workers": "admin_workers",
                     "/v1/telemetry/capabilities": "v1_telemetry_capabilities",
                     "/v1/telemetry/inference": "v1_telemetry_inference"}.get(path, "unsupported")
            runtime.metrics.http_requests_in_flight.inc(route=route)
            status_code = HTTPStatus.OK
            try:
                if self._origin_refused(route):
                    status_code = self._refuse_origin(route, request_id)
                    return
                if route in ("health", "metrics"):
                    if not self._monitoring_authorized():
                        runtime.metrics.http_auth_failures_total.inc(route=route)
                        status_code = HTTPStatus.UNAUTHORIZED
                        self._send(status_code, {"error": {"message": "monitoring authentication required",
                                                           "type": "authentication_error"}}, request_id)
                        return
                    if route == "health":
                        query = urllib.parse.parse_qs(parsed.query)
                        strict = query.get("strict", [""])[0].lower() in {"true", "1"}
                        status_code, payload = runtime.health.check(strict=strict)
                        if runtime.shutting_down.is_set():
                            payload["status"], payload["ready"] = "draining", False
                            status_code = HTTPStatus.SERVICE_UNAVAILABLE
                        payload["evidence"] = {"chain_valid": getattr(runtime.evidence, "chain_valid", True),
                                               "head": getattr(runtime.evidence, "head", None)}
                        self._send(status_code, payload, request_id)
                        return
                    body = runtime.metrics.render_prometheus_text().encode("utf-8")
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("X-Request-ID", request_id)
                    self.end_headers()
                    self.wfile.write(body)
                    return

                client = self._client()
                if client is None:
                    status_code = self._unauthorized(route, request_id)
                    return
                if route == "admin_workers":
                    if "admin" not in client.scopes:
                        status_code = self._forbidden(request_id, "admin scope required")
                        return
                    self._send(HTTPStatus.OK, {"workers": {w["worker_id"]: runtime.worker_detail(w["worker_id"])
                                                           for w in runtime.registry.snapshot()}}, request_id)
                    return
                if not client.scopes & {"workload", "qualification", "monitoring", "telemetry", "admin"}:
                    status_code = self._forbidden(request_id, "workload, qualification, monitoring, telemetry or admin scope required")
                    return
                if route == "v1_telemetry_capabilities":
                    if hasattr(runtime, "telemetry_service"):
                        caps = runtime.telemetry_service.capabilities(client)
                        self._send(HTTPStatus.OK, caps, request_id)
                    else:
                        self._send(HTTPStatus.SERVICE_UNAVAILABLE, {"error": {"message": "telemetry service unavailable", "type": "service_unavailable"}}, request_id)
                    return
                if route == "v1_telemetry_inference":
                    if not hasattr(runtime, "telemetry_service"):
                        self._send(HTTPStatus.SERVICE_UNAVAILABLE, {"error": {"message": "telemetry service unavailable", "type": "service_unavailable"}}, request_id)
                        return
                    query = urllib.parse.parse_qs(parsed.query)
                    scope = query.get("scope", [None])[0]
                    req_id = query.get("request_id", [None])[0]
                    worker_id = query.get("worker_id", [None])[0]
                    model = query.get("model", [None])[0]
                    metric = query.get("metric", [None])[0]
                    limit_raw = query.get("limit", ["10"])[0]
                    try:
                        limit = int(limit_raw)
                        if limit < 1 or limit > 100:
                            status_code = HTTPStatus.BAD_REQUEST
                            self._send(status_code, {"error": {"message": "limit must be between 1 and 100", "type": "invalid_request_error"}}, request_id)
                            return
                    except (ValueError, TypeError):
                        status_code = HTTPStatus.BAD_REQUEST
                        self._send(status_code, {"error": {"message": "invalid limit parameter", "type": "invalid_request_error"}}, request_id)
                        return
                    try:
                        telemetry_data = runtime.telemetry_service.inference_telemetry(
                            client, scope=scope, request_id=req_id, worker_id=worker_id,
                            model=model, metric=metric, limit=limit
                        )
                        self._send(HTTPStatus.OK, telemetry_data, request_id)
                        return
                    except PermissionError as err:
                        status_code = self._forbidden(request_id, str(err))
                        return
                    except KeyError as err:
                        status_code = HTTPStatus.NOT_FOUND
                        self._send(status_code, {"error": {"message": str(err).strip("'"), "type": "not_found"}}, request_id)
                        return
                    except ValueError as err:
                        status_code = HTTPStatus.BAD_REQUEST
                        self._send(status_code, {"error": {"message": str(err), "type": "invalid_request_error"}}, request_id)
                        return
                if route == "v1_routes":
                    pools: dict[str, list[dict[str, Any]]] = {}
                    for worker in runtime.registry.snapshot():
                        pools.setdefault(worker.get("pool", "lead"), []).append({
                            "worker_id": worker["worker_id"], "model_id": worker["model_id"], "role": worker.get("role", "production"),
                            "context_limit": worker["context_limit"], "healthy": worker["healthy"],
                        })
                    table = runtime.router.describe() if runtime.router else None
                    self._send(HTTPStatus.OK, {"object": "route_table", "router": table, "pools": pools}, request_id)
                    return
                if route == "v1_models":
                    self._send(HTTPStatus.OK, {"object": "list", "data": runtime.alias_view(client)}, request_id)
                    return
                if route == "v1_outcomes_summary":
                    self._send(HTTPStatus.OK, {"object": "outcome_summary", "rows": runtime.outcome_summary()}, request_id)
                    return
                status_code = HTTPStatus.NOT_FOUND
                self._send(status_code, {"error": {"message": "unsupported endpoint", "type": "not_found"}}, request_id)
            finally:
                runtime.metrics.http_requests_in_flight.dec(route=route)
                self._record_metrics(route, "GET", int(status_code), time.monotonic() - t0)

        # ---------------------------------------------------------------- POST
        def do_POST(self) -> None:  # noqa: N802
            t0 = time.monotonic()
            request_id = self.headers.get("X-Request-ID") or str(uuid.uuid4())
            path = urllib.parse.urlsplit(self.path).path
            route = {"/v1/chat/completions": "v1_chat_completions", "/v1/tokenize": "v1_tokenize",
                     "/v1/outcomes": "v1_outcomes"}.get(path, "admin_worker" if path.startswith("/admin/workers/") else "unsupported")
            runtime.metrics.http_requests_in_flight.inc(route=route)
            status_code = HTTPStatus.OK
            try:
                if self._origin_refused(route):
                    status_code = self._refuse_origin(route, request_id)
                    return
                client = self._client()
                if client is None:
                    status_code = self._unauthorized(route, request_id)
                    return
                if route == "unsupported":
                    status_code = HTTPStatus.NOT_FOUND
                    self._send(status_code, {"error": {"message": "unsupported endpoint", "type": "not_found"}}, request_id)
                    return
                if route == "admin_worker":
                    status_code = self._admin(client, path, request_id)
                    return
                body = self._read_json()
                if body is None:
                    status_code = HTTPStatus.BAD_REQUEST
                    self._send(status_code, {"error": {"message": "invalid request", "type": "invalid_request_error"}}, request_id)
                    return
                if not client.scopes & {"workload", "qualification"}:
                    status_code = self._forbidden(request_id, "workload or qualification scope required")
                    return
                if route == "v1_tokenize":
                    counted = runtime.count_tokens(body, client)
                    status_code = HTTPStatus.NOT_FOUND if counted.get("status") == "not_found" else HTTPStatus.OK
                    self._send(status_code, counted, request_id)
                    return
                if route == "v1_outcomes":
                    result = runtime.report_outcome(client, str(body.get("request_id", "")), str(body.get("outcome", "")),
                                                    body.get("detail"))
                    status_code = {"recorded": HTTPStatus.OK, "not_found": HTTPStatus.NOT_FOUND}.get(result["status"], HTTPStatus.BAD_REQUEST)
                    self._send(status_code, result, request_id)
                    return
                status_code = self._completion(body, client, request_id, t0)
            finally:
                runtime.metrics.http_requests_in_flight.dec(route=route)
                self._record_metrics(route, "POST", int(status_code), time.monotonic() - t0)

        def _admin(self, client: Client, path: str, request_id: str) -> int:
            if "admin" not in client.scopes:
                return self._forbidden(request_id, "admin scope required")
            parts = path.strip("/").split("/")  # admin/workers/<id>/<action>
            if len(parts) != 4 or parts[3] not in ("drain", "undrain"):
                self._send(HTTPStatus.NOT_FOUND, {"error": {"message": "unsupported endpoint", "type": "not_found"}}, request_id)
                return HTTPStatus.NOT_FOUND
            action = runtime.drain if parts[3] == "drain" else runtime.undrain
            result = action(parts[2], actor=client.client_id)
            status = HTTPStatus.NOT_FOUND if result["status"] == "not_found" else HTTPStatus.OK
            self._send(status, result, request_id)
            return status

        def _completion(self, request: dict[str, Any], client: Client, request_id: str, t0: float) -> int:
            request["request_id"] = request_id
            pinned_worker = self.headers.get("X-AIHost-Worker")
            pinning_enabled = allow_worker_pinning or os.environ.get("ORCHESTRATOR_ALLOW_WORKER_PINNING") == "true"
            if pinned_worker and not pinning_enabled:
                self._send(HTTPStatus.FORBIDDEN, {"error": {"message": "worker pinning is disabled", "type": "forbidden"}}, request_id)
                return HTTPStatus.FORBIDDEN

            def header_int(name: str) -> int | None:
                value = self.headers.get(name)
                try:
                    return int(value) if value is not None else None
                except ValueError:
                    return None

            cancel = threading.Event()
            done = threading.Event()
            stream_state: dict[str, Any] = {}
            stream_timing: dict[str, Any] = {}

            def begin_stream(meta: dict[str, Any]) -> None:
                headers = {**_route_headers(meta.get("route")), **meta.get("headers", {})}
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Request-ID", request_id)
                self.send_header("Connection", "close")
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.close_connection = True
                stream_state["meta"] = meta
                stream_state["started"] = True
                stream_state["last_chunk_time"] = None
                stream_state["first_token_observed"] = False

            def send_stream_delta(event: dict[str, Any]) -> None:
                meta = stream_state.get("meta")
                if meta is None:
                    raise OSError("upstream sent a delta before stream headers")
                now = time.monotonic()
                worker_id = meta.get("worker_id")
                choices = event.get("choices", [])

                if not stream_state.get("first_token_observed") and choices:
                    stream_state["first_token_observed"] = True
                    ttft = max(0.0, now - t0)
                    stream_timing["ttft"] = ttft
                    if worker_id:
                        runtime.metrics.inference_ttft_seconds.observe(ttft, worker_id=worker_id)
                    stream_state["last_chunk_time"] = now
                    stream_state["itl_sum"] = 0.0
                    stream_state["itl_count"] = 0
                elif stream_state.get("first_token_observed") and choices:
                    last_time = stream_state.get("last_chunk_time")
                    if last_time is not None:
                        delta = max(0.0, now - last_time)
                        stream_state["itl_sum"] = stream_state.get("itl_sum", 0.0) + delta
                        stream_state["itl_count"] = stream_state.get("itl_count", 0) + 1
                        stream_timing["avg_itl"] = stream_state["itl_sum"] / stream_state["itl_count"]
                        if worker_id:
                            runtime.metrics.inference_inter_token_latency_seconds.observe(delta, worker_id=worker_id)
                    stream_state["last_chunk_time"] = now

                chunk = {"id": meta["id"], "object": "chat.completion.chunk", "created": meta["created"],
                         "model": meta["model"], "choices": choices}
                try:
                    self.wfile.write(f"data: {json.dumps(chunk, separators=(',', ':'))}\n\n".encode())
                    self.wfile.flush()
                except OSError:
                    # The client went away mid-stream: that is a cancellation (R1), never a worker failure.
                    cancel.set()

            def watch() -> None:  # R1: a client that goes away stops the work it started
                while not done.wait(0.25):
                    if _client_gone(self.connection):
                        cancel.set()
                        return

            threading.Thread(target=watch, daemon=True, name="client-watch").start()
            try:
                result = runtime.complete(
                    request, worker_id=pinned_worker, affinity=self.headers.get("X-Session-ID"),
                    task_class=self.headers.get("X-Task-Class"), client=client,
                    priority=self.headers.get("X-AIHost-Priority"), deadline_ms=header_int("X-AIHost-Deadline-Ms"),
                    attempt=header_int("X-AIHost-Attempt") or 1, previous_request=self.headers.get("X-AIHost-Previous-Request"),
                    reasoning_profile=self.headers.get("X-AIHost-Reasoning"), cancel=cancel,
                    on_stream_start=begin_stream if request.get("stream") else None,
                    on_stream_chunk=send_stream_delta if request.get("stream") else None,
                    stream_timing=stream_timing if request.get("stream") else None,
                )
            except OSError:
                runtime.metrics.evidence_verification_failures_total.inc()
                self._send(HTTPStatus.SERVICE_UNAVAILABLE, {"error": {"message": "evidence store unavailable", "type": "evidence_error"}}, request_id)
                return HTTPStatus.SERVICE_UNAVAILABLE
            finally:
                done.set()

            headers = {**_route_headers(result.get("route")), **(result.get("headers") or {})}
            if stream_state.get("started"):
                worker_used = result.get("route", {}).get("worker_id", "unknown")
                try:
                    if result.get("status") == "ok":
                        response = result["response"]
                        choice = response["choices"][0]
                        finish = {"id": stream_state["meta"]["id"], "object": "chat.completion.chunk",
                                  "created": stream_state["meta"]["created"], "model": stream_state["meta"]["model"],
                                  "choices": [{"index": 0, "delta": {}, "finish_reason": choice.get("finish_reason", "stop")}]}
                        if response.get("usage"):
                            finish["usage"] = response["usage"]
                        # Headers went out before generation finished, so the termination class travels in the final frame.
                        finish["x_aihost"] = {"termination": (result.get("headers") or {}).get("X-AIHost-Termination")}
                        self.wfile.write(f"data: {json.dumps(finish, separators=(',', ':'))}\n\n".encode())
                        self.wfile.write(b"data: [DONE]\n\n")
                        runtime.metrics.inference_streaming_requests_total.inc(worker_id=worker_used, outcome="success")
                    elif result.get("status") != "cancelled":
                        error = {"error": {"message": result.get("message") or result.get("failure_class", "stream failed"),
                                            "code": result.get("failure_class", "stream_failed")}}
                        self.wfile.write(f"event: error\ndata: {json.dumps(error, separators=(',', ':'))}\n\n".encode())
                        runtime.metrics.inference_streaming_requests_total.inc(worker_id=worker_used, outcome="failure")
                    self.wfile.flush()
                except OSError:
                    runtime.metrics.inference_streaming_requests_total.inc(worker_id=worker_used, outcome="failure")
                    cancel.set()
                return HTTPStatus.OK
            if result["status"] == "cancelled":
                self.close_connection = True
                return 499
            if result["status"] != "ok":
                status = HTTPStatus(result.get("http_status") or _STATUS.get(result["status"], HTTPStatus.SERVICE_UNAVAILABLE))
                if result.get("retry_after") is not None:
                    headers["Retry-After"] = str(int(result["retry_after"]))
                error = {"message": result.get("message") or result.get("failure_class", "error"),
                         "type": "invalid_request_error" if result["status"] == "rejected" else result["status"],
                         "code": result.get("failure_class", "error")}
                for key in ("details", "missing_capabilities"):
                    if key in result:
                        error[key] = result[key]
                self._send(status, {"error": error}, request_id, headers)
                return status

            self._send(HTTPStatus.OK, result["response"], request_id, headers)
            return HTTPStatus.OK

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


class GatewayServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
