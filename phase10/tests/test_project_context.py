from pathlib import Path
import pytest

from autonomous_engineering.project.context import (
    CheckpointRecord,
    CrossProjectLeakageError,
    ProjectContextManager,
    StaleProjectContextError,
)
from autonomous_engineering.project.planner import (
    EngineeringProjectPlan,
    ProjectWorkOrder,
)


@pytest.fixture
def context_mgr(tmp_path):
    db_file = tmp_path / "project_context.db"
    return ProjectContextManager(db_file)


def test_project_plan_persistence_and_resumption(context_mgr):
    wo = ProjectWorkOrder("wo-1", "Task 1", "defect_repair", ["src/a.py"], ["src/"], "implementation-engineer", [], [], 1024)
    plan = EngineeringProjectPlan("proj-persist", 1, "Persist Obj", "repo-1", "commit-aaa", ["src/"], [wo], [], "digest-123", True, "human@corp.com")

    context_mgr.save_project_plan(plan)

    # Retrieve and verify
    recovered = context_mgr.get_project_plan("proj-persist", expected_commit="commit-aaa")
    assert recovered is not None
    assert recovered.project_id == "proj-persist"
    assert recovered.is_human_authorized is True
    assert recovered.authorized_by == "human@corp.com"
    assert len(recovered.work_orders) == 1


def test_stale_commit_context_rejected(context_mgr):
    wo = ProjectWorkOrder("wo-1", "Task 1", "defect_repair", ["src/a.py"], ["src/"], "implementation-engineer", [], [], 1024)
    plan = EngineeringProjectPlan("proj-stale", 1, "Stale Obj", "repo-1", "commit-v1", ["src/"], [wo], [], "digest-stale", True)
    context_mgr.save_project_plan(plan)

    # Repository moved to commit-v2
    with pytest.raises(StaleProjectContextError):
        context_mgr.get_project_plan("proj-stale", expected_commit="commit-v2")


def test_intermediate_deliverables_and_checkpoints(context_mgr):
    context_mgr.record_intermediate_deliverable(
        project_id="proj-cp",
        work_order_id="wo-step-1",
        patch_text="--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n+fixed\n",
        patch_digest="sha-step-1",
        validation_status="ACCEPTED",
    )

    delivs = context_mgr.get_intermediate_deliverables("proj-cp")
    assert "wo-step-1" in delivs
    assert delivs["wo-step-1"]["patch_digest"] == "sha-step-1"

    # Save and retrieve checkpoint
    cp = CheckpointRecord("cp-01", "proj-cp", 1, ["wo-step-1"], [], {"wo-step-1": "sha-step-1"}, "Step 1 complete")
    context_mgr.save_checkpoint(cp)

    latest = context_mgr.get_latest_checkpoint("proj-cp")
    assert latest is not None
    assert latest.checkpoint_id == "cp-01"
    assert latest.completed_task_ids == ["wo-step-1"]


def test_cross_project_isolation(context_mgr):
    with pytest.raises(CrossProjectLeakageError):
        context_mgr.validate_project_isolation("project-alpha", "project-beta")
