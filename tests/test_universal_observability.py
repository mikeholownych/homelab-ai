"""Tests for universal worker observability: Queue Wait, TTFT, and ITL across all worker types."""
from __future__ import annotations

import json
import threading
import time
from http.client import HTTPConnection

from orchestrator_gateway import GatewayServer, create_gateway
from orchestrator_runtime import (
    AdmissionController,
    CapabilityRegistry,
    EvidenceStore,
    MetricsRegistry,
    OrchestratorRuntime,
)
from orchestrator_runtime.admission import Ticket
from tests.test_orchestrator_runtime import worker


class MultiChunkStreamingAdapter:
    supports_streaming = True

    def __init__(self, chunks: list[str] | None = None):
        self.chunks = chunks or ["Hello", " ", "world", "!"]

    def complete(self, request, timeout, cancel=None, on_stream_start=None, on_stream_chunk=None):
        if on_stream_start:
            on_stream_start()
        for chunk in self.chunks:
            time.sleep(0.01)
            if on_stream_chunk:
                on_stream_chunk({"choices": [{"index": 0, "delta": {"content": chunk}, "finish_reason": None}]})
        return {"content": "".join(self.chunks), "provider_finish_reason": "stop"}


class TimingsAdapter:
    supports_streaming = False

    def __init__(self, prompt_ms: float = 30.0, predicted_per_token_ms: float = 15.0):
        self.prompt_ms = prompt_ms
        self.predicted_per_token_ms = predicted_per_token_ms

    def complete(self, request, timeout, cancel=None):
        return {
            "content": "Result from engine with timings",
            "provider_finish_reason": "stop",
            "timings": {
                "prompt_ms": self.prompt_ms,
                "predicted_per_token_ms": self.predicted_per_token_ms,
            },
        }


def test_admission_controller_observes_queue_wait_time():
    metrics = MetricsRegistry()
    admission = AdmissionController(metrics=metrics)
    t = Ticket(pool="lead", client_id="c1", priority="interactive", enqueued_at=time.monotonic() - 0.05)
    worker_id = admission.acquire(t, lambda: ["w1"])
    assert worker_id == "w1"
    
    # Check that scheduler_queue_wait_seconds has been observed
    rendered = metrics.render_prometheus_text()
    assert 'aihost_scheduler_queue_wait_seconds_count{worker_id="w1"} 1' in rendered
    assert 'aihost_scheduler_queue_wait_seconds_sum{worker_id="w1"}' in rendered


def test_streaming_request_observes_ttft_and_inter_token_latency(tmp_path):
    w = worker("ready")
    registry = CapabilityRegistry([w])
    metrics = MetricsRegistry()
    runtime = OrchestratorRuntime(
        registry,
        {"ready": MultiChunkStreamingAdapter(["First", " second", " third"])},
        EvidenceStore(tmp_path / "evidence.jsonl"),
        metrics=metrics,
    )
    server = GatewayServer(("127.0.0.1", 0), create_gateway(runtime, "test-secret"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        conn = HTTPConnection(host, port)
        body = json.dumps({"model": "engineering/ready", "stream": True, "messages": [{"role": "user", "content": "hi"}]})
        conn.request("POST", "/v1/chat/completions", body=body, headers={
            "Authorization": "Bearer test-secret",
            "Content-Type": "application/json",
        })
        resp = conn.getresponse()
        assert resp.status == 200
        payload = resp.read().decode()
        assert "data: " in payload
        conn.close()

        rendered = metrics.render_prometheus_text()
        # TTFT should have 1 observation
        assert 'aihost_inference_ttft_seconds_count{worker_id="ready"} 1' in rendered
        # ITL should have 2 observations (for the 2nd and 3rd chunks)
        assert 'aihost_inference_inter_token_latency_seconds_count{worker_id="ready"} 2' in rendered
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_non_streaming_timings_observe_ttft_and_itl(tmp_path):
    w = worker("ready")
    registry = CapabilityRegistry([w])
    metrics = MetricsRegistry()
    runtime = OrchestratorRuntime(
        registry,
        {"ready": TimingsAdapter(prompt_ms=45.0, predicted_per_token_ms=12.0)},
        EvidenceStore(tmp_path / "evidence.jsonl"),
        metrics=metrics,
    )
    server = GatewayServer(("127.0.0.1", 0), create_gateway(runtime, "test-secret"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        conn = HTTPConnection(host, port)
        body = json.dumps({"model": "engineering/ready", "stream": False, "messages": [{"role": "user", "content": "hi"}]})
        conn.request("POST", "/v1/chat/completions", body=body, headers={
            "Authorization": "Bearer test-secret",
            "Content-Type": "application/json",
        })
        resp = conn.getresponse()
        assert resp.status == 200
        conn.close()

        rendered = metrics.render_prometheus_text()
        # TTFT: 45ms = 0.045s
        assert 'aihost_inference_ttft_seconds_count{worker_id="ready"} 1' in rendered
        assert 'aihost_inference_ttft_seconds_sum{worker_id="ready"} 0.045' in rendered
        # ITL: 12ms = 0.012s
        assert 'aihost_inference_inter_token_latency_seconds_count{worker_id="ready"} 1' in rendered
        assert 'aihost_inference_inter_token_latency_seconds_sum{worker_id="ready"} 0.012' in rendered
    finally:
        server.shutdown()
        thread.join(timeout=2)
