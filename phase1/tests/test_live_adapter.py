"""Contract tests for LiveModelWorker connecting to OpenAI-Compatible Gateway."""
from datetime import datetime, timezone
from pathlib import Path
import pytest

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.authority.guard import ScopeViolationError
from autonomous_engineering.authority.tokens import CapabilityToken
from autonomous_engineering.core.types import ArtifactType
from autonomous_engineering.planning.models import TaskStepDefinition
from autonomous_engineering.workers.live_adapter import LiveModelWorker, LiveWorkerError


@pytest.fixture
def repo_fixture_path() -> Path:
    path = Path(__file__).parent.parent / "fixtures" / "disposable_repo"
    assert path.exists()
    return path


def test_live_adapter_contract_and_model_completion(tmp_path: Path, repo_fixture_path: Path):
    """Verifies that LiveModelWorker connects to live gateway, records request ID,

    and extracts unified diff patch artifact into ArtifactStore.
    """
    store = ArtifactStore(tmp_path / "artifacts")
    token_path = Path("/home/mike/.config/opencode/t5820-client-token")
    if not token_path.exists():
        pytest.skip("Live client token not accessible")

    worker = LiveModelWorker(
        worker_id="live-worker-b65",
        profile_hash="profile-live-b65",
        artifact_store=store,
        endpoint_url="http://127.0.0.1:18010/v1/chat/completions",
        token_path=token_path,
        model_name="engineering/b0",
    )

    token = CapabilityToken(
        token_id="tok-live-1",
        work_order_id="wo-live-test",
        work_order_version=1,
        task_id="step-patch",
        authorized_paths=("src/stats_utils.py",),
        authorized_tools=("read_file", "write_patch"),
        max_retries=1,
        fencing_token=1,
        issued_at=datetime.now(timezone.utc).isoformat(),
        expires_at="2030-01-01T00:00:00Z",
    )

    step = TaskStepDefinition(
        step_id="step-patch",
        required_role="defect_patch",
        description="Fix calculate_moving_average to raise ValueError when window_size <= 0 and return [] when window_size > len(data)",
        target_paths=("src/stats_utils.py",),
        dependencies=(),
        output_artifact_type=ArtifactType.PATCH,
    )

    result = worker.execute(
        assignment_id="asgn-live-1",
        step=step,
        token=token,
        fencing_token=1,
        input_artifacts=(),
        repo_dir=repo_fixture_path,
    )

    assert result.exit_code == 0
    assert result.output_artifact.artifact_type == ArtifactType.PATCH
    assert len(result.output_artifact.artifact_hash) == 64

    # Verify metadata captured
    meta = result.output_artifact.metadata
    assert meta["model_name"] == "engineering/b0"
    assert "request_id" in meta
    assert meta["request_id"].startswith("req-")
    assert "tokens_prompt" in meta  # May be int or None depending on gateway usage reporting

    # Verify patch bytes stored in CAS
    patch_bytes = store.get(result.output_artifact.artifact_hash)
    assert len(patch_bytes) > 0
    patch_text = patch_bytes.decode()
    assert "--- " in patch_text or "+++" in patch_text or "def calculate_moving_average" in patch_text


def test_live_adapter_enforces_scope_guard_before_network(tmp_path: Path, repo_fixture_path: Path):
    """Verifies that an unauthorized mutation path is halted by ScopeGuard BEFORE calling network."""
    store = ArtifactStore(tmp_path / "artifacts")
    worker = LiveModelWorker(
        worker_id="live-worker-b65",
        profile_hash="profile-live-b65",
        artifact_store=store,
    )

    # Token only authorizes stats_utils.py
    token = CapabilityToken(
        token_id="tok-live-2",
        work_order_id="wo-live-test",
        work_order_version=1,
        task_id="step-patch",
        authorized_paths=("src/stats_utils.py",),
        authorized_tools=("write_patch",),
        max_retries=1,
        fencing_token=1,
        issued_at=datetime.now(timezone.utc).isoformat(),
        expires_at="2030-01-01T00:00:00Z",
    )

    # Step asks for unauthorized path config/settings.py
    unauthorized_step = TaskStepDefinition(
        step_id="step-patch",
        required_role="defect_patch",
        description="Modify unauthorized config",
        target_paths=("config/settings.py",),
        dependencies=(),
        output_artifact_type=ArtifactType.PATCH,
    )

    with pytest.raises(ScopeViolationError):
        worker.execute("asgn-2", unauthorized_step, token, 1, repo_dir=repo_fixture_path)
