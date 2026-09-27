"""Content-Addressed Immutable Artifact Store."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from autonomous_engineering.artifacts.models import ArtifactRecord
from autonomous_engineering.core.crypto import canonical_json, sha256_digest
from autonomous_engineering.core.types import ArtifactType


class ArtifactIntegrityError(RuntimeError):
    pass


class ArtifactStore:
    """Content-addressed, immutable filesystem store for engineering artifacts.

    Invariants:
    - Content addressing: File paths are strictly keyed by SHA-256 digest of payload.
    - Immutability: Once written, an artifact cannot be modified.
    - Tamper evidence: Reading verifies digest match against stored payload.
    """

    def __init__(self, root_dir: Path | str) -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, digest: str) -> Path:
        prefix = digest[:2]
        return self.root_dir / prefix / digest

    def _meta_path_for(self, digest: str) -> Path:
        prefix = digest[:2]
        return self.root_dir / prefix / f"{digest}.meta.json"

    def put(
        self,
        content: bytes | str,
        artifact_type: ArtifactType,
        work_order_id: str,
        work_order_version: int,
        step_id: str,
        producing_worker_id: str,
        producing_profile_hash: str,
        capability_token_id: str,
        parent_artifact_hashes: tuple[str, ...] = (),
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRecord:
        raw_bytes = content.encode("utf-8") if isinstance(content, str) else content
        digest = sha256_digest(raw_bytes)
        target_path = self._path_for(digest)
        meta_path = self._meta_path_for(digest)

        now_iso = datetime.now(timezone.utc).isoformat()
        record = ArtifactRecord(
            artifact_hash=digest,
            artifact_type=artifact_type,
            work_order_id=work_order_id,
            work_order_version=work_order_version,
            step_id=step_id,
            producing_worker_id=producing_worker_id,
            producing_profile_hash=producing_profile_hash,
            capability_token_id=capability_token_id,
            parent_artifact_hashes=parent_artifact_hashes,
            created_at=now_iso,
            metadata=metadata or {},
        )

        if not target_path.exists():
            target_path.parent.mkdir(parents=True, exist_ok=True)
            # Write atomically via temp file
            tmp_target = target_path.with_suffix(".tmp")
            tmp_target.write_bytes(raw_bytes)
            tmp_target.rename(target_path)

            meta_json = canonical_json(record.to_dict())
            tmp_meta = meta_path.with_suffix(".tmp")
            tmp_meta.write_text(meta_json, encoding="utf-8")
            tmp_meta.rename(meta_path)

        return record

    def get(self, digest: str) -> bytes:
        target_path = self._path_for(digest)
        if not target_path.exists():
            raise FileNotFoundError(f"Artifact {digest} not found in store")
        content = target_path.read_bytes()
        actual_hash = sha256_digest(content)
        if actual_hash != digest:
            raise ArtifactIntegrityError(
                f"Tamper detected: expected {digest} but got {actual_hash}"
            )
        return content

    def get_record(self, digest: str) -> ArtifactRecord | None:
        meta_path = self._meta_path_for(digest)
        if not meta_path.exists():
            return None
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return ArtifactRecord(
            artifact_hash=data["artifact_hash"],
            artifact_type=ArtifactType(data["artifact_type"]),
            work_order_id=data["work_order_id"],
            work_order_version=data["work_order_version"],
            step_id=data["step_id"],
            producing_worker_id=data["producing_worker_id"],
            producing_profile_hash=data["producing_profile_hash"],
            capability_token_id=data["capability_token_id"],
            parent_artifact_hashes=tuple(data.get("parent_artifact_hashes", ())),
            created_at=data["created_at"],
            metadata=data.get("metadata", {}),
        )
