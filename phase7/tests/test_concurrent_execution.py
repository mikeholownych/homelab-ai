"""Tests for Concurrent Engineering Execution, Workspace Isolation, and Backpressure."""
import tempfile
from pathlib import Path
import pytest

from autonomous_engineering.service.concurrency_manager import (
    ConcurrencyManager,
    ConcurrencyError,
    QueueCapacityExceededError,
    AdmissionStoppedError,
)
from autonomous_engineering.work_order.compiler import WorkOrderCompiler


@pytest.fixture
def conc_env():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        repo_dir = tmp_path / "repo"
        repo_dir.mkdir(parents=True, exist_ok=True)
        (repo_dir / "mod_a.py").write_text("def a(): pass\n")
        (repo_dir / "mod_b.py").write_text("def b(): pass\n")
        (repo_dir / "tests").mkdir()
        (repo_dir / "tests" / "test_a.py").write_text("def test_a(): pass\n")

        manager = ConcurrencyManager(
            base_repo_dir=repo_dir,
            max_concurrency=2,
            max_queue_depth=3,
        )
        yield {
            "manager": manager,
            "repo_dir": repo_dir,
            "tmp_path": tmp_path,
        }


def test_isolated_workspace_creation_and_cleanup(conc_env):
    """Verifies that each concurrent task gets a fully isolated directory workspace."""
    manager = conc_env["manager"]
    compiler = WorkOrderCompiler()

    wo = compiler.compile(
        raw_text="Task 1",
        source_channel="cli",
        source_reference="s1",
        repository_id="aihost",
        baseline_commit="da54731",
        proposed_mutation_paths=["mod_a.py"],
    )
    object.__setattr__(wo, "work_order_id", "wo-c1")

    ws = manager.acquire_workspace(wo)
    assert ws.workspace_dir.exists()
    assert (ws.workspace_dir / "mod_a.py").exists()
    assert manager.get_active_count() == 1

    # Release workspace
    manager.release_workspace("wo-c1")
    assert not ws.workspace_dir.exists()
    assert manager.get_active_count() == 0


def test_path_conflict_detection_and_serialization(conc_env):
    """Verifies that two tasks targeting overlapping files are prevented from running concurrently."""
    manager = conc_env["manager"]
    compiler = WorkOrderCompiler()

    wo1 = compiler.compile(
        raw_text="Task 1 modifies mod_a.py",
        source_channel="cli",
        source_reference="s1",
        repository_id="aihost",
        baseline_commit="da54731",
        proposed_mutation_paths=["mod_a.py"],
    )
    object.__setattr__(wo1, "work_order_id", "wo-t1")

    wo2 = compiler.compile(
        raw_text="Task 2 also modifies mod_a.py (conflicting)",
        source_channel="cli",
        source_reference="s2",
        repository_id="aihost",
        baseline_commit="da54731",
        proposed_mutation_paths=["mod_a.py"],
    )
    object.__setattr__(wo2, "work_order_id", "wo-t2")

    wo3 = compiler.compile(
        raw_text="Task 3 modifies mod_b.py (non-conflicting)",
        source_channel="cli",
        source_reference="s3",
        repository_id="aihost",
        baseline_commit="da54731",
        proposed_mutation_paths=["mod_b.py"],
    )
    object.__setattr__(wo3, "work_order_id", "wo-t3")

    ws1 = manager.acquire_workspace(wo1)

    # wo2 conflicts on mod_a.py
    can_acquire, conflicts = manager.can_acquire_paths(wo2)
    assert can_acquire is False
    assert "mod_a.py" in conflicts
    with pytest.raises(ConcurrencyError, match="Path lock conflict"):
        manager.acquire_workspace(wo2)

    # wo3 is non-conflicting
    can_acquire_3, _ = manager.can_acquire_paths(wo3)
    assert can_acquire_3 is True
    ws3 = manager.acquire_workspace(wo3)
    assert manager.get_active_count() == 2

    # Cleanup
    manager.release_workspace("wo-t1")
    manager.release_workspace("wo-t3")


def test_queue_capacity_backpressure_and_pause(conc_env):
    """Verifies queue backpressure when max_queue_depth is exceeded and operator pause."""
    manager = conc_env["manager"]

    # Queue capacity check
    manager.check_admission_capacity(current_queue_size=2)  # Under limit of 3

    with pytest.raises(QueueCapacityExceededError, match="Backpressure engaged"):
        manager.check_admission_capacity(current_queue_size=3)

    # Operator pause admission
    manager.pause_admission()
    with pytest.raises(AdmissionStoppedError, match="paused by operator"):
        manager.check_admission_capacity(current_queue_size=1)

    manager.resume_admission()
    manager.check_admission_capacity(current_queue_size=1)
