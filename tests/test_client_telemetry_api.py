from __future__ import annotations

import json
import threading
import time
from http.client import HTTPConnection

import pytest

from orchestrator_gateway import GatewayServer, create_gateway
from orchestrator_runtime import (
    CapabilityRegistry,
    EvidenceStore,
    InMemoryAdapter,
    OrchestratorRuntime,
)
from orchestrator_runtime.clients import Client, ClientRegistry, token_digest
from orchestrator_runtime.telemetry import (
    API_VERSION,
    METRICS_CATALOGUE,
    UNAVAILABLE_CAPABILITIES,
    RequestTelemetryBuffer,
    RequestTelemetryRecord,
)
from tests.test_orchestrator_runtime import worker


class StreamingTelemetryAdapter:
    supports_streaming = True

    def __init__(self, *, tokens=("Hello", " ", "world", "!"), chunk_delay=0.01):
        self.tokens = tokens
        self.chunk_delay = chunk_delay

    def complete(self, request, timeout, cancel=None, on_stream_start=None, on_stream_chunk=None):
        if on_stream_start:
            on_stream_start()
        time.sleep(self.chunk_delay)
        for i, tok in enumerate(self.tokens):
            time.sleep(self.chunk_delay)
            if on_stream_chunk:
                on_stream_chunk({"choices": [{"index": 0, "delta": {"content": tok}, "finish_reason": None}]})
        return {
            "content": "".join(self.tokens),
            "tool_calls": [],
            "provider_finish_reason": "stop",
            "usage": {"prompt_tokens": 12, "completion_tokens": len(self.tokens)},
        }


def _make_record(req_id: str, client_id: str, worker_id: str = "worker1", model: str = "engineering/lead") -> RequestTelemetryRecord:
    return RequestTelemetryRecord(
        request_id=req_id,
        client_id=client_id,
        worker_id=worker_id,
        pool="lead",
        model=model,
        model_id="m1",
        artifact_digest="sha256:1234567890abcdef",
        stream=False,
        priority="interactive",
        status="completed",
        termination="complete",
        finish_reason="stop",
        prompt_tokens=10,
        completion_tokens=5,
        cached_prompt_tokens=None,
        queue_duration_seconds=0.001,
        ttft_seconds=0.015,
        ttft_provenance="engine_reported_timings",
        inter_token_latency_seconds=0.005,
        itl_provenance="engine_reported_timings",
        duration_seconds=0.040,
        timestamp="2026-10-09T12:00:00Z",
    )


def _setup_test_gateway(tmp_path):
    """Sets up a GatewayServer with multiple clients of different scopes."""
    clients = ClientRegistry([
        Client("workload-only", token_digest("workload-token"), frozenset(["workload"])),
        Client("telemetry-client", token_digest("telemetry-token"), frozenset(["workload", "telemetry"])),
        Client("monitoring-client", token_digest("monitoring-token"), frozenset(["monitoring"])),
        Client("client-b", token_digest("client-b-token"), frozenset(["workload", "telemetry"])),
    ])

    registry = CapabilityRegistry([worker("worker1")])
    streaming_adapter = StreamingTelemetryAdapter()
    runtime = OrchestratorRuntime(
        registry,
        {"worker1": streaming_adapter},
        EvidenceStore(tmp_path / "evidence.jsonl"),
    )
    # create_gateway will attach clients to runtime
    server = GatewayServer(("127.0.0.1", 0), create_gateway(runtime, clients=clients))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, runtime


