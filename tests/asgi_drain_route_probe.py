import asyncio
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from orchestrator_gateway import create_asgi_gateway
from orchestrator_runtime import CapabilityRegistry, Client, ClientRegistry, EvidenceStore, InMemoryAdapter, OrchestratorRuntime, WorkerRecord
from orchestrator_runtime.clients import token_digest


async def request(app, path, method="GET", token=None, peer="10.0.8.95"):
    messages = []
    headers = [(b"host", b"test")]
    if token:
        headers.append((b"authorization", ("Bearer " + token).encode()))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
             "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
             "headers": headers, "client": (peer, 23456), "server": ("10.0.8.5", 8443), "root_path": ""}
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    async def send(message):
        messages.append(message)
    await app(scope, receive, send)
    status = next(m["status"] for m in messages if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    try:
        decoded = json.loads(body) if body else {}
    except ValueError:
        decoded = {"text": body.decode()}
    return status, decoded


async def main():
    clients = ClientRegistry([
        Client(client_id="fixture-admin", token_sha256=token_digest("fixture-admin-token"), scopes=frozenset({"admin"})),
        Client(client_id="fixture-worker", token_sha256=token_digest("fixture-workload-token"), scopes=frozenset({"workload"})),
    ])
    worker = WorkerRecord(worker_id="fixture", public_model_id="engineering/fixture", model_id="fixture",
                          revision="a" * 40, artifact_digest="sha256:" + "b" * 64,
                          runtime_image_digest="sha256:" + "c" * 64, topology="tp1", gpu_assignment=("0",),
                          capabilities=frozenset({"navigation"}), context_limit=16384, max_concurrency=1,
                          resource_envelope={"memory_reserve_gib": 32}, evidence_ids=("fixture",), registry_version=1,
                          measured_at="2026-10-21T00:00:00Z",
                          valid_until=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat())
    with tempfile.TemporaryDirectory(prefix="asgi-drain-probe-") as directory:
        runtime = OrchestratorRuntime(CapabilityRegistry([worker]), {"fixture": InMemoryAdapter("fixture")},
                                      EvidenceStore(Path(directory) / "evidence.jsonl"))
        runtime.clients = clients
        app = create_asgi_gateway(runtime, clients=clients, listener="remote", local_addresses=lambda: {"127.0.0.1", "10.0.8.5"})
        if sys.argv[1] == "baseline":
            for path, method in [("/admin/workers", "GET"), ("/admin/workers/fixture/drain", "POST")]:
                status, _ = await request(app, path, method, "fixture-admin-token")
                assert status == 404, (path, status)
            print(json.dumps({"mode": "baseline", "verified_missing_endpoints": 2}))
            return
        cases = [
            ("unauthenticated view", "/admin/workers", "GET", None, "10.0.8.95", 401),
            ("workload view", "/admin/workers", "GET", "fixture-workload-token", "10.0.8.95", 403),
            ("admin view", "/admin/workers", "GET", "fixture-admin-token", "10.0.8.95", 200),
            ("local origin refused", "/admin/workers", "GET", "fixture-admin-token", "127.0.0.1", 403),
            ("unauthenticated drain", "/admin/workers/fixture/drain", "POST", None, "10.0.8.95", 401),
            ("workload drain", "/admin/workers/fixture/drain", "POST", "fixture-workload-token", "10.0.8.95", 403),
            ("local drain refused", "/admin/workers/fixture/drain", "POST", "fixture-admin-token", "127.0.0.1", 403),
            ("unknown worker", "/admin/workers/unknown/drain", "POST", "fixture-admin-token", "10.0.8.95", 404),
            ("unsupported action", "/admin/workers/fixture/restart", "POST", "fixture-admin-token", "10.0.8.95", 404),
            ("wrong method", "/admin/workers/fixture/drain", "GET", "fixture-admin-token", "10.0.8.95", 405),
        ]
        for label, path, method, token, peer, expected in cases:
            status, _ = await request(app, path, method, token, peer)
            assert status == expected, (label, status, expected)
        status, body = await request(app, "/admin/workers/fixture/drain", "POST", "fixture-admin-token")
        assert status == 200 and body["status"] == "drained"
        assert "fixture" in runtime.admission.drained()
        status, body = await request(app, "/admin/workers", token="fixture-admin-token")
        assert status == 200 and body["workers"]["fixture"]["drain"]["state"] == "drained"
        status, body = await request(app, "/admin/workers/fixture/undrain", "POST", "fixture-admin-token")
        assert status == 200 and body["status"] == "active"
        assert "fixture" not in runtime.admission.drained()
        print(json.dumps({"mode": "candidate", "checks_passed": len(cases) + 3,
                          "production_requests": 0, "actual_runtime_drain_and_undrain": True}))


asyncio.run(main())
