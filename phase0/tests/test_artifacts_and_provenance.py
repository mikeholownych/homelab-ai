"""Contract tests for Content-Addressed Immutable Artifacts and Provenance."""
from pathlib import Path
import pytest

from autonomous_engineering.artifacts.store import ArtifactIntegrityError, ArtifactStore
from autonomous_engineering.core.types import ArtifactType


def test_artifact_store_content_addressing_and_provenance(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")

    patch_bytes = b"diff --git a/test.py b/test.py\n+print('hello')\n"
    record = store.put(
        content=patch_bytes,
        artifact_type=ArtifactType.PATCH,
        work_order_id="wo-100",
        work_order_version=1,
        step_id="step-patch",
        producing_worker_id="worker-b65-0",
        producing_profile_hash="profile-hash-1",
        capability_token_id="token-1",
        parent_artifact_hashes=("parent-hash-0",),
        metadata={"commit_msg": "test patch"},
    )

    assert len(record.artifact_hash) == 64
    assert record.work_order_id == "wo-100"
    assert record.work_order_version == 1
    assert record.parent_artifact_hashes == ("parent-hash-0",)

    # Retrieval by hash
    retrieved = store.get(record.artifact_hash)
    assert retrieved == patch_bytes

    # Retrieval of record metadata
    meta = store.get_record(record.artifact_hash)
    assert meta is not None
    assert meta.producing_worker_id == "worker-b65-0"
    assert meta.metadata["commit_msg"] == "test patch"


def test_artifact_store_detects_tampering(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")

    original_bytes = b"safe_code_snippet = True"
    record = store.put(
        content=original_bytes,
        artifact_type=ArtifactType.PATCH,
        work_order_id="wo-tamper",
        work_order_version=1,
        step_id="step-1",
        producing_worker_id="worker-1",
        producing_profile_hash="prof-1",
        capability_token_id="tok-1",
    )

    # Tamper with file on disk directly
    prefix = record.artifact_hash[:2]
    raw_file = tmp_path / "artifacts" / prefix / record.artifact_hash
    assert raw_file.exists()
    raw_file.write_bytes(b"malicious_tampered_bytes = False")

    # Invariant: Tamper-evident read raises ArtifactIntegrityError
    with pytest.raises(ArtifactIntegrityError, match="Tamper detected"):
        store.get(record.artifact_hash)


def test_resume_from_last_proven_artifact(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")

    # Store step 1 artifact (investigation)
    art1 = store.put(
        content="reproduction script bytes",
        artifact_type=ArtifactType.REPRODUCTION_SCRIPT,
        work_order_id="wo-resume",
        work_order_version=1,
        step_id="step-investigate",
        producing_worker_id="worker-inv",
        producing_profile_hash="prof-inv",
        capability_token_id="tok-1",
    )

    # Store step 2 artifact (patch) bound explicitly to step 1 hash
    art2 = store.put(
        content="patch bytes",
        artifact_type=ArtifactType.PATCH,
        work_order_id="wo-resume",
        work_order_version=1,
        step_id="step-patch",
        producing_worker_id="worker-coder",
        producing_profile_hash="prof-coder",
        capability_token_id="tok-2",
        parent_artifact_hashes=(art1.artifact_hash,),
    )

    # Downstream execution loads exact inputs by artifact hash, without conversation history
    assert art2.parent_artifact_hashes == (art1.artifact_hash,)
    reloaded_input = store.get(art2.parent_artifact_hashes[0])
    assert reloaded_input == b"reproduction script bytes"
