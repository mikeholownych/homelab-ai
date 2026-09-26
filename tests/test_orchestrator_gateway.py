from __future__ import annotations

import json
import threading
from http.client import HTTPConnection

from orchestrator_gateway import GatewayServer, create_gateway
from orchestrator_runtime import CapabilityRegistry, EvidenceStore, InMemoryAdapter, OrchestratorRuntime
from tests.test_orchestrator_runtime import worker


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
        stream = response.read().decode()
        assert response.status == 200
        assert response.getheader("Content-Type") == "text/event-stream"
        assert "[DONE]" in stream
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_gateway_stream_preserves_tool_call_and_terminal_finish_reason(tmp_path):
    tool_call = {
        "id": "call-1",
        "type": "function",
        "function": {"name": "read", "arguments": '{"path":"README.md"}'},
    }

    class ToolCallAdapter:
        def complete(self, request, timeout):
            return {"content": "", "tool_calls": [tool_call]}

    runtime = OrchestratorRuntime(
        CapabilityRegistry([worker("ready")]),
        {"ready": ToolCallAdapter()},
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
        assert events[0]["choices"][0]["delta"]["tool_calls"] == [tool_call]
        assert events[-1]["choices"][0]["finish_reason"] == "tool_calls"
    finally:
        server.shutdown()
        thread.join(timeout=2)
