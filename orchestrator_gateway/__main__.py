from __future__ import annotations

import hashlib
import json
import os
import signal
import ssl
import sys
import threading
from pathlib import Path

from orchestrator_gateway import GatewayServer, create_gateway
from orchestrator_runtime import (
    CapabilityRegistry,
    ClientRegistry,
    EvidenceStore,
    HealthManager,
    MetricsRegistry,
    OpenAIProviderAdapter,
    OrchestratorRuntime,
    Router,
    WorkerRecord,
)


def read_secret(name: str, file_name: str | None = None) -> str:
    path = os.environ.get(file_name) if file_name else None
    if path and Path(path).exists():
        return Path(path).read_text(encoding="utf-8").strip()
    return os.environ.get(name, "")


def _credential_path(token_file: str) -> Path:
    path = Path(token_file)
    if path.is_absolute():
        return path
    root = os.environ.get("CREDENTIALS_DIRECTORY")
    if not root:
        raise RuntimeError("relative worker credential requires CREDENTIALS_DIRECTORY")
    return Path(root) / path


def worker_records() -> list[WorkerRecord]:
    specs = os.environ.get("ORCHESTRATOR_WORKER_SPECS")
    if specs:
        records = []
        for spec in json.loads(specs):
            records.append(
                WorkerRecord(
                    worker_id=spec["worker_id"],
                    public_model_id=spec["public_model_id"],
                    model_id=spec["model_id"],
                    revision=spec["revision"],
                    artifact_digest=spec["artifact_digest"],
                    runtime_image_digest=spec["runtime_image_digest"],
                    topology=spec["topology"],
                    gpu_assignment=tuple(spec["gpu_assignment"]),
                    capabilities=frozenset(spec["capabilities"]),
                    context_limit=int(spec["context_limit"]),
                    max_output_tokens=int(spec.get("max_output_tokens", 0)),
                    max_concurrency=int(spec["max_concurrency"]),
                    resource_envelope=spec.get("resource_envelope", {}),
                    evidence_ids=tuple(spec["evidence_ids"]),
                    registry_version=int(spec.get("registry_version", 1)),
                    measured_at=spec["measured_at"],
                    valid_until=spec["valid_until"],
                    status=spec.get("status", "measured"),
                    endpoint=spec["endpoint"],
                    auth_token=_credential_path(spec["token_file"]).read_text(encoding="utf-8").strip(),
                    pool=spec.get("pool", "lead"),
                    engine=spec.get("engine", "unknown"),
                    reasoning_budget=spec.get("reasoning_budget"),
                    role=spec.get("role", "production"),
                )
            )
        return records

    worker_endpoint = os.environ["ORCHESTRATOR_WORKER_ENDPOINT"]
    worker_token = read_secret("ORCHESTRATOR_WORKER_TOKEN", "ORCHESTRATOR_WORKER_TOKEN_FILE")
    worker_id = os.environ.get("ORCHESTRATOR_WORKER_ID", "live-worker-1")
    return [
        WorkerRecord(
            worker_id=worker_id,
            public_model_id=os.environ.get("ORCHESTRATOR_PUBLIC_MODEL_ID", "engineering/default"),
            model_id=os.environ["ORCHESTRATOR_MODEL_ID"],
            revision=os.environ["ORCHESTRATOR_MODEL_REVISION"],
            artifact_digest=os.environ["ORCHESTRATOR_ARTIFACT_DIGEST"],
            runtime_image_digest=os.environ["ORCHESTRATOR_RUNTIME_IMAGE_DIGEST"],
            topology=os.environ.get("ORCHESTRATOR_TOPOLOGY", "unknown"),
            gpu_assignment=tuple(filter(None, os.environ.get("ORCHESTRATOR_GPU_ASSIGNMENT", "").split(","))),
            capabilities=frozenset(filter(None, os.environ.get("ORCHESTRATOR_CAPABILITIES", "navigation").split(","))),
            context_limit=int(os.environ.get("ORCHESTRATOR_CONTEXT_LIMIT", "16384")),
            max_output_tokens=0,
            max_concurrency=int(os.environ.get("ORCHESTRATOR_MAX_CONCURRENCY", "1")),
            resource_envelope={"source": "environment"},
            evidence_ids=(os.environ["ORCHESTRATOR_EVIDENCE_ID"],),
            registry_version=int(os.environ.get("ORCHESTRATOR_REGISTRY_VERSION", "1")),
            measured_at=os.environ["ORCHESTRATOR_MEASURED_AT"],
            valid_until=os.environ["ORCHESTRATOR_VALID_UNTIL"],
            endpoint=worker_endpoint,
            auth_token=worker_token,
        )
    ]


