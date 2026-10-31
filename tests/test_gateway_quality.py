"""Failure-path qualification with fake providers; never contacts the appliance."""
import asyncio
import importlib.util
import json
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

pytest.importorskip("httpx2")
import httpx

from orchestrator_gateway import AsgiServerWrapper, create_asgi_gateway
from orchestrator_gateway.asgi_limits import BoundedExecutor, ExecutionBusy, IngressError, read_object
from orchestrator_runtime import CapabilityRegistry, EvidenceStore, InMemoryAdapter, OrchestratorRuntime
from orchestrator_runtime.clients import Client, ClientRegistry, token_digest
from orchestrator_runtime.evidence import verify_lines
from orchestrator_runtime.tracing import OTLPTraceExporter, Span
from tests.test_orchestrator_runtime import worker


def make_runtime(tmp_path):
    return OrchestratorRuntime(CapabilityRegistry([worker("w1")]),
                               {"w1": InMemoryAdapter({"content": "ok", "tool_calls": []})},
                               EvidenceStore(tmp_path / "evidence.jsonl"))


def close_runtime(runtime):
    for name in ("http_dispatch", "http_tokenize"):
        getattr(runtime, name).shutdown()


def test_incremental_body_bounds_and_timeout():
    class Request:
        async def stream(self):
            yield b'{"a":"'
            yield b'x' * 100
    class Stalled:
        async def stream(self):
            await asyncio.sleep(5)
            yield b'{}'
    async def run():
        with pytest.raises(IngressError) as error:
            await read_object(Request(), 20, 1)
        assert error.value.status == 413
        with pytest.raises(IngressError) as error:
            await read_object(Stalled(), 20, .02)
        assert error.value.status == 408
    asyncio.run(run())


def test_http_shape_size_and_outcome_contract(tmp_path):
    runtime = make_runtime(tmp_path)
    app = create_asgi_gateway(runtime, "tok", max_body_bytes=256)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                     headers={"Authorization": "Bearer tok"}) as c:
            for body in [[], None, "string", {"messages": [], "stream": "true"}, {"messages": ["bad"]}]:
                response = await c.post('/v1/chat/completions', content=json.dumps(body))
                assert response.status_code == 400
            response = await c.post('/v1/chat/completions', content=b'x' * 257)
            assert response.status_code == 413
            response = await c.post('/v1/outcomes', json={"request_id": "unknown", "outcome": "fail"})
            assert response.status_code == 404
            response = await c.post('/v1/outcomes', json={'request_id': 'unknown', 'outcome': 'fail', 'detail': {}})
            assert response.status_code == 400
            response = await c.get('/v1/outcomes/summary')
            assert response.status_code == 200
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            assert (await c.post('/v1/outcomes', json={})).status_code == 401
    try:
        asyncio.run(run())
    finally:
        close_runtime(runtime)


def test_slow_tokenizer_does_not_block_health(tmp_path):
    runtime = make_runtime(tmp_path)
    entered = threading.Event()
    def slow(*args):
        entered.set()
        time.sleep(.3)
        return {"prompt_tokens": 1}
    runtime.count_tokens = slow
    app = create_asgi_gateway(runtime, "tok")
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                     headers={"Authorization": "Bearer tok"}) as c:
            request = asyncio.create_task(c.post('/v1/tokenize', json={}))
            while not entered.is_set():
                await asyncio.sleep(.005)
            t0 = time.monotonic()
            assert (await c.get('/health')).status_code == 200
            assert time.monotonic() - t0 < .2
            assert (await request).status_code == 200
    try:
        asyncio.run(run())
    finally:
        close_runtime(runtime)


