"""Tests for OpenTelemetry OTLP distributed tracing exporter."""
from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
from pathlib import Path

import pytest

from orchestrator_runtime import (
    CapabilityRegistry,
    EvidenceStore,
    InMemoryAdapter,
    OTLPTraceExporter,
    OrchestratorRuntime,
    Span,
    TraceContext,
)
from tests.test_orchestrator_runtime import worker


def test_span_otlp_json_serialization():
    span = Span(
        name="inference",
        trace_id="4bf92f3577b34da6a3ce929d0e0e4736",
        span_id="00f067aa0ba902b7",
        parent_span_id="5fb397be34d23b0f",
        start_time_ns=1700000000000000000,
        end_time_ns=1700000000500000000,
        attributes={
            "gen_ai.request.model": "qwen2.5-coder-32b",
            "gen_ai.usage.prompt_tokens": 128,
            "stream": True,
            "cost": 0.0045,
        },
        status_code=1,
    )
    payload = span.to_otlp_json()
    assert payload["traceId"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert payload["spanId"] == "00f067aa0ba902b7"
    assert payload["parentSpanId"] == "5fb397be34d23b0f"
    assert payload["name"] == "inference"
    assert payload["status"]["code"] == 1

    attr_map = {a["key"]: a["value"] for a in payload["attributes"]}
    assert attr_map["gen_ai.request.model"] == {"stringValue": "qwen2.5-coder-32b"}
    assert attr_map["gen_ai.usage.prompt_tokens"] == {"intValue": "128"}
    assert attr_map["stream"] == {"boolValue": True}
    assert attr_map["cost"] == {"doubleValue": 0.0045}


def test_otlp_trace_exporter_hierarchy_and_collector():
    received_batches = []

    class MockCollectorHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            received_batches.append(json.loads(body.decode("utf-8")))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"partialSuccess": {}}')

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), MockCollectorHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    collector_port = server.server_address[1]
    collector_url = f"http://127.0.0.1:{collector_port}/v1/traces"

    try:
        exporter = OTLPTraceExporter(
            endpoint=collector_url,
            batch_size=2,
            batch_timeout_seconds=0.1,
        )

        root_ctx = TraceContext.new_root()
        with exporter.span("ingress", root_ctx, attributes={"http.method": "POST"}) as (s1, child1):
            with exporter.span("inference", child1, attributes={"model": "test-model"}) as (s2, child2):
                pass

        exporter.flush()
        exporter.shutdown()

        # Verify exporter recorded spans
        spans = exporter.exported_spans
        assert len(spans) == 2
        inference_span = [s for s in spans if s.name == "inference"][0]
        ingress_span = [s for s in spans if s.name == "ingress"][0]
        assert inference_span.parent_span_id == ingress_span.span_id

        # Verify collector received batches
        assert len(received_batches) >= 1
        batch = received_batches[0]
        resource_spans = batch["resourceSpans"][0]
        assert resource_spans["resource"]["attributes"][0]["value"]["stringValue"] == "aihost-orchestrator"
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join()


def test_runtime_complete_emits_otlp_spans(tmp_path):
    w1 = worker("w1")
    exporter = OTLPTraceExporter()  # in-memory only (no endpoint)
    runtime = OrchestratorRuntime(
        CapabilityRegistry([w1]),
        {"w1": InMemoryAdapter("reply token")},
        EvidenceStore(tmp_path / "evidence.jsonl"),
        tracer=exporter,
    )

    req = {"model": "engineering/w1", "messages": [{"role": "user", "content": "hello"}]}
    res = runtime.complete(req)
    assert res["status"] == "ok"

    spans = exporter.exported_spans
    names = [s.name for s in spans]
    assert "cache" in names
    assert "admission" in names
    assert "inference" in names

    inf_span = [s for s in spans if s.name == "inference"][0]
    assert inf_span.attributes["gen_ai.request.model"] == "engineering/w1"
    assert inf_span.attributes["aihost.worker_id"] == "w1"