def load_router(workers: list[WorkerRecord]) -> Router | None:
    """Build the route table from ORCHESTRATOR_ROUTES / ORCHESTRATOR_MODEL_ALIASES.

    An invalid table, one that references a pool with no registered worker, or one whose ordinary rules could route
    production traffic to a candidate pool, aborts start-up (fail closed) instead of silently routing somewhere
    unintended. Candidate pools are reachable only through qualification aliases, canary and shadow (R4).
    """
    raw_routes = os.environ.get("ORCHESTRATOR_ROUTES")
    if not raw_routes:
        return None
    router = Router.from_config(json.loads(raw_routes), json.loads(os.environ.get("ORCHESTRATOR_MODEL_ALIASES", "{}")))
    known = {worker.pool for worker in workers}
    missing = router.referenced_pools() - known
    if missing:
        raise RuntimeError(f"route table references pools with no worker: {sorted(missing)}")
    candidate_pools = {w.pool for w in workers if w.role == "candidate"}
    for rule in router.rules:
        leaked = ({rule.pool, *rule.fallback} & candidate_pools)
        if leaked:
            raise RuntimeError(f"rule '{rule.rule_id}' routes ordinary traffic to candidate pool(s) {sorted(leaked)}")
    for name, alias in router.alias_specs.items():
        if alias.pool in candidate_pools and alias.scope != "qualification":
            raise RuntimeError(f"alias '{name}' exposes candidate pool '{alias.pool}' without the qualification scope")
    return router


def seal_predecessors(paths: str) -> list[dict[str, object]]:
    """R11: earlier chains that cannot be continued are sealed, not rewritten. Their sha256 is taken here, when the new
    chain starts and nothing writes to them any more, and recorded in the new chain's genesis record."""
    sealed = []
    for path in paths.split():
        try:
            digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
            lines = sum(1 for _ in Path(path).open(encoding="utf-8", errors="replace"))
            sealed.append({"path": path, "sha256": digest, "records": lines})
        except OSError as error:
            sealed.append({"path": path, "unreadable": type(error).__name__})
    return sealed


def load_clients() -> ClientRegistry:
    """Per-client registry (R6) when configured; otherwise the legacy bearer tokens become workload clients."""
    state = os.environ.get("ORCHESTRATOR_STATE_DIR")
    state_path = Path(state) / "client-usage.json" if state else None
    registry_file = os.environ.get("ORCHESTRATOR_CLIENTS_FILE")
    if registry_file:
        return ClientRegistry.from_file(registry_file, state_path=state_path)
    tokens = [("default", read_secret("ORCHESTRATOR_CLIENT_TOKEN", "ORCHESTRATOR_CLIENT_TOKEN_FILE"))]
    extra = os.environ.get("ORCHESTRATOR_CLIENT_TOKEN_EXTRA_FILE")
    if extra and Path(extra).exists():
        tokens.append(("opencode", Path(extra).read_text(encoding="utf-8").strip()))
    return ClientRegistry.from_tokens([(cid, t) for cid, t in tokens if t])


