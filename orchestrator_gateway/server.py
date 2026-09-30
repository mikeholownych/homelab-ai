from __future__ import annotations

import hmac
import json
import os
import threading
import time
import urllib.parse
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterable

from orchestrator_runtime import OrchestratorRuntime


def create_gateway(
    runtime: OrchestratorRuntime,
    client_tokens: str | Iterable[str],
    *,
    max_body_bytes: int = 1_000_000,
    monitoring_token: str | None = None,
    require_monitoring_auth: bool = False,
    allow_worker_pinning: bool = False,
):
    tokens = (client_tokens,) if isinstance(client_tokens, str) else tuple(client_tokens)
    if not tokens or any(not token for token in tokens):
        raise ValueError("at least one non-empty client token is required")

    class Handler(BaseHTTPRequestHandler):
        server_version = "aihost-orchestrator/1.0"

        def _authorized(self) -> bool:
            presented = self.headers.get("Authorization", "")
            return any(hmac.compare_digest(presented, f"Bearer {token}") for token in tokens)

        def _monitoring_authorized(self) -> bool:
            if not require_monitoring_auth:
                return True
            presented = self.headers.get("Authorization", "")
            if monitoring_token and hmac.compare_digest(presented, f"Bearer {monitoring_token}"):
                return True
            return self._authorized()

        def _send(self, status: int, payload: dict[str, Any], request_id: str | None = None) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Request-ID", request_id or str(uuid.uuid4()))
            self.end_headers()
            self.wfile.write(body)

        def _record_metrics(self, route: str, method: str, status_code: int, duration: float) -> None:
            status_class = f"{status_code // 100}xx"
            runtime.metrics.http_requests_total.inc(
                route=route, method=method, status_class=status_class
            )
            runtime.metrics.http_request_duration_seconds.observe(
                duration, route=route, method=method
            )

        def do_GET(self) -> None:  # noqa: N802
            t0 = time.monotonic()
            request_id = self.headers.get("X-Request-ID") or str(uuid.uuid4())
            parsed = urllib.parse.urlsplit(self.path)
            clean_path = parsed.path

            if clean_path == "/health":
                route = "health"
            elif clean_path == "/metrics":
                route = "metrics"
            elif clean_path == "/v1/models":
                route = "v1_models"
            else:
                route = "unsupported"

            runtime.metrics.http_requests_in_flight.inc(route=route)
            status_code = HTTPStatus.OK
            try:
                if route == "health":
                    if not self._monitoring_authorized():
                        runtime.metrics.http_auth_failures_total.inc(route="health")
                        status_code = HTTPStatus.UNAUTHORIZED
                        self._send(
                            status_code,
                            {"error": {"message": "monitoring authentication required", "type": "authentication_error"}},
                            request_id,
                        )
                        return
                    query = urllib.parse.parse_qs(parsed.query)
                    strict = query.get("strict", [""])[0].lower() in {"true", "1"}
                    status_code, health_payload = runtime.health.check(strict=strict)
                    self._send(status_code, health_payload, request_id)
                    return

                if route == "metrics":
                    if not self._monitoring_authorized():
                        runtime.metrics.http_auth_failures_total.inc(route="metrics")
                        status_code = HTTPStatus.UNAUTHORIZED
                        self._send(
                            status_code,
                            {"error": {"message": "monitoring authentication required", "type": "authentication_error"}},
                            request_id,
                        )
                        return
                    metrics_body = runtime.metrics.render_prometheus_text().encode("utf-8")
                    status_code = HTTPStatus.OK
                    self.send_response(status_code)
                    self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
                    self.send_header("Content-Length", str(len(metrics_body)))
                    self.send_header("X-Request-ID", request_id)
                    self.end_headers()
                    self.wfile.write(metrics_body)
                    return

                if route == "v1_models":
                    if not self._authorized():
                        runtime.metrics.http_auth_failures_total.inc(route="v1_models")
                        status_code = HTTPStatus.UNAUTHORIZED
                        self._send(
                            status_code,
                            {"error": {"message": "authentication required", "type": "authentication_error"}},
                            request_id,
                        )
                        return
                    self._send(
                        HTTPStatus.OK,
                        {
                            "object": "list",
                            "data": [
                                {"id": model, "object": "model", "owned_by": "aihost-orchestrator"}
                                for model in runtime.registry.public_models()
                            ],
                        },
                        request_id,
                    )
                    return

                status_code = HTTPStatus.NOT_FOUND
                self._send(
                    status_code,
                    {"error": {"message": "unsupported endpoint", "type": "not_found"}},
                    request_id,
                )
            finally:
                runtime.metrics.http_requests_in_flight.dec(route=route)
                self._record_metrics(route, "GET", int(status_code), time.monotonic() - t0)

        def do_POST(self) -> None:  # noqa: N802
            t0 = time.monotonic()
            request_id = self.headers.get("X-Request-ID") or str(uuid.uuid4())
            parsed = urllib.parse.urlsplit(self.path)
            clean_path = parsed.path

            if clean_path == "/v1/chat/completions":
                route = "v1_chat_completions"
            else:
                route = "unsupported"

            runtime.metrics.http_requests_in_flight.inc(route=route)
            status_code = HTTPStatus.OK
            try:
                if not self._authorized():
                    runtime.metrics.http_auth_failures_total.inc(route=route)
                    status_code = HTTPStatus.UNAUTHORIZED
                    self._send(
                        status_code,
                        {"error": {"message": "authentication required", "type": "authentication_error"}},
                        request_id,
                    )
                    return

                if route != "v1_chat_completions":
                    status_code = HTTPStatus.NOT_FOUND
                    self._send(
                        status_code,
                        {"error": {"message": "unsupported endpoint", "type": "not_found"}},
                        request_id,
                    )
                    return

                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > max_body_bytes:
                        runtime.metrics.scheduler_admission_backpressure_total.inc(reason="body_limit")
                        raise ValueError("request body exceeds configured limit")
                    request = json.loads(self.rfile.read(length))
                    if not isinstance(request, dict):
                        raise ValueError("request must be an object")
                except (ValueError, json.JSONDecodeError):
                    status_code = HTTPStatus.BAD_REQUEST
                    self._send(
                        status_code,
                        {"error": {"message": "invalid request", "type": "invalid_request_error"}},
                        request_id,
                    )
                    return

                request["request_id"] = request_id
                pinned_worker = self.headers.get("X-AIHost-Worker")
                pinning_enabled = allow_worker_pinning or os.environ.get("ORCHESTRATOR_ALLOW_WORKER_PINNING") == "true"
                if pinned_worker and not pinning_enabled:
                    status_code = HTTPStatus.FORBIDDEN
                    self._send(
                        status_code,
                        {"error": {"message": "worker pinning is disabled", "type": "forbidden"}},
                        request_id,
                    )
                    return

                try:
                    result = runtime.complete(request, worker_id=pinned_worker)
                except OSError:
                    status_code = HTTPStatus.SERVICE_UNAVAILABLE
                    runtime.metrics.evidence_verification_failures_total.inc()
                    self._send(
                        status_code,
                        {"error": {"message": "evidence store unavailable", "type": "evidence_error"}},
                        request_id,
                    )
                    return

                if result["status"] != "ok":
                    status_code = (
                        HTTPStatus.UNPROCESSABLE_ENTITY
                        if result["status"] == "unsupported"
                        else HTTPStatus.SERVICE_UNAVAILABLE
                    )
                    self._send(
                        status_code,
                        {"error": {"message": result.get("failure_class", "error"), "type": result["status"]}},
                        request_id,
                    )
                    return

                if request.get("stream"):
                    response = result["response"]
                    ttft = time.monotonic() - t0
                    worker_used = pinned_worker or (
                        runtime.registry.snapshot()[0]["worker_id"] if runtime.registry.snapshot() else "unknown"
                    )
                    runtime.metrics.inference_ttft_seconds.observe(ttft, worker_id=worker_used)

                    try:
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", "text/event-stream")
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("X-Request-ID", request_id)
                        self.end_headers()
                        choice = response["choices"][0]
                        message = choice["message"]
                        delta = {"role": "assistant"}
                        for key in ("content", "reasoning_content", "tool_calls"):
                            if message.get(key):
                                delta[key] = message[key]
                        event = {
                            "id": response["id"],
                            "object": "chat.completion.chunk",
                            "model": response["model"],
                            "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                        }
                        self.wfile.write(f"data: {json.dumps(event, separators=(',', ':'))}\n\n".encode())
                        finish = {
                            "id": response["id"],
                            "object": "chat.completion.chunk",
                            "model": response["model"],
                            "choices": [{"index": 0, "delta": {}, "finish_reason": choice.get("finish_reason", "stop")}],
                        }
                        self.wfile.write(f"data: {json.dumps(finish, separators=(',', ':'))}\n\n".encode())
                        self.wfile.write(b"data: [DONE]\n\n")
                        runtime.metrics.inference_streaming_requests_total.inc(
                            worker_id=worker_used, outcome="success"
                        )
                        status_code = HTTPStatus.OK
                        return
                    except Exception:
                        runtime.metrics.inference_streaming_requests_total.inc(
                            worker_id=worker_used, outcome="failure"
                        )
                        raise

                status_code = HTTPStatus.OK
                self._send(status_code, result["response"], request_id)
            finally:
                runtime.metrics.http_requests_in_flight.dec(route=route)
                self._record_metrics(route, "POST", int(status_code), time.monotonic() - t0)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


class GatewayServer(ThreadingHTTPServer):
    daemon_threads = True
