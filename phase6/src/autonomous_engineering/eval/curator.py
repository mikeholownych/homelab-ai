"""Execution Trace Curator for Contamination-Free Fine-Tuning."""
from __future__ import annotations

from typing import Any

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.core.types import ArtifactType, WorkOrderState
from autonomous_engineering.workflow.engine import WorkflowEngine


class TraceCurator:
    """Curates independently verified execution traces for future model improvements.

    Invariants:
    - Only ACCEPTED engineering work is admitted.
    - Held-out benchmark repositories are strictly excluded to prevent evaluation contamination.
    """

    def __init__(
        self,
        engine: WorkflowEngine,
        artifact_store: ArtifactStore,
        held_out_repositories: set[str] | None = None,
    ) -> None:
        self.engine = engine
        self.artifact_store = artifact_store
        self.held_out_repositories = held_out_repositories or {"benchmark-eval-v1", "held-out-test"}

    def curate_trace(
        self,
        work_order_id: str,
        version: int,
    ) -> dict[str, Any] | None:
        wo_record = self.engine.get_work_order(work_order_id, version)
        if not wo_record:
            return None

        # Invariant 1: Only accepted work
        if wo_record["terminal_disposition"] != "ACCEPTED":
            return None

        data = eval(wo_record["data_json"]) if isinstance(wo_record["data_json"], str) and not wo_record["data_json"].startswith("{") else None
        if not data:
            import json
            data = json.loads(wo_record["data_json"])

        repo_id = data["intent"]["target_repo"]["repository_id"]

        # Invariant 2: Anti-contamination check
        if repo_id in self.held_out_repositories:
            return None

        # Extract artifacts
        assignments = self.engine.list_assignments(work_order_id, version)
        artifact_chain = []
        for asgn in assignments:
            art_hash = asgn.get("output_artifact_hash")
            if art_hash:
                rec = self.artifact_store.get_record(art_hash)
                if rec and rec.artifact_type != ArtifactType.VALIDATION_VERDICT:
                    content = self.artifact_store.get(art_hash).decode("utf-8", errors="replace")
                    artifact_chain.append(
                        {
                            "step_id": rec.step_id,
                            "artifact_type": str(rec.artifact_type),
                            "content": content,
                        }
                    )

        return {
            "work_order_id": work_order_id,
            "version": version,
            "instruction": data["source_instruction"]["raw_text"],
            "repository_id": repo_id,
            "artifact_chain": artifact_chain,
            "curated_at_version": version,
        }
