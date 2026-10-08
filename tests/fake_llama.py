"""A small llama.cpp stand-in for gateway tests: the read-only endpoints the gateway observes and a chat endpoint
whose behaviour (delay, finish reason, reasoning, failure) is configurable, and which records whether the gateway
closed the connection before generation finished (cancellation, R1)."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any


class FakeLlama:
    def __init__(self, *, n_ctx: int = 4096, slots: int = 1, alias: str = "fake-model", build: str = "b1-test",
                 tools: bool = True, reasoning: bool = True) -> None:
        self.n_ctx = n_ctx
        self.slots = slots
        self.alias = alias
        self.build = build
        self.tools = tools
        self.reasoning = reasoning
        self.delay = 0.0
        self.stream_delay = 0.0
        self.finish_reason = "stop"
        self.content = "ok"
        self.reasoning_content = ""
        self.fail_status: int | None = None
        self.requests: list[dict[str, Any]] = []
        self.aborted = 0
        self.completed = 0
        self.busy = 0
        self._lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                return

            def _json(self, status: int, payload: Any) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/props":
                    self._json(200, {
                        "default_generation_settings": {"n_ctx": fake.n_ctx, "params": {"max_tokens": -1}},
                        "total_slots": fake.slots, "model_alias": fake.alias, "model_path": f"/models/{fake.alias}.gguf",
                        "model_ftype": "Q4_K - Medium", "build_info": fake.build, "modalities": {"vision": False},
                        "chat_template_caps": {"supports_tool_calls": fake.tools, "supports_parallel_tool_calls": fake.tools,
                                               "supports_reasoning_effort": fake.reasoning},
                    })
                elif self.path == "/slots":
                    self._json(200, [{"id": i, "n_ctx": fake.n_ctx, "is_processing": i < fake.busy} for i in range(fake.slots)])
                elif self.path in ("/health", "/v1/models"):
                    self._json(200, {"status": "ok", "data": [{"id": fake.alias}]})
                elif self.path == "/metrics":
                    body = b"llamacpp:requests_processing 0\n"
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self._json(404, {"error": "nope"})

            def do_POST(self) -> None:  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
                if self.path == "/apply-template":
                    # One "token" per whitespace-separated word of a deterministic rendering (incl. tools schema).
                    rendered = " ".join([json.dumps(body.get("messages")), json.dumps(body.get("tools") or []),
                                         json.dumps(body.get("chat_template_kwargs") or {})])
                    self._json(200, {"prompt": rendered})
                    return
                if self.path == "/tokenize":
                    self._json(200, {"tokens": list(range(len(body.get("content", "").split())))})
                    return
                if self.path != "/v1/chat/completions":
                    self._json(404, {"error": "nope"})
                    return
                with fake._lock:
                    fake.requests.append(body)
                    fake.busy += 1
                try:
                    if fake.fail_status:
                        self._json(fake.fail_status, {"error": {"message": "boom"}})
                        return
                    if body.get("stream"):
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.send_header("Cache-Control", "no-cache")
                        self.end_headers()
                        try:
                            words = fake.content.split(" ") or [""]
                            for word in words:
                                if fake.stream_delay:
                                    time.sleep(fake.stream_delay)
                                if _peer_closed(self.connection):
                                    with fake._lock:
                                        fake.aborted += 1
                                    return
                                event = {"id": "fake", "object": "chat.completion.chunk", "model": fake.alias,
                                         "choices": [{"index": 0, "delta": {"content": word + " "}, "finish_reason": None}]}
                                self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                                self.wfile.flush()
                            finish = {"choices": [{"index": 0, "delta": {}, "finish_reason": fake.finish_reason}],
                                      "usage": {"prompt_tokens": 7, "completion_tokens": len(words)}}
                            self.wfile.write(f"data: {json.dumps(finish)}\n\n".encode())
                            self.wfile.write(b"data: [DONE]\n\n")
                            self.wfile.flush()
                            with fake._lock:
                                fake.completed += 1
                        except (BrokenPipeError, ConnectionResetError):
                            with fake._lock:
                                fake.aborted += 1
                        return
                    deadline = time.monotonic() + fake.delay
                    while time.monotonic() < deadline:
                        time.sleep(0.02)
                        if _peer_closed(self.connection):
                            with fake._lock:
                                fake.aborted += 1
                            return
                    reasoning = fake.reasoning_content
                    self._json(200, {
                        "choices": [{"finish_reason": fake.finish_reason,
                                     "message": {"content": fake.content, "reasoning_content": reasoning}}],
                        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
                        "timings": {"prompt_ms": 5.0, "predicted_ms": 30.0, "predicted_n": 3},
                    })
                    with fake._lock:
                        fake.completed += 1
                finally:
                    with fake._lock:
                        fake.busy -= 1

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def endpoint(self) -> str:
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def _peer_closed(connection: Any) -> bool:
    import select
    import socket
    readable, _, _ = select.select([connection], [], [], 0)
    if not readable:
        return False
    try:
        return connection.recv(1, socket.MSG_PEEK) == b""
    except OSError:
        return True