def test_execution_capacity_not_released_when_http_await_is_cancelled():
    executor = BoundedExecutor(1, "qualification")
    release = threading.Event()
    async def run():
        first = executor.submit(release.wait)
        first.cancel()
        with pytest.raises(ExecutionBusy):
            executor.submit(lambda: None)
        release.set()
        for _ in range(100):
            try:
                assert await executor.submit(lambda: "available") == "available"
                return
            except ExecutionBusy:
                await asyncio.sleep(.005)
        pytest.fail("execution slot leaked")
    try:
        asyncio.run(run())
    finally:
        release.set()
        executor.shutdown()


@pytest.mark.parametrize("stream,phase", [(False, "before"), (True, "before"), (True, "stream")])
def test_socket_disconnect_cancels_provider(tmp_path, stream, phase):
    runtime = make_runtime(tmp_path)
    started, stopped = threading.Event(), threading.Event()
    def completion(body, *, cancel, **kwargs):
        started.set()
        if phase == "stream":
            kwargs["on_stream_start"]({"id": "socket-fixture", "model": "fixture"})
            for _ in range(10000):
                if cancel.is_set():
                    break
                kwargs["on_stream_chunk"]({"choices": [{"delta": {"content": "x" * 1024}}]})
        if cancel.wait(2):
            stopped.set()
        return {"status": "cancelled"}
    runtime.complete = completion
    app = create_asgi_gateway(runtime, "tok")
    server = AsgiServerWrapper(app, "127.0.0.1", 0, log_level="error")
    # Bind the listening socket once to avoid a free-port race.
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    thread = threading.Thread(target=lambda: server.server.run(sockets=[listener]), daemon=True)
    thread.start()
    try:
        for _ in range(200):
            if server.server.started:
                break
            time.sleep(.005)
        assert server.server.started
        connection = socket.create_connection(listener.getsockname(), timeout=2)
        body = json.dumps({"messages": [{"role": "user", "content": "hi"}], "stream": stream}).encode()
        connection.sendall(b'POST /v1/chat/completions HTTP/1.1\r\nHost: localhost\r\n'
                           b'Authorization: Bearer tok\r\nContent-Type: application/json\r\nContent-Length: '
                           + str(len(body)).encode() + b'\r\n\r\n' + body)
        assert started.wait(1)
        if phase == "stream":
            assert b"200 OK" in connection.recv(4096)
        connection.close()
        assert stopped.wait(1), "provider did not observe client disconnect"
    finally:
        server.shutdown()
        thread.join(timeout=3)
        listener.close()
        close_runtime(runtime)
    assert not thread.is_alive()


def test_streams_do_not_need_default_executor_consumers(tmp_path):
    runtime = make_runtime(tmp_path)
    def completion(body, on_stream_start, on_stream_chunk, **kwargs):
        on_stream_start({"id": "fixture", "model": "fixture"})
        for _ in range(8):
            on_stream_chunk({"choices": [{"index": 0, "delta": {"content": "x"}}]})
        return {"status": "ok", "response": {"choices": [{"finish_reason": "stop"}]}}
    runtime.complete = completion
    app = create_asgi_gateway(runtime, "tok", max_stream_queue_size=1)
    async def run():
        asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=1))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                     headers={"Authorization": "Bearer tok"}) as c:
            results = await asyncio.wait_for(asyncio.gather(*[
                c.post('/v1/chat/completions', json={"messages": [{}], "stream": True}) for _ in range(4)
            ]), timeout=3)
            assert all(r.status_code == 200 and '[DONE]' in r.text for r in results)
    try:
        asyncio.run(run())
    finally:
        close_runtime(runtime)


def test_telemetry_memory_is_bounded_and_evidence_stays_complete(tmp_path, monkeypatch):
    monkeypatch.setenv('ORCHESTRATOR_EVIDENCE_RING_SIZE', '8')
    monkeypatch.setenv('ORCHESTRATOR_TRACE_RING_SIZE', '8')
    path = tmp_path / 'chain.jsonl'
    evidence = EvidenceStore(path)
    tracer = OTLPTraceExporter(endpoint=None)
    for i in range(200):
        evidence.append('fixture', index=i)
        tracer.record_span(Span('fixture', 'a' * 32, 'b' * 16))
    assert len(evidence.records()) == 8
    assert len(tracer.exported_spans) == 8
    with path.open() as lines:
        intact, count, head, _ = verify_lines(lines)
    assert intact and count == 200
    assert EvidenceStore(path).head == head
    tracer.shutdown()