def main() -> None:
    workers = worker_records()
    registry = CapabilityRegistry(workers)
    metrics = MetricsRegistry()
    adapters = {
        worker.worker_id: OpenAIProviderAdapter(worker.endpoint or "", worker.auth_token or "", worker.model_id)
        for worker in workers
    }
    scheduling_mode = os.environ.get("ORCHESTRATOR_SCHEDULING_MODE", "CONFIGURATION_B_PLUS")
    health = HealthManager(registry, adapters, metrics, probe_interval_seconds=10.0, auto_start=False,
                           scheduling_mode=scheduling_mode)
    router = load_router(workers)
    evidence = EvidenceStore(os.environ.get("ORCHESTRATOR_EVIDENCE_PATH", "orchestrator-evidence.jsonl"))
    if evidence.head is None:
        evidence.genesis(release=os.environ.get("ORCHESTRATOR_RELEASE_ID", "unknown"),
                         sealed_predecessors=seal_predecessors(os.environ.get("ORCHESTRATOR_EVIDENCE_PREDECESSORS", "")))
    state_dir = os.environ.get("ORCHESTRATOR_STATE_DIR")
    capability_evidence = json.loads(os.environ.get("ORCHESTRATOR_CAPABILITY_EVIDENCE", "{}") or "{}")
    runtime = OrchestratorRuntime(
        registry,
        adapters,
        evidence,
        diagnostic_lineage=os.environ.get("ORCHESTRATOR_DIAGNOSTIC_LINEAGE") == "true",
        metrics=metrics,
        health=health,
        scheduling_mode=scheduling_mode,
        router=router,
        capability_evidence=capability_evidence,
        state_path=Path(state_dir) / "gateway-state.json" if state_dir else None,
    )
    runtime.clients = load_clients()
    health.start()

    monitoring_token = read_secret("ORCHESTRATOR_MONITORING_TOKEN", "ORCHESTRATOR_MONITORING_TOKEN_FILE") or None
    allow_worker_pinning = os.environ.get("ORCHESTRATOR_ALLOW_WORKER_PINNING") == "true"
    servers: list[GatewayServer] = []

    # Loopback listener: monitoring only (vllm-top, node textfile, readiness). Workload here is refused.
    local_host = os.environ.get("ORCHESTRATOR_HOST", "127.0.0.1")
    local_port = int(os.environ.get("ORCHESTRATOR_PORT", "8010"))
    local_mode = os.environ.get("ORCHESTRATOR_LOCAL_LISTENER_MODE", "local")
    servers.append(GatewayServer((local_host, local_port), create_gateway(
        runtime, clients=runtime.clients, monitoring_token=monitoring_token,
        require_monitoring_auth=os.environ.get("ORCHESTRATOR_REQUIRE_MONITORING_AUTH") == "true",
        allow_worker_pinning=allow_worker_pinning, listener=local_mode)))

    # Remote listener: the only workload entry point (TLS; requests from the host's own addresses are refused).
    remote_host = os.environ.get("ORCHESTRATOR_REMOTE_HOST")
    if remote_host:
        remote = GatewayServer((remote_host, int(os.environ.get("ORCHESTRATOR_REMOTE_PORT", "8443"))), create_gateway(
            runtime, clients=runtime.clients, monitoring_token=monitoring_token, require_monitoring_auth=True,
            allow_worker_pinning=allow_worker_pinning, listener="remote"))
        cert, key = os.environ.get("ORCHESTRATOR_TLS_CERT"), os.environ.get("ORCHESTRATOR_TLS_KEY")
        if not cert or not key:
            raise RuntimeError("the remote listener requires ORCHESTRATOR_TLS_CERT and ORCHESTRATOR_TLS_KEY")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(cert, key)
        remote.socket = context.wrap_socket(remote.socket, server_side=True)
        servers.append(remote)

    grace = float(os.environ.get("ORCHESTRATOR_SHUTDOWN_GRACE_SECONDS", "600"))
    stopped = threading.Event()

    def graceful_stop(signum, frame) -> None:  # R12
        if stopped.is_set():
            return
        stopped.set()

        def run() -> None:
            runtime.begin_shutdown()
            for server in servers:
                server.shutdown()  # stop accepting; in-flight handler threads continue
            drained = runtime.wait_idle(grace)
            runtime.save_state()
            if runtime.clients is not None:
                runtime.clients.save_state()
            evidence.append("gateway_stopped", graceful=drained, inflight_at_exit=runtime.inflight_count())
            health.stop()

        threading.Thread(target=run, name="graceful-stop").start()

    signal.signal(signal.SIGTERM, graceful_stop)
    signal.signal(signal.SIGINT, graceful_stop)
    threads = [threading.Thread(target=s.serve_forever, name=f"listener-{i}") for i, s in enumerate(servers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    for thread in threading.enumerate():
        if thread.name == "graceful-stop":
            thread.join()
    sys.exit(0)


if __name__ == "__main__":
    main()
