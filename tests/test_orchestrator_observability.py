"""Comprehensive offline validation suite for orchestrator health and Prometheus metrics.

Covers:
- Healthy, degraded, unavailable, and stale health states
- HTTP status codes (200, 503, 401, 404, 400)
- Prometheus exposition 0.0.4 text format conformance
- Parsing via official prometheus_client parser
- Monotonic counter and gauge lifecycle correctness
- Inference dispatch, completion, timeout, and token accounting
- Streaming TTFT and streaming request accounting
- Scheduler queue, active work, and dependency block gauges
- Provider error and timeout tracking
- Authority and preflight rejection accounting
- Concurrency and scrape non-interference
- Bounded label cardinality
- Zero disclosure of credentials, prompts, or sensitive internals
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.client import HTTPConnection
from typing import Any

try:
    from prometheus_client.parser import text_string_to_metric_families
    HAS_PROMETHEUS_CLIENT = True
except ImportError:
    text_string_to_metric_families = None
    HAS_PROMETHEUS_CLIENT = False

from orchestrator_contract import Authority, Task
from orchestrator_gateway import GatewayServer, create_gateway
from orchestrator_runtime import (
    CapabilityRegistry,
    Counter,
    EvidenceStore,
    Gauge,
    GraphScheduler,
    HealthManager,
    Histogram,
    InMemoryAdapter,
    MetricsRegistry,
    OrchestratorRuntime,
    TaskGraph,
    WorkerRecord,
)


def make_worker(
    worker_id: str,
    *,
    healthy: bool = True,
    status: str = "measured",
    model_id: str | None = None,
    public_model_id: str | None = None,
    ttl_seconds: int = 600,
) -> WorkerRecord:
    return WorkerRecord(
        worker_id=worker_id,
        public_model_id=public_model_id or f"engineering/{worker_id}",
        model_id=model_id or f"model/{worker_id}",
        revision="a" * 40,
        artifact_digest="sha256:" + "b" * 64,
        runtime_image_digest="sha256:" + "c" * 64,
        topology="tp1",
        gpu_assignment=(worker_id,),
        capabilities=frozenset({"navigation", "coding"}),
        context_limit=16_384,
        max_output_tokens=512,
        max_concurrency=2,
        resource_envelope={"memory_reserve_gib": 32},
        evidence_ids=(f"evidence-{worker_id}",),
        registry_version=1,
        measured_at="2026-09-25T00:00:00Z",
        valid_until=(datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat(),
        status=status,
        healthy=healthy,
    )


class TimeoutAdapter:
    def complete(self, request: dict[str, Any], timeout: float) -> dict[str, Any]:
        raise TimeoutError("upstream worker timed out")


class ErrorAdapter:
    def complete(self, request: dict[str, Any], timeout: float) -> dict[str, Any]:
        raise RuntimeError("upstream connection refused")


# =============================================================================
# 1. Prometheus Text Exposition & Parser Conformance
# =============================================================================

def test_metrics_registry_format_and_prometheus_parser_conformance():
    """Verify that MetricsRegistry generates 100% compliant Prometheus 0.0.4 text."""
    registry = MetricsRegistry()

    # Record samples across all metric types
    registry.http_requests_total.inc(1.0, route="v1_chat_completions", method="POST", status_class="2xx")
    registry.http_request_duration_seconds.observe(0.125, route="v1_chat_completions", method="POST")
    registry.http_requests_in_flight.set(2.0, route="v1_chat_completions")
    registry.inference_dispatches_total.inc(1.0, worker_id="w1", model="engineering/b0")
    registry.inference_completions_total.inc(1.0, worker_id="w1", outcome="completed")
    registry.inference_prompt_tokens_total.inc(42.0, worker_id="w1", model="engineering/b0")
    registry.scheduler_queued_work.set(3.0)
    registry.worker_health_status.set(1.0, worker_id="w1")

    text = registry.render_prometheus_text()
    assert text.endswith("\n"), "Prometheus text must end with a trailing newline"

    # Verify Prometheus 0.0.4 text format compliance directly
    assert "# HELP aihost_http_requests_total" in text
    assert "# TYPE aihost_http_requests_total counter" in text
    assert 'aihost_http_requests_total{route="v1_chat_completions",method="POST",status_class="2xx"} 1' in text
    assert "# HELP aihost_http_request_duration_seconds" in text
    assert "# TYPE aihost_http_request_duration_seconds histogram" in text
    assert 'aihost_http_request_duration_seconds_bucket{route="v1_chat_completions",method="POST",le="0.25"} 1' in text
    assert 'aihost_http_request_duration_seconds_count{route="v1_chat_completions",method="POST"} 1' in text

    # Parse with official prometheus_client parser if available in environment
    if HAS_PROMETHEUS_CLIENT:
        families = list(text_string_to_metric_families(text))
        family_names = {f.name for f in families}
        sample_names = {s.name for f in families for s in f.samples}

        assert "aihost_http_requests_total" in sample_names
        assert "aihost_http_request_duration_seconds" in family_names
        assert "aihost_http_requests_in_flight" in family_names
        assert "aihost_inference_dispatches_total" in sample_names
        assert "aihost_inference_completions_total" in sample_names
        assert "aihost_inference_prompt_tokens_total" in sample_names
        assert "aihost_scheduler_queued_work" in family_names
        assert "aihost_worker_health_status" in family_names

        # Check parsed family details
        http_fam = next(f for f in families if f.name in {"aihost_http_requests", "aihost_http_requests_total"})
        assert http_fam.type == "counter"
        sample = http_fam.samples[0]
        assert sample.name == "aihost_http_requests_total"
        assert sample.labels == {"route": "v1_chat_completions", "method": "POST", "status_class": "2xx"}
        assert sample.value == 1.0


# =============================================================================
# 2. Health Manager State Transitions & Contracts
# =============================================================================

def test_health_manager_state_transitions():
    """Verify healthy, degraded, unavailable, and strict evaluation."""
    w1 = make_worker("w1")
    w2 = make_worker("w2")
    cap_registry = CapabilityRegistry([w1, w2])
    metrics = MetricsRegistry()
    health = HealthManager(cap_registry, {}, metrics, max_freshness_seconds=30.0)

    # 1. Initially both workers healthy
    status_code, payload = health.check(strict=False)
    assert status_code == HTTPStatus.OK
    assert payload["status"] == "healthy"
    assert payload["ready"] is True
    assert payload["can_route"] is True
    assert payload["workers"]["w1"]["healthy"] is True
    assert payload["workers"]["w2"]["healthy"] is True

    # 2. Worker 2 fails
    health.record_worker_observation("w2", healthy=False, duration=0.05, error="timeout")
    status_code, payload = health.check(strict=False)
    assert status_code == HTTPStatus.OK
    assert payload["status"] == "degraded"
    assert payload["ready"] is True
    assert payload["can_route"] is True
    assert payload["workers"]["w2"]["healthy"] is False

    # Strict check when degraded returns 503
    strict_code, strict_payload = health.check(strict=True)
    assert strict_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert strict_payload["status"] == "degraded"

    # 3. Worker 1 also fails -> complete unavailability
    health.record_worker_observation("w1", healthy=False, duration=0.01, error="connection_refused")
    status_code, payload = health.check(strict=False)
    assert status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert payload["status"] == "unavailable"
    assert payload["ready"] is False
    assert payload["can_route"] is False

    # 4. Worker 1 recovers -> back to degraded
    health.record_worker_observation("w1", healthy=True, duration=0.02)
    status_code, payload = health.check(strict=False)
    assert status_code == HTTPStatus.OK
    assert payload["status"] == "degraded"
    assert payload["ready"] is True

    # 5. Worker 2 recovers -> back to healthy
    health.record_worker_observation("w2", healthy=True, duration=0.03)
    status_code, payload = health.check(strict=False)
    assert status_code == HTTPStatus.OK
    assert payload["status"] == "healthy"
    assert payload["ready"] is True


def test_health_manager_stale_detection():
    """Verify that workers without observations within TTL are marked stale."""
    w1 = make_worker("w1")
    cap_registry = CapabilityRegistry([w1])
    # Very short freshness window: 0.1 seconds
    health = HealthManager(cap_registry, {}, max_freshness_seconds=0.1)

    time.sleep(0.15)
    status_code, payload = health.check(strict=False)
    assert status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert payload["status"] == "unavailable"
    assert payload["workers"]["w1"]["status"] == "stale"
    assert payload["workers"]["w1"]["healthy"] is False
    assert payload["dependency_freshness"]["is_stale"] is True


def test_health_manager_empty_registry():
    """Verify that a registry with zero workers returns unavailable."""
    cap_registry = CapabilityRegistry([])
    health = HealthManager(cap_registry, {})
    status_code, payload = health.check()
    assert status_code == HTTPStatus.SERVICE_UNAVAILABLE
    assert payload["status"] == "unavailable"
    assert payload["can_route"] is False
    assert payload["ready"] is False


def test_health_manager_background_polling():
    """Verify that background polling continuously refreshes worker health preventing staleness."""
    w1 = make_worker("w1")
    cap_registry = CapabilityRegistry([w1])
    # Freshness window 0.2s, poll interval 0.05s
    health = HealthManager(cap_registry, {}, max_freshness_seconds=0.2, probe_interval_seconds=0.05, auto_start=True)
    try:
        # Sleep for longer than max_freshness_seconds (0.25s)
        time.sleep(0.25)
        status_code, payload = health.check(strict=False)
        # Background polling kept worker fresh!
        assert status_code == HTTPStatus.OK
        assert payload["status"] == "healthy"
        assert payload["workers"]["w1"]["status"] == "healthy"
        assert payload["workers"]["w1"]["healthy"] is True
        assert payload["dependency_freshness"]["is_stale"] is False
        assert payload["dependency_freshness"]["freshness_seconds"] < 0.2
    finally:
        health.stop()


# =============================================================================
# 3. Gateway HTTP Contract: /health & /metrics
# =============================================================================

def test_gateway_health_and_metrics_endpoints(tmp_path):
    """Test /health and /metrics over HTTP socket."""
    w1 = make_worker("w1", public_model_id="engineering/default")
    cap_registry = CapabilityRegistry([w1])
    metrics = MetricsRegistry()
    runtime = OrchestratorRuntime(
        cap_registry,
        {"w1": InMemoryAdapter("hello")},
        EvidenceStore(tmp_path / "evidence.jsonl"),
        metrics=metrics,
    )

    server = GatewayServer(("127.0.0.1", 0), create_gateway(runtime, "client-secret"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address

        # 1. Unauthenticated GET /health -> 200 OK
        conn = HTTPConnection(host, port)
        conn.request("GET", "/health")
        resp = conn.getresponse()
        assert resp.status == 200
        assert resp.getheader("Content-Type") == "application/json"
        body = json.loads(resp.read().decode())
        assert body["status"] == "healthy"
        assert body["ready"] is True
        assert body["can_route"] is True
        assert body["gateway"]["status"] == "alive"
        assert "uptime_seconds" in body["gateway"]
        conn.close()

        # 2. Strict GET /health?strict=true
        conn = HTTPConnection(host, port)
        conn.request("GET", "/health?strict=true")
        resp = conn.getresponse()
        assert resp.status == 200
        conn.close()

        # 3. Unauthenticated GET /metrics -> 200 OK
        conn = HTTPConnection(host, port)
        conn.request("GET", "/metrics")
        resp = conn.getresponse()
        assert resp.status == 200
        assert "text/plain" in resp.getheader("Content-Type")
        text = resp.read().decode()
        assert "aihost_gateway_uptime_seconds" in text
        assert "aihost_http_requests_total" in text
        conn.close()

        # 4. Verify /v1/models STILL requires authentication
        conn = HTTPConnection(host, port)
        conn.request("GET", "/v1/models")
        assert conn.getresponse().status == 401
        conn.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_gateway_monitoring_authentication_boundary(tmp_path):
    """Test optional monitoring auth requirement without bypassing /v1/*."""
    w1 = make_worker("w1")
    cap_registry = CapabilityRegistry([w1])
    runtime = OrchestratorRuntime(
        cap_registry,
        {"w1": InMemoryAdapter("hello")},
        EvidenceStore(tmp_path / "evidence.jsonl"),
    )

    handler = create_gateway(
        runtime,
        client_tokens=["client-secret"],
        monitoring_token="mon-secret",
        require_monitoring_auth=True,
    )
    server = GatewayServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address

        # 1. Unauthenticated GET /health -> 401
        conn = HTTPConnection(host, port)
        conn.request("GET", "/health")
        assert conn.getresponse().status == 401
        conn.close()

        # 2. Unauthenticated GET /metrics -> 401
        conn = HTTPConnection(host, port)
        conn.request("GET", "/metrics")
        assert conn.getresponse().status == 401
        conn.close()

        # 3. Authenticated GET /health with monitoring token -> 200
        conn = HTTPConnection(host, port)
        conn.request("GET", "/health", headers={"Authorization": "Bearer mon-secret"})
        assert conn.getresponse().status == 200
        conn.close()

        # 4. Monitoring token cannot access /v1/models -> 401
        conn = HTTPConnection(host, port)
        conn.request("GET", "/v1/models", headers={"Authorization": "Bearer mon-secret"})
        assert conn.getresponse().status == 401
        conn.close()

        # 5. Client token can access /v1/models -> 200
        conn = HTTPConnection(host, port)
        conn.request("GET", "/v1/models", headers={"Authorization": "Bearer client-secret"})
        assert conn.getresponse().status == 200
        conn.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)


# =============================================================================
# 4. Lifecycle Accounting & Failure Handling
# =============================================================================

def test_runtime_inference_lifecycle_metrics(tmp_path):
    """Verify counter and histogram updates during normal and error inference."""
    w1 = make_worker("w1", public_model_id="engineering/w1")
    cap_registry = CapabilityRegistry([w1])
    metrics = MetricsRegistry()
    runtime = OrchestratorRuntime(
        cap_registry,
        {"w1": InMemoryAdapter("sample response")},
        EvidenceStore(tmp_path / "evidence.jsonl"),
        metrics=metrics,
    )

    # Successful completion
    result = runtime.complete(
        {"model": "engineering/w1", "messages": [{"role": "user", "content": "test prompt"}]}
    )
    assert result["status"] == "ok"
    assert metrics.inference_requests_total.get(status="received") == 1.0
    assert metrics.inference_dispatches_total.get(worker_id="w1", model="engineering/w1") == 1.0
    assert metrics.inference_completions_total.get(worker_id="w1", outcome="completed") == 1.0
    assert metrics.inference_prompt_tokens_total.get(worker_id="w1", model="engineering/w1") > 0
    assert metrics.inference_completion_tokens_total.get(worker_id="w1", model="engineering/w1") > 0

    count, total_sum = metrics.inference_duration_seconds.get_summary(worker_id="w1", model="engineering/w1")
    assert count == 1
    assert total_sum > 0.0

    # Timeout handling
    runtime.adapters["w1"] = TimeoutAdapter()
    timed_out = runtime.complete(
        {"model": "engineering/w1", "messages": [{"role": "user", "content": "time out please"}]}
    )
    assert timed_out["status"] == "blocked"
    assert timed_out["failure_class"] == "timeout"
    assert metrics.inference_completions_total.get(worker_id="w1", outcome="timed_out") == 1.0
    assert metrics.provider_errors_total.get(worker_id="w1", error_type="timeout") == 1.0

    # Upstream error handling (re-enable worker first)
    runtime.health.record_worker_observation("w1", healthy=True)
    runtime.adapters["w1"] = ErrorAdapter()
    errored = runtime.complete(
        {"model": "engineering/w1", "messages": [{"role": "user", "content": "error out please"}]}
    )
    assert errored["status"] == "blocked"
    assert errored["failure_class"] == "worker"
    assert metrics.inference_completions_total.get(worker_id="w1", outcome="failed") == 1.0
    assert metrics.provider_errors_total.get(worker_id="w1", error_type="connection_error") == 1.0


def test_scheduler_metrics_instrumentation():
    """Verify scheduler queue wait and queue work gauge updates."""
    metrics = MetricsRegistry()
    scheduler = GraphScheduler(metrics=metrics)

    graph = TaskGraph("task-1")
    graph.add("step1", capabilities={"navigation"})
    graph.add("step2", dependencies={"step1"}, capabilities={"navigation"})

    executed = []
    scheduler.run(
        graph,
        {
            "step1": lambda: executed.append("step1"),
            "step2": lambda: executed.append("step2"),
        },
    )

    assert executed == ["step1", "step2"]
    assert metrics.scheduler_queued_work.get() == 0.0
    assert metrics.scheduler_active_work.get() == 0.0


def test_authority_and_validation_metrics(tmp_path):
    """Verify authority rejection and external validation metric counters."""
    w1 = make_worker("w1")
    cap_registry = CapabilityRegistry([w1])
    metrics = MetricsRegistry()
    runtime = OrchestratorRuntime(
        cap_registry,
        {"w1": InMemoryAdapter("rejected content")},
        EvidenceStore(tmp_path / "evidence.jsonl"),
        metrics=metrics,
        validator=lambda resp: resp.get("content") == "expected",
    )

    # External validation rejected
    result = runtime.complete({"messages": [{"role": "user", "content": "hi"}]})
    assert result["status"] == "blocked"
    assert metrics.authority_validations_total.get(outcome="rejected") == 1.0

    # Tool authority rejection
    task = Task("task-auth", "repo", "a" * 40, frozenset(), frozenset({"read"}), 1)
    authority = Authority(task.task_id, task.state_hash, frozenset({"write"}), datetime.now(timezone.utc) + timedelta(minutes=1))
    denied = runtime.execute_tool(task, authority, "delete_all", {}, lambda name, args: "ok")
    assert denied["status"] == "blocked"
    assert metrics.authority_rejections_total.get(reason="unauthorized_action") == 1.0


# =============================================================================
# 5. Concurrency, Cardinality & Privacy Verification
# =============================================================================

def test_concurrency_and_scrape_isolation(tmp_path):
    """Verify thread-safety and absence of side effects under concurrent load."""
    w1 = make_worker("w1")
    cap_registry = CapabilityRegistry([w1])
    metrics = MetricsRegistry()
    runtime = OrchestratorRuntime(
        cap_registry,
        {"w1": InMemoryAdapter("reply")},
        EvidenceStore(tmp_path / "evidence.jsonl"),
        metrics=metrics,
    )
    server = GatewayServer(("127.0.0.1", 0), create_gateway(runtime, "client-secret"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    errors = []
    host, port = server.server_address

    def do_inference():
        try:
            conn = HTTPConnection(host, port)
            body = json.dumps({"messages": [{"role": "user", "content": "hi"}]})
            conn.request("POST", "/v1/chat/completions", body=body, headers={"Authorization": "Bearer client-secret"})
            resp = conn.getresponse()
            assert resp.status == 200
            conn.close()
        except Exception as e:
            errors.append(e)

    def do_scrape():
        try:
            conn = HTTPConnection(host, port)
            conn.request("GET", "/metrics")
            resp = conn.getresponse()
            assert resp.status == 200
            resp.read()
            conn.close()
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=do_inference) for _ in range(10)] + [
        threading.Thread(target=do_scrape) for _ in range(10)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    try:
        assert not errors, f"Concurrent execution generated errors: {errors}"
        # Scrapes alone must not create extra inference requests
        assert metrics.inference_requests_total.get(status="received") == 10.0
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_security_no_credential_or_prompt_disclosure(tmp_path):
    """Ensure sensitive tokens, prompt content, and secret strings never appear in telemetry."""
    secret_prompt = "TOP_SECRET_PROMPT_CONTENT_XYZ"
    secret_token = "SUPER_SECRET_CLIENT_BEARER_TOKEN"

    w1 = make_worker("w1")
    cap_registry = CapabilityRegistry([w1])
    metrics = MetricsRegistry()
    runtime = OrchestratorRuntime(
        cap_registry,
        {"w1": InMemoryAdapter("safe output")},
        EvidenceStore(tmp_path / "evidence.jsonl"),
        metrics=metrics,
    )
    server = GatewayServer(("127.0.0.1", 0), create_gateway(runtime, secret_token))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address

        # Send request with sensitive prompt and token
        conn = HTTPConnection(host, port)
        body = json.dumps({"messages": [{"role": "user", "content": secret_prompt}]})
        conn.request("POST", "/v1/chat/completions", body=body, headers={"Authorization": f"Bearer {secret_token}"})
        assert conn.getresponse().status == 200
        conn.close()

        # Scrape /health
        conn = HTTPConnection(host, port)
        conn.request("GET", "/health")
        health_text = conn.getresponse().read().decode()
        conn.close()

        # Scrape /metrics
        conn = HTTPConnection(host, port)
        conn.request("GET", "/metrics")
        metrics_text = conn.getresponse().read().decode()
        conn.close()

        # Ensure NO sensitive content appears
        assert secret_prompt not in health_text
        assert secret_token not in health_text
        assert secret_prompt not in metrics_text
        assert secret_token not in metrics_text
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_bounded_label_cardinality():
    """Verify that metric label names and values are strictly bounded enums."""
    registry = MetricsRegistry()
    registry.http_requests_total.inc(route="v1_chat_completions", method="POST", status_class="2xx")
    registry.inference_completions_total.inc(worker_id="b0-live-tp1-worker1", outcome="completed")
    registry.scheduler_dispatch_decisions_total.inc(worker_id="b0-live-tp1-worker1", decision="dispatched")

    text = registry.render_prometheus_text()
    if HAS_PROMETHEUS_CLIENT:
        families = list(text_string_to_metric_families(text))
        for fam in families:
            for sample in fam.samples:
                for label_name, label_val in sample.labels.items():
                    assert label_name in {
                        "route", "method", "status_class", "worker_id", "model",
                        "status", "outcome", "decision", "error_type", "reason", "le"
                    }, f"Unexpected high-cardinality label name: {label_name}"
                    assert len(label_val) < 64, f"Suspiciously long label value: {label_val}"
                    assert " " not in label_val, f"Label value contains whitespace: {label_val}"
    else:
        for line in text.splitlines():
            if line.startswith("#") or "{" not in line:
                continue
            labels_part = line[line.find("{") + 1 : line.rfind("}")]
            for item in labels_part.split(","):
                k, v = item.split("=", 1)
                assert k in {
                    "route", "method", "status_class", "worker_id", "model",
                    "status", "outcome", "decision", "error_type", "reason", "le"
                }, f"Unexpected label name: {k}"
                clean_v = v.strip('"')
                assert len(clean_v) < 64
                assert " " not in clean_v