def test_corrupt_evidence_diagnostics_are_bounded():
    intact, count, head, problems = verify_lines('not-json\n' for _ in range(10000))
    assert not intact and len(problems) == 50


def test_cache_hits_obey_client_request_quota(tmp_path):
    runtime = make_runtime(tmp_path)
    client = Client('fixture', token_digest('tok'), frozenset({'workload'}), requests_per_minute=1)
    runtime.clients = ClientRegistry([client])
    request = {"model": "engineering/w1", "messages": [{"role": "user", "content": "hi"}], "temperature": 0}
    first = runtime.complete(request.copy(), client=client)
    assert first['status'] == 'ok', first
    second = runtime.complete(request.copy(), client=client)
    assert second['status'] == 'limited', second


def test_artifact_verification_detects_changes(tmp_path):
    script = Path(__file__).resolve().parents[1] / 'roles/orchestrator_gateway/files/gateway-artifact.py'
    spec = importlib.util.spec_from_file_location('gateway_artifact', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in module.MODULES:
        directory = tmp_path / name
        directory.mkdir()
        (directory / '__init__.py').write_text('pass\n')
    lock = tmp_path / 'lock'
    lock.write_text('fixture')
    before = module.manifest(tmp_path, lock)
    (tmp_path / module.MODULES[0] / '__init__.py').write_text('different\n')
    assert module.manifest(tmp_path, lock) != before


def test_evidence_segments_preserve_chain_and_detect_tampering(tmp_path, monkeypatch):
    from orchestrator_runtime.evidence import verify_file
    monkeypatch.setenv('ORCHESTRATOR_EVIDENCE_SEGMENT_BYTES', '1024')
    path = tmp_path / 'evidence.jsonl'
    evidence = EvidenceStore(path)
    for i in range(20):
        evidence.append('fixture', index=i, payload='x' * 200)
    intact, count, head, problems = verify_file(path)
    assert intact and count >= 20 and not problems
    assert EvidenceStore(path).head == head
    segments = list(tmp_path.glob('*.sealed-*'))
    assert segments
    with segments[0].open('a') as stream:
        stream.write('tampering')
    assert not verify_file(path)[0]


def test_interrupted_rotation_preserves_original_chain(tmp_path, monkeypatch):
    import orchestrator_runtime.evidence as module
    monkeypatch.setenv('ORCHESTRATOR_EVIDENCE_SEGMENT_BYTES', '1024')
    path = tmp_path / 'evidence.jsonl'
    evidence = EvidenceStore(path)
    evidence.append('fixture', payload='x' * 1100)
    original = path.read_bytes()
    replace = module.os.replace
    def interrupted(*args):
        raise OSError('injected interruption before activation')
    monkeypatch.setattr(module.os, 'replace', interrupted)
    with pytest.raises(OSError):
        evidence.append('next')
    assert path.read_bytes() == original
    assert module.verify_file(path)[0]
    monkeypatch.setattr(module.os, 'replace', replace)
    evidence.append('recovered')
    assert module.verify_file(path)[0]


def test_per_client_dispatch_limit_preserves_other_client_capacity():
    executor = BoundedExecutor(2, 'fairness', per_client_capacity=1)
    stop = threading.Event()
    async def run():
        first = executor.submit_for('one', stop.wait)
        with pytest.raises(ExecutionBusy):
            executor.submit_for('one', lambda: None)
        assert await executor.submit_for('two', lambda: 'ok') == 'ok'
        stop.set()
        await first
    try:
        asyncio.run(run())
    finally:
        stop.set()
        executor.shutdown()