def test_buffer_capacity_and_client_isolation():
    buffer = RequestTelemetryBuffer(max_size=3)
    r1 = _make_record("req-1", "client-a")
    r2 = _make_record("req-2", "client-b")
    r3 = _make_record("req-3", "client-a", worker_id="worker2")
    r4 = _make_record("req-4", "client-a")

    buffer.record(r1)
    buffer.record(r2)
    buffer.record(r3)
    assert buffer.count() == 3

    # Add r4, r1 should be evicted (FIFO)
    buffer.record(r4)
    assert buffer.count() == 3
    assert buffer.get_by_id("req-1") is None
    assert buffer.get_by_id("req-4") is not None

    # Isolation check: client-a cannot see req-2
    assert buffer.get_by_id("req-2", client_id="client-a") is None
    assert buffer.get_by_id("req-2", client_id="client-b") is not None

    # Listing for client-a returns only client-a records (req-3, req-4)
    records_a = buffer.query(client_id="client-a")
    assert len(records_a) == 2
    assert {r.request_id for r in records_a} == {"req-3", "req-4"}


def test_unauthenticated_capabilities_rejected(tmp_path):
    server, thread, _ = _setup_test_gateway(tmp_path)
    try:
        host, port = server.server_address
        conn = HTTPConnection(host, port)
        conn.request("GET", "/v1/telemetry/capabilities")
        res = conn.getresponse()
        assert res.status == 401
        conn.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_authenticated_capabilities_discovery(tmp_path):
    server, thread, _ = _setup_test_gateway(tmp_path)
    try:
        host, port = server.server_address
        conn = HTTPConnection(host, port)
        # Any authenticated client can discover capabilities
        conn.request("GET", "/v1/telemetry/capabilities", headers={"Authorization": "Bearer workload-token"})
        res = conn.getresponse()
        assert res.status == 200
        data = json.loads(res.read().decode())
        assert data["api_version"] == API_VERSION
        assert data["version"] == API_VERSION
        assert "supported_metrics" in data
        assert len(data["supported_metrics"]) == len(METRICS_CATALOGUE)

        metric_names = [m["metric"] for m in data["supported_metrics"]]
        assert "ttft_seconds" in metric_names
        assert "inter_token_latency_seconds" in metric_names
        assert "queue_wait_seconds" in metric_names
        assert "duration_seconds" in metric_names
        assert "prompt_tokens" in metric_names
        assert "completion_tokens" in metric_names
        assert "kv_cache_usage_ratio" in metric_names
        assert "prefix_cache_hit_ratio" in metric_names
        assert "requests_running" in metric_names

        assert "scopes" in data
        assert "appliance" in data["scopes"]
        assert "worker" in data["scopes"]
        assert "request" in data["scopes"]

        assert "retrieval_limits" in data
        assert data["retrieval_limits"]["max_limit"] == 100
        assert data["retrieval_limits"]["default_limit"] == 10

        assert "request_correlation" in data
        assert data["request_correlation"]["available"] is True

        assert "unavailable_capabilities" in data
        assert len(data["unavailable_capabilities"]) == len(UNAVAILABLE_CAPABILITIES)
        unavailable_caps = [c["capability"] for c in data["unavailable_capabilities"]]
        assert "gpu_hardware_sensors_via_api" in unavailable_caps
        assert "raw_prompt_payload_storage" in unavailable_caps
        conn.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_scope_authorization_enforcement(tmp_path):
    server, thread, _ = _setup_test_gateway(tmp_path)
    try:
        host, port = server.server_address

        # 1. Workload-only client cannot access aggregate appliance or worker scope
        conn = HTTPConnection(host, port)
        conn.request("GET", "/v1/telemetry/inference?scope=appliance", headers={"Authorization": "Bearer workload-token"})
        res = conn.getresponse()
        assert res.status == 403
        conn.close()

        conn = HTTPConnection(host, port)
        conn.request("GET", "/v1/telemetry/inference?scope=worker", headers={"Authorization": "Bearer workload-token"})
        res = conn.getresponse()
        assert res.status == 403
        conn.close()

        conn = HTTPConnection(host, port)
        conn.request("GET", "/v1/telemetry/inference?scope=request", headers={"Authorization": "Bearer workload-token"})
        res = conn.getresponse()
        # Request scope without request_id is denied for workload-only without telemetry scope
        assert res.status == 403
        conn.close()

        # 2. Telemetry client can access appliance, worker, and request scopes
        conn = HTTPConnection(host, port)
        conn.request("GET", "/v1/telemetry/inference?scope=appliance", headers={"Authorization": "Bearer telemetry-token"})
        res = conn.getresponse()
        assert res.status == 200
        appliance_data = json.loads(res.read().decode())
        assert appliance_data["scope"] == "appliance"
        assert "appliance" in appliance_data
        conn.close()

        conn = HTTPConnection(host, port)
        conn.request("GET", "/v1/telemetry/inference?scope=worker", headers={"Authorization": "Bearer telemetry-token"})
        res = conn.getresponse()
        assert res.status == 200
        worker_data = json.loads(res.read().decode())
        assert worker_data["scope"] == "worker"
        assert "workers" in worker_data
        conn.close()

        # 3. Monitoring client can access appliance and worker scopes
        conn = HTTPConnection(host, port)
        conn.request("GET", "/v1/telemetry/inference?scope=appliance", headers={"Authorization": "Bearer monitoring-token"})
        res = conn.getresponse()
        assert res.status == 200
        conn.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_request_correlation_and_isolation(tmp_path):
    server, thread, _ = _setup_test_gateway(tmp_path)
    try:
        host, port = server.server_address

        # Perform streaming request as telemetry-client (client A)
        chat_body = json.dumps({
            "model": "engineering/worker1",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": True,
        })
        conn = HTTPConnection(host, port)
        conn.request("POST", "/v1/chat/completions", body=chat_body, headers={
            "Authorization": "Bearer telemetry-token",
            "Content-Type": "application/json",
        })
        res = conn.getresponse()
        assert res.status == 200
        req_id_a = res.getheader("X-Request-ID")
        assert req_id_a is not None
        # Drain response
        res.read()
        conn.close()

        # Perform request as client-b
        conn = HTTPConnection(host, port)
        conn.request("POST", "/v1/chat/completions", body=chat_body, headers={
            "Authorization": "Bearer client-b-token",
            "Content-Type": "application/json",
        })
        res = conn.getresponse()
        assert res.status == 200
        req_id_b = res.getheader("X-Request-ID")
        assert req_id_b is not None
        res.read()
        conn.close()

        # Client A queries its own request -> 200
        conn = HTTPConnection(host, port)
        conn.request("GET", f"/v1/telemetry/inference?request_id={req_id_a}", headers={"Authorization": "Bearer telemetry-token"})
        res = conn.getresponse()
        assert res.status == 200
        data_a = json.loads(res.read().decode())
        assert "requests" in data_a
        assert len(data_a["requests"]) == 1
        rec_a = data_a["requests"][0]
        assert rec_a["request_id"] == req_id_a
        assert rec_a["client_id"] == "telemetry-client"
        assert rec_a["stream"] is True
        assert rec_a["ttft_provenance"] == "streaming_first_chunk"
        assert rec_a["itl_provenance"] == "streaming_delta_intervals"
        assert rec_a["ttft_seconds"] is not None and rec_a["ttft_seconds"] > 0
        assert rec_a["inter_token_latency_seconds"] is not None and rec_a["inter_token_latency_seconds"] > 0
        assert rec_a["prompt_tokens"] == 12
        assert rec_a["completion_tokens"] == 4
        # Verify no raw prompt or completion is in the record
        assert "content" not in rec_a
        assert "messages" not in rec_a
        assert "prompt" not in rec_a
        conn.close()

        # Workload-only client querying its own request by request_id should succeed if it made the request
        # But if client-b attempts to query Client A's request -> 404 (isolation prevents cross-client lookup)
        conn = HTTPConnection(host, port)
        conn.request("GET", f"/v1/telemetry/inference?request_id={req_id_a}", headers={"Authorization": "Bearer client-b-token"})
        res = conn.getresponse()
        assert res.status == 404
        conn.close()

        # Client B queries its own request -> 200
        conn = HTTPConnection(host, port)
        conn.request("GET", f"/v1/telemetry/inference?request_id={req_id_b}", headers={"Authorization": "Bearer client-b-token"})
        res = conn.getresponse()
        assert res.status == 200
        data_b = json.loads(res.read().decode())
        rec_b = data_b["requests"][0]
        assert rec_b["request_id"] == req_id_b
        assert rec_b["client_id"] == "client-b"
        conn.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_parameter_validation_and_error_handling(tmp_path):
    server, thread, _ = _setup_test_gateway(tmp_path)
    try:
        host, port = server.server_address

        # 1. Invalid limit (0)
        conn = HTTPConnection(host, port)
        conn.request("GET", "/v1/telemetry/inference?scope=appliance&limit=0", headers={"Authorization": "Bearer telemetry-token"})
        res = conn.getresponse()
        assert res.status == 400
        assert "limit" in json.loads(res.read().decode())["error"]["message"].lower()
        conn.close()

        # 2. Invalid limit (> 100)
        conn = HTTPConnection(host, port)
        conn.request("GET", "/v1/telemetry/inference?scope=appliance&limit=105", headers={"Authorization": "Bearer telemetry-token"})
        res = conn.getresponse()
        assert res.status == 400
        conn.close()

        # 3. Invalid limit (non-integer)
        conn = HTTPConnection(host, port)
        conn.request("GET", "/v1/telemetry/inference?scope=appliance&limit=abc", headers={"Authorization": "Bearer telemetry-token"})
        res = conn.getresponse()
        assert res.status == 400
        conn.close()

        # 4. Invalid scope
        conn = HTTPConnection(host, port)
        conn.request("GET", "/v1/telemetry/inference?scope=galaxy", headers={"Authorization": "Bearer telemetry-token"})
        res = conn.getresponse()
        assert res.status == 400
        assert "scope" in json.loads(res.read().decode())["error"]["message"].lower()
        conn.close()

        # 5. Unsupported metric
        conn = HTTPConnection(host, port)
        conn.request("GET", "/v1/telemetry/inference?scope=appliance&metric=nonexistent_latency", headers={"Authorization": "Bearer telemetry-token"})
        res = conn.getresponse()
        assert res.status == 400
        assert "metric" in json.loads(res.read().decode())["error"]["message"].lower()
        conn.close()

        # 6. Unknown worker_id
        conn = HTTPConnection(host, port)
        conn.request("GET", "/v1/telemetry/inference?scope=worker&worker_id=worker99", headers={"Authorization": "Bearer telemetry-token"})
        res = conn.getresponse()
        assert res.status == 404
        conn.close()

        # 7. Non-existent request_id
        conn = HTTPConnection(host, port)
        conn.request("GET", "/v1/telemetry/inference?request_id=does-not-exist", headers={"Authorization": "Bearer telemetry-token"})
        res = conn.getresponse()
        assert res.status == 404
        conn.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)


