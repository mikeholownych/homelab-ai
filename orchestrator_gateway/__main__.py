from __future__ import annotations

import os

from orchestrator_gateway import GatewayServer, create_gateway
from orchestrator_runtime import CapabilityRegistry, EvidenceStore, OpenAIProviderAdapter, OrchestratorRuntime, WorkerRecord


def main() -> None:
    client_token = os.environ["ORCHESTRATOR_CLIENT_TOKEN"]
    worker_endpoint = os.environ["ORCHESTRATOR_WORKER_ENDPOINT"]
    worker_token = os.environ["ORCHESTRATOR_WORKER_TOKEN"]
    worker_id = os.environ.get("ORCHESTRATOR_WORKER_ID", "live-worker-1")
    public_model_id = os.environ.get("ORCHESTRATOR_PUBLIC_MODEL_ID", "engineering/default")
    worker = WorkerRecord(
        worker_id=worker_id,
        public_model_id=public_model_id,
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
    registry = CapabilityRegistry([worker])
    runtime = OrchestratorRuntime(
        registry,
        {worker_id: OpenAIProviderAdapter(worker_endpoint, worker_token)},
        EvidenceStore(os.environ.get("ORCHESTRATOR_EVIDENCE_PATH", "orchestrator-evidence.jsonl")),
    )
    host = os.environ.get("ORCHESTRATOR_HOST", "127.0.0.1")
    port = int(os.environ.get("ORCHESTRATOR_PORT", "8010"))
    server = GatewayServer((host, port), create_gateway(runtime, client_token))
    server.serve_forever()


if __name__ == "__main__":
    main()
