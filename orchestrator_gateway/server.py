from __future__ import annotations

import json
import threading
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from orchestrator_runtime import OrchestratorRuntime


def create_gateway(runtime: OrchestratorRuntime, client_token: str, *, max_body_bytes: int = 1_000_000):
    class Handler(BaseHTTPRequestHandler):
        server_version = "aihost-orchestrator/1.0"

        def _authorized(self) -> bool:
            return self.headers.get("Authorization") == f"Bearer {client_token}"

        def _send(self, status: int, payload: dict[str, Any], request_id: str | None = None) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Request-ID", request_id or str(uuid.uuid4()))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            request_id = self.headers.get("X-Request-ID") or str(uuid.uuid4())
            if not self._authorized():
                self._send(HTTPStatus.UNAUTHORIZED, {"error": {"message": "authentication required", "type": "authentication_error"}}, request_id)
                return
            if self.path != "/v1/models":
                self._send(HTTPStatus.NOT_FOUND, {"error": {"message": "unsupported endpoint", "type": "not_found"}}, request_id)
                return
            self._send(HTTPStatus.OK, {"object": "list", "data": [{"id": model, "object": "model", "owned_by": "aihost-orchestrator"} for model in runtime.registry.public_models()]}, request_id)

        def do_POST(self) -> None:  # noqa: N802
            request_id = self.headers.get("X-Request-ID") or str(uuid.uuid4())
            if not self._authorized():
                self._send(HTTPStatus.UNAUTHORIZED, {"error": {"message": "authentication required", "type": "authentication_error"}}, request_id)
                return
            if self.path != "/v1/chat/completions":
                self._send(HTTPStatus.NOT_FOUND, {"error": {"message": "unsupported endpoint", "type": "not_found"}}, request_id)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > max_body_bytes:
                    raise ValueError("request body exceeds configured limit")
                request = json.loads(self.rfile.read(length))
                if not isinstance(request, dict):
                    raise ValueError("request must be an object")
            except (ValueError, json.JSONDecodeError):
                self._send(HTTPStatus.BAD_REQUEST, {"error": {"message": "invalid request", "type": "invalid_request_error"}}, request_id)
                return
            request["request_id"] = request_id
            result = runtime.complete(request)
            if result["status"] != "ok":
                status = HTTPStatus.UNPROCESSABLE_ENTITY if result["status"] == "unsupported" else HTTPStatus.SERVICE_UNAVAILABLE
                self._send(status, {"error": {"message": result["failure_class"], "type": result["status"]}}, request_id)
                return
            if request.get("stream"):
                response = result["response"]
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
                event = {"id": response["id"], "object": "chat.completion.chunk", "model": response["model"], "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}
                self.wfile.write(f"data: {json.dumps(event, separators=(',', ':'))}\n\n".encode())
                finish = {"id": response["id"], "object": "chat.completion.chunk", "model": response["model"], "choices": [{"index": 0, "delta": {}, "finish_reason": choice.get("finish_reason", "stop")}]}
                self.wfile.write(f"data: {json.dumps(finish, separators=(',', ':'))}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")
                return
            self._send(HTTPStatus.OK, result["response"], request_id)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return Handler


class GatewayServer(ThreadingHTTPServer):
    daemon_threads = True
