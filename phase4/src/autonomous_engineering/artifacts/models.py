"""Immutable Artifact and Provenance Models."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from autonomous_engineering.core.types import ArtifactType


@dataclass(frozen=True)
class ArtifactRecord:
    artifact_hash: str
    artifact_type: ArtifactType
    work_order_id: str
    work_order_version: int
    step_id: str
    producing_worker_id: str
    producing_profile_hash: str
    capability_token_id: str
    parent_artifact_hashes: tuple[str, ...]
    created_at: str
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_hash": self.artifact_hash,
            "artifact_type": str(self.artifact_type),
            "work_order_id": self.work_order_id,
            "work_order_version": self.work_order_version,
            "step_id": self.step_id,
            "producing_worker_id": self.producing_worker_id,
            "producing_profile_hash": self.producing_profile_hash,
            "capability_token_id": self.capability_token_id,
            "parent_artifact_hashes": list(self.parent_artifact_hashes),
            "created_at": self.created_at,
            "metadata": self.metadata,
        }
