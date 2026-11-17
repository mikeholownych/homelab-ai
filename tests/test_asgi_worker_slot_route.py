"""POST /admin/workers/<id>/slot/<save|restore>: admin scope, remote origin only, 404 unknown worker, 422 for an engine without slot persistence."""
import asyncio
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytest.importorskip("starlette")   # the repository-quality job installs only the base requirements; the gateway job has starlette

from orchestrator_gateway import create_asgi_gateway  # noqa: E402
from orchestrator_runtime import CapabilityRegistry, Client, ClientRegistry, EvidenceStore, InMemoryAdapter, OrchestratorRuntime, WorkerRecord
from orchestrator_runtime.clients import token_digest


async def request(app, path, method="POST", token=None, peer="10.0.8.95"):
    messages = []
    headers = [(b"host", b"test")]
    if token:
        headers.append((b"authorization", ("Bearer " + token).encode()))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http", "path": path,
             "raw_path": path.encode(), "query_string": b"", "headers": headers, "client": (peer, 23456), "server": ("10.0.8.5", 8443), "root_path": ""}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    status = next(m["status"] for m in messages if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    try:
        return status, (json.loads(body) if body else {})
    except ValueError:
        return status, {"text": body.decode()}


def test_slot_route_scopes_origin_and_unsupported_engines():
    clients = ClientRegistry([
        Client(client_id="adm", token_sha256=token_digest("admin-token"), scopes=frozenset({"admin"})),
        Client(client_id="wl", token_sha256=token_digest("workload-token"), scopes=frozenset({"workload"})),
    ])
    worker = WorkerRecord(worker_id="fixture", public_model_id="engineering/fixture", model_id="fixture", revision="a" * 40,
                          artifact_digest="sha256:" + "b" * 64, runtime_image_digest="sha256:" + "c" * 64, topology="tp1", gpu_assignment=("0",),
                          capabilities=frozenset({"navigation"}), context_limit=16384, max_concurrency=1, resource_envelope={"memory_reserve_gib": 32},
                          evidence_ids=("fixture",), registry_version=1, measured_at="2026-10-21T00:00:00Z",
                          valid_until=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat())

    async def run():
        with tempfile.TemporaryDirectory() as directory:
            runtime = OrchestratorRuntime(CapabilityRegistry([worker]), {"fixture": InMemoryAdapter("fixture")}, EvidenceStore(Path(directory) / "e.jsonl"))
            runtime.clients = clients
            app = create_asgi_gateway(runtime, clients=clients, listener="remote", local_addresses=lambda: {"127.0.0.1", "10.0.8.5"})
            cases = [("no token", "/admin/workers/fixture/slot/save", None, "10.0.8.95", 401),
                     ("workload token", "/admin/workers/fixture/slot/save", "workload-token", "10.0.8.95", 403),
                     ("local origin", "/admin/workers/fixture/slot/save", "admin-token", "127.0.0.1", 403),
                     ("unknown worker", "/admin/workers/nope/slot/save", "admin-token", "10.0.8.95", 404),
                     ("engine without slot persistence", "/admin/workers/fixture/slot/save", "admin-token", "10.0.8.95", 422),
                     ("bad action", "/admin/workers/fixture/slot/delete", "admin-token", "10.0.8.95", 422)]
            for label, path, token, peer, expected in cases:
                status, _ = await request(app, path, "POST", token, peer)
                assert status == expected, (label, status)
            status, _ = await request(app, "/admin/workers/fixture/slot/save", "GET", "admin-token")
            assert status == 405

    asyncio.run(run())
