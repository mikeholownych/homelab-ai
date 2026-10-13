"""Tests for streaming backpressure and slow consumer disconnection."""
from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from orchestrator_gateway import AsgiServerWrapper, create_asgi_gateway
from orchestrator_runtime import CapabilityRegistry, EvidenceStore, OrchestratorRuntime
from tests.test_orchestrator_runtime import worker


class InfiniteStreamAdapter:
    supports_streaming = True
    supports_cancel = True

    def __init__(self):
        self.cancelled = False
        self.chunks_sent = 0

    def complete(self, request, timeout, cancel=None, on_stream_start=None, on_stream_chunk=None, **kwargs):
        if on_stream_start:
            on_stream_start()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if cancel and cancel.is_set():
                self.cancelled = True
                break
            try:
                on_stream_chunk({"choices": [{"index": 0, "delta": {"content": "token "}, "finish_reason": None}]})
                self.chunks_sent += 1
            except Exception:
                break
            time.sleep(0.01)
        return {"content": "done", "tool_calls": []}


def test_asgi_streaming_client_disconnect_cancels_worker(tmp_path):
    """Verify that when a client abruptly closes its TCP socket mid-stream, the upstream worker is canceled immediately."""
    w1 = worker("w1")
    adapter = InfiniteStreamAdapter()
    runtime = OrchestratorRuntime(
        CapabilityRegistry([w1]),
        {"w1": adapter},
        EvidenceStore(tmp_path / "evidence.jsonl"),
    )
    app = create_asgi_gateway(runtime, "test-secret-token", max_stream_queue_size=4, stream_queue_timeout=0.1)
    wrapper = AsgiServerWrapper(app, "127.0.0.1", 0, log_level="error")
    thread = threading.Thread(target=wrapper.serve_forever, daemon=True)
    thread.start()

    deadline = time.monotonic() + 5.0
    while not wrapper.server.started and time.monotonic() < deadline:
        time.sleep(0.01)

    port = wrapper.server.servers[0].sockets[0].getsockname()[1]
    try:
        s = socket.socket()
        s.connect(("127.0.0.1", port))
        body = json.dumps({"model": "engineering/w1", "messages": [{"role": "user", "content": "hi"}], "stream": True})
        req = (
            f"POST /v1/chat/completions HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{port}\r\n"
            f"Authorization: Bearer test-secret-token\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n\r\n{body}"
        )
        s.sendall(req.encode())
        data = s.recv(512)
        assert b"200 OK" in data
        # Abruptly close socket mid-stream
        s.close()

        # Wait for cancellation signal to reach adapter
        cancel_deadline = time.monotonic() + 3.0
        while not adapter.cancelled and time.monotonic() < cancel_deadline:
            time.sleep(0.05)

        assert adapter.cancelled is True
    finally:
        wrapper.shutdown()
        thread.join(timeout=3.0)


def test_asgi_streaming_normal_consumption(tmp_path):
    """Verify standard TestClient streaming completes cleanly."""
    w1 = worker("w1")

    class SimpleAdapter:
        supports_streaming = True
        supports_cancel = True

        def complete(self, request, timeout, cancel=None, on_stream_start=None, on_stream_chunk=None, **kwargs):
            if on_stream_start:
                on_stream_start()
            for i in range(5):
                on_stream_chunk({"choices": [{"index": 0, "delta": {"content": f"tok_{i} "}, "finish_reason": None}]})
            return {"content": "completed", "tool_calls": []}

    adapter = SimpleAdapter()
    runtime = OrchestratorRuntime(
        CapabilityRegistry([w1]),
        {"w1": adapter},
        EvidenceStore(tmp_path / "evidence.jsonl"),
    )
    app = create_asgi_gateway(runtime, "test-secret-token")
    client = TestClient(app)
    headers = {"Authorization": "Bearer test-secret-token"}
    payload = {
        "model": "engineering/w1",
        "messages": [{"role": "user", "content": "stream tokens"}],
        "stream": True,
    }

    with client.stream("POST", "/v1/chat/completions", headers=headers, json=payload) as response:
        assert response.status_code == 200
        lines = list(response.iter_lines())
        assert len(lines) >= 5
