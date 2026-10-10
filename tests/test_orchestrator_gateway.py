from __future__ import annotations

import json
import threading
from http.client import HTTPConnection

from orchestrator_gateway import GatewayServer, create_gateway
from orchestrator_runtime import CapabilityRegistry, EvidenceStore, InMemoryAdapter, OrchestratorRuntime
from tests.test_orchestrator_runtime import worker


class StreamingAdapter:
    supports_streaming = True

    def __init__(self, *, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []

    def complete(self, request, timeout, cancel=None, on_stream_start=None, on_stream_chunk=None):
        on_stream_start()
        delta = {}
        if self.content:
            delta["content"] = self.content
        if self.tool_calls:
            delta["tool_calls"] = [{**call, "index": index} for index, call in enumerate(self.tool_calls)]
        on_stream_chunk({"choices": [{"index": 0, "delta": delta, "finish_reason": None}]})
        return {"content": self.content, "tool_calls": self.tool_calls, "provider_finish_reason": "tool_calls" if self.tool_calls else "stop"}


def test_gateway_auth_models_and_chat(tmp_path):
    registry = CapabilityRegistry([worker("ready")])
    runtime = OrchestratorRuntime(
        registry,
        {"ready": InMemoryAdapter("hello")},
        EvidenceStore(tmp_path / "evidence.jsonl"),
    )
    server = GatewayServer(("127.0.0.1", 0), create_gateway(runtime, "client-secret"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        connection = HTTPConnection(host, port)
        connection.request("GET", "/v1/models")
        assert connection.getresponse().status == 401
        connection.close()

        connection = HTTPConnection(host, port)
        connection.request("GET", "/v1/models", headers={"Authorization": "Bearer client-secret"})
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read())["data"][0]["id"] == "engineering/ready"
        connection.close()

        body = json.dumps({"model": "engineering/ready", "messages": [{"role": "user", "content": "hi"}]})
        connection = HTTPConnection(host, port)
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=body,
            headers={"Authorization": "Bearer client-secret", "Content-Type": "application/json"},
        )
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 200
        assert payload["choices"][0]["message"]["content"] == "hello"
        connection.close()

        stream_body = json.dumps({"model": "engineering/ready", "stream": True, "messages": [{"role": "user", "content": "hi"}]})
        connection = HTTPConnection(host, port)
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=stream_body,
            headers={"Authorization": "Bearer client-secret", "Content-Type": "application/json"},
        )
        response = connection.getresponse()
        assert response.status == 422  # in-memory adapters do not pretend to stream
        connection.close()

        connection = HTTPConnection(host, port)
        connection.request("GET", "/health")
        health_resp = connection.getresponse()
        assert health_resp.status == 200
        health_payload = json.loads(health_resp.read().decode())
        assert health_payload["status"] == "healthy"
        assert health_payload["ready"] is True
        connection.close()

        connection = HTTPConnection(host, port)
        connection.request("GET", "/metrics")
        metrics_resp = connection.getresponse()
        assert metrics_resp.status == 200
        assert "text/plain" in metrics_resp.getheader("Content-Type")
        metrics_text = metrics_resp.read().decode()
        assert "aihost_http_requests_total" in metrics_text
        connection.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_gateway_stream_preserves_tool_call_and_terminal_finish_reason(tmp_path):
    tool_call = {
        "id": "call-1",
        "type": "function",
        "function": {"name": "read", "arguments": '{"path":"README.md"}'},
    }

    runtime = OrchestratorRuntime(
        CapabilityRegistry([worker("ready")]),
        {"ready": StreamingAdapter(tool_calls=[tool_call])},
        EvidenceStore(tmp_path / "evidence.jsonl"),
    )
    server = GatewayServer(("127.0.0.1", 0), create_gateway(runtime, "client-secret"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        body = json.dumps(
            {
                "model": "engineering/ready",
                "stream": True,
                "messages": [{"role": "user", "content": "read the file"}],
            }
        )
        connection = HTTPConnection(host, port)
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=body,
            headers={"Authorization": "Bearer client-secret", "Content-Type": "application/json"},
        )
        response = connection.getresponse()
        events = [
            json.loads(line.removeprefix("data: "))
            for line in response.read().decode().splitlines()
            if line.startswith("data: {")
        ]

        assert response.status == 200
        assert events[0]["choices"][0]["delta"]["tool_calls"] == [{**tool_call, "index": 0}]
        assert events[-1]["choices"][0]["finish_reason"] == "tool_calls"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_gateway_reports_context_overflow_as_client_error(tmp_path):
    from orchestrator_runtime import ProviderError

    body = json.dumps({"error": {"message": "This model's maximum context length is 16384 tokens."}})

    class Overflow:
        def complete(self, request, timeout):
            raise ProviderError("provider HTTP 400: " + body, status=400, body=body)

    runtime = OrchestratorRuntime(
        CapabilityRegistry([worker("ready")]),
        {"ready": Overflow()},
        EvidenceStore(tmp_path / "evidence.jsonl"),
    )
    server = GatewayServer(("127.0.0.1", 0), create_gateway(runtime, "client-secret"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        connection = HTTPConnection(host, port)
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=json.dumps({"model": "engineering/ready", "messages": [{"role": "user", "content": "hi"}]}),
            headers={"Authorization": "Bearer client-secret", "Content-Type": "application/json"},
        )
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 400
        assert payload["error"]["code"] == "context_length_exceeded"
        assert "maximum context length" in payload["error"]["message"]
        connection.close()
    finally:
        server.shutdown()
        server.server_close()


def test_gateway_stream_gives_parallel_tool_calls_distinct_indexes(tmp_path):
    calls = [
        {"id": "a", "type": "function", "function": {"name": "find_files", "arguments": '{"pattern":"x"}'}},
        {"id": "b", "type": "function", "function": {"name": "list_dir", "arguments": '{"path":"tests"}'}},
    ]

    runtime = OrchestratorRuntime(CapabilityRegistry([worker("ready")]), {"ready": StreamingAdapter(tool_calls=[dict(c) for c in calls])}, EvidenceStore(tmp_path / "evidence.jsonl"))
    server = GatewayServer(("127.0.0.1", 0), create_gateway(runtime, "client-secret"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        connection = HTTPConnection(host, port)
        connection.request(
            "POST", "/v1/chat/completions",
            body=json.dumps({"model": "engineering/ready", "stream": True, "messages": [{"role": "user", "content": "go"}]}),
            headers={"Authorization": "Bearer client-secret", "Content-Type": "application/json"},
        )
        events = [json.loads(l.removeprefix("data: ")) for l in connection.getresponse().read().decode().splitlines() if l.startswith("data: {")]
        streamed = events[0]["choices"][0]["delta"]["tool_calls"]
        assert [c["index"] for c in streamed] == [0, 1]
        assert [c["function"]["name"] for c in streamed] == ["find_files", "list_dir"]
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_gateway_reasoning_effort_mapping(tmp_path):
    class CaptureAdapter:
        def __init__(self):
            self.last_request = None

        def complete(self, request, timeout, cancel=None, on_stream_start=None, on_stream_chunk=None):
            self.last_request = request
            return {"content": "ok", "tool_calls": []}

    adapter = CaptureAdapter()
    runtime = OrchestratorRuntime(CapabilityRegistry([worker("ready")]), {"ready": adapter}, EvidenceStore(tmp_path / "evidence.jsonl"))
    server = GatewayServer(("127.0.0.1", 0), create_gateway(runtime, "client-secret"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        conn = HTTPConnection(host, port)
        body = json.dumps({"model": "engineering/ready", "messages": [{"role": "user", "content": "hi"}], "reasoning_effort": "low"})
        conn.request("POST", "/v1/chat/completions", body=body, headers={"Authorization": "Bearer client-secret", "Content-Type": "application/json"})
        resp = conn.getresponse()
        assert resp.status == 200
        conn.close()

        conn = HTTPConnection(host, port)
        body = json.dumps({"model": "engineering/ready", "messages": [{"role": "user", "content": "hi"}]})
        conn.request("POST", "/v1/chat/completions", body=body, headers={"Authorization": "Bearer client-secret", "Content-Type": "application/json", "X-AIHost-Reasoning-Effort": "medium"})
        resp = conn.getresponse()
        assert resp.status == 200
        conn.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)