class NonStreamingTelemetryAdapter:
    supports_streaming = False

    def complete(self, request, timeout, cancel=None, on_stream_start=None, on_stream_chunk=None):
        return {
            "content": "Non-streaming answer",
            "tool_calls": [],
            "provider_finish_reason": "stop",
            "usage": {"prompt_tokens": 15, "completion_tokens": 8, "prompt_tokens_details": {"cached_tokens": 5}},
            "timings": {
                "prompt_ms": 25.5,
                "predicted_ms": 160.0,
                "predicted_n": 8,
                "predicted_per_token_ms": 20.0,
            },
        }


def test_non_streaming_telemetry_provenance_and_filtering(tmp_path):
    clients = ClientRegistry([
        Client("telemetry-client", token_digest("telemetry-token"), frozenset(["workload", "telemetry"])),
    ])
    registry = CapabilityRegistry([worker("worker1")])
    adapter = NonStreamingTelemetryAdapter()
    runtime = OrchestratorRuntime(
        registry,
        {"worker1": adapter},
        EvidenceStore(tmp_path / "evidence.jsonl"),
    )
    server = GatewayServer(("127.0.0.1", 0), create_gateway(runtime, clients=clients))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        chat_body = json.dumps({
            "model": "engineering/worker1",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": False,
        })
        conn = HTTPConnection(host, port)
        conn.request("POST", "/v1/chat/completions", body=chat_body, headers={
            "Authorization": "Bearer telemetry-token",
            "Content-Type": "application/json",
        })
        res = conn.getresponse()
        assert res.status == 200
        req_id = res.getheader("X-Request-ID")
        res.read()
        conn.close()

        # Query all metrics for this request
        conn = HTTPConnection(host, port)
        conn.request("GET", f"/v1/telemetry/inference?request_id={req_id}", headers={"Authorization": "Bearer telemetry-token"})
        res = conn.getresponse()
        assert res.status == 200
        data = json.loads(res.read().decode())
        rec = data["requests"][0]
        assert rec["stream"] is False
        assert rec["ttft_seconds"] == pytest.approx(0.0255, rel=1e-3)
        assert rec["ttft_provenance"] == "engine_reported_timings"
        assert rec["inter_token_latency_seconds"] == pytest.approx(0.02, rel=1e-3)
        assert rec["itl_provenance"] == "engine_reported_timings"
        assert rec["cached_prompt_tokens"] == 5
        assert rec["finish_reason"] == "stop"
        conn.close()

        # Query with metric filter: metric=ttft_seconds
        conn = HTTPConnection(host, port)
        conn.request("GET", f"/v1/telemetry/inference?request_id={req_id}&metric=ttft_seconds", headers={"Authorization": "Bearer telemetry-token"})
        res = conn.getresponse()
        assert res.status == 200
        filtered_data = json.loads(res.read().decode())
        filtered_rec = filtered_data["requests"][0]
        assert "ttft_seconds" in filtered_rec
        assert "ttft_provenance" in filtered_rec
        assert "inter_token_latency_seconds" not in filtered_rec
        assert "completion_tokens" not in filtered_rec
        conn.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_worker_and_appliance_telemetry(tmp_path):
    server, thread, runtime = _setup_test_gateway(tmp_path)
    try:
        host, port = server.server_address

        # 1. Worker scope telemetry
        conn = HTTPConnection(host, port)
        conn.request("GET", "/v1/telemetry/inference?scope=worker&worker_id=worker1", headers={"Authorization": "Bearer telemetry-token"})
        res = conn.getresponse()
        assert res.status == 200
        worker_data = json.loads(res.read().decode())
        assert worker_data["scope"] == "worker"
        assert len(worker_data["workers"]) == 1
        w_obs = worker_data["workers"][0]
        assert w_obs["worker_id"] == "worker1"
        assert "healthy" in w_obs
        assert "available" in w_obs
        assert "inflight_requests" in w_obs
        assert "latency_distributions" in w_obs
        assert "ttft_seconds" in w_obs["latency_distributions"]
        assert "inter_token_latency_seconds" in w_obs["latency_distributions"]
        assert "queue_wait_seconds" in w_obs["latency_distributions"]
        conn.close()

        # 2. Appliance scope telemetry
        conn = HTTPConnection(host, port)
        conn.request("GET", "/v1/telemetry/inference?scope=appliance", headers={"Authorization": "Bearer telemetry-token"})
        res = conn.getresponse()
        assert res.status == 200
        appliance_data = json.loads(res.read().decode())
        assert appliance_data["scope"] == "appliance"
        app_obs = appliance_data["appliance"]
        assert "admission" in app_obs
        assert "queue_depth_by_pool" in app_obs["admission"]
        assert "workers_summary" in app_obs
        assert app_obs["workers_summary"]["total"] >= 1
        assert "gateway" in app_obs
        assert app_obs["gateway"]["status"] == "healthy"
        conn.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)

