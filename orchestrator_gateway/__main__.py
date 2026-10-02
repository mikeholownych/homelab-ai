from __future__ import annotations

import json
import os
from pathlib import Path

from orchestrator_gateway import GatewayServer, create_gateway
from orchestrator_runtime import (
    CapabilityRegistry,
    Router,
    EvidenceStore,
    HealthManager,
    MetricsRegistry,
    OpenAIProviderAdapter,
    OrchestratorRuntime,
    WorkerRecord,
)


def read_secret(name: str, file_name: str | None = None) -> str:
    path = os.environ.get(file_name) if file_name else None
    if path and Path(path).exists():
        return Path(path).read_text(encoding="utf-8").strip()
    return os.environ.get(name, "")


def worker_records() -> list[WorkerRecord]:
    specs = os.environ.get("ORCHESTRATOR_WORKER_SPECS")
    if specs:
        credential_root = os.environ.get("CREDENTIALS_DIRECTORY")
        records = []
        for spec in json.loads(specs):
            token_path = Path(spec["token_file"])
            if not token_path.is_absolute():
                if not credential_root:
                    raise RuntimeError("relative worker credential requires CREDENTIALS_DIRECTORY")
                token_path = Path(credential_root) / token_path
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
                    max_output_tokens=int(spec["max_output_tokens"]),
                    max_concurrency=int(spec["max_concurrency"]),
                    resource_envelope=spec.get("resource_envelope", {}),
                    evidence_ids=tuple(spec["evidence_ids"]),
                    registry_version=int(spec.get("registry_version", 1)),
                    measured_at=spec["measured_at"],
                    valid_until=spec["valid_until"],
                    endpoint=spec["endpoint"],
                    auth_token=token_path.read_text(encoding="utf-8").strip(),
                    pool=spec.get("pool", "lead"),
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
            max_output_tokens=int(os.environ.get("ORCHESTRATOR_MAX_OUTPUT_TOKENS", "512")),
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

    An invalid table, or one that references a pool with no registered worker, aborts start-up
    (fail closed) instead of silently routing somewhere unintended.
    """
    raw_routes = os.environ.get("ORCHESTRATOR_ROUTES")
    if not raw_routes:
        return None
    router = Router.from_config(json.loads(raw_routes), json.loads(os.environ.get("ORCHESTRATOR_MODEL_ALIASES", "{}")))
    known = {worker.pool for worker in workers}
    missing = router.referenced_pools() - known
    if missing:
        raise RuntimeError(f"route table references pools with no worker: {sorted(missing)}")
    return router


def main() -> None:
    workers = worker_records()
    registry = CapabilityRegistry(workers)
    metrics = MetricsRegistry()
    adapters = {
        worker.worker_id: OpenAIProviderAdapter(worker.endpoint or "", worker.auth_token or "", worker.model_id)
        for worker in workers
    }
    scheduling_mode = os.environ.get("ORCHESTRATOR_SCHEDULING_MODE", "CONFIGURATION_B_PLUS")
    health = HealthManager(
        registry,
        adapters,
        metrics,
        probe_interval_seconds=10.0,
        auto_start=True,
        scheduling_mode=scheduling_mode,
    )
    router = load_router(workers)
    runtime = OrchestratorRuntime(
        registry,
        adapters,
        EvidenceStore(os.environ.get("ORCHESTRATOR_EVIDENCE_PATH", "orchestrator-evidence.jsonl")),
        diagnostic_lineage=os.environ.get("ORCHESTRATOR_DIAGNOSTIC_LINEAGE") == "true",
        metrics=metrics,
        health=health,
        scheduling_mode=scheduling_mode,
        router=router,
    )
    client_tokens = [read_secret("ORCHESTRATOR_CLIENT_TOKEN", "ORCHESTRATOR_CLIENT_TOKEN_FILE")]
    extra_client_token_file = os.environ.get("ORCHESTRATOR_CLIENT_TOKEN_EXTRA_FILE")
    if extra_client_token_file and Path(extra_client_token_file).exists():
        client_tokens.append(Path(extra_client_token_file).read_text(encoding="utf-8").strip())
    client_tokens = [t for t in client_tokens if t]

    monitoring_token = read_secret("ORCHESTRATOR_MONITORING_TOKEN", "ORCHESTRATOR_MONITORING_TOKEN_FILE") or None
    require_monitoring_auth = os.environ.get("ORCHESTRATOR_REQUIRE_MONITORING_AUTH") == "true"
    allow_worker_pinning = os.environ.get("ORCHESTRATOR_ALLOW_WORKER_PINNING") == "true"

    host = os.environ.get("ORCHESTRATOR_HOST", "127.0.0.1")
    port = int(os.environ.get("ORCHESTRATOR_PORT", "8010"))
    handler = create_gateway(
        runtime,
        client_tokens,
        monitoring_token=monitoring_token,
        require_monitoring_auth=require_monitoring_auth,
        allow_worker_pinning=allow_worker_pinning,
    )
    server = GatewayServer((host, port), handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
