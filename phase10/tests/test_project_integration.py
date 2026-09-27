from pathlib import Path
import pytest

from autonomous_engineering.project.integration import (
    IntegrationConflictError,
    MissingDeliverableError,
    ProjectIntegrationManager,
    UnauthorizedIntegrationScopeError,
)
from autonomous_engineering.project.planner import (
    EngineeringProjectPlan,
    ProjectWorkOrder,
)


@pytest.fixture
def base_repo(tmp_path):
    repo_dir = tmp_path / "integration_base"
    repo_dir.mkdir()
    (repo_dir / "src").mkdir()
    (repo_dir / "src" / "math_ops.py").write_text("def add(a, b): return a + b\n")
    (repo_dir / "src" / "printer.py").write_text("def display(val): print(val)\n")
    return repo_dir


def test_clean_multi_deliverable_integration(base_repo):
    mgr = ProjectIntegrationManager()

    wo1 = ProjectWorkOrder("wo-add", "Add multiply", "defect_repair", ["src/math_ops.py"], ["src/"], "implementation-engineer", [], [], 1024)
    wo2 = ProjectWorkOrder("wo-disp", "Display format", "defect_repair", ["src/printer.py"], ["src/"], "implementation-engineer", ["wo-add"], [], 1024)

    plan = EngineeringProjectPlan(
        project_id="proj-integ-1",
        plan_version=1,
        objective="Enhance math and display",
        repository_id="math-repo",
        baseline_commit="commit-integ-1",
        authorized_project_scope=["src/"],
        work_orders=[wo1, wo2],
        dependency_edges=[("wo-add", "wo-disp")],
        plan_digest="digest-integ-1",
        is_human_authorized=True,
    )

    deliverables = {
        "wo-add": {
            "patch_text": "--- a/src/math_ops.py\n+++ b/src/math_ops.py\n@@ -1,1 +1,2 @@\n def add(a, b): return a + b\n+def mul(a, b): return a * b\n",
            "patch_digest": "sha-p1",
            "validation_status": "ACCEPTED",
        },
        "wo-disp": {
            "patch_text": "--- a/src/printer.py\n+++ b/src/printer.py\n@@ -1,1 +1,2 @@\n def display(val): print(val)\n+def display_hex(val): print(hex(val))\n",
            "patch_digest": "sha-p2",
            "validation_status": "ACCEPTED",
        },
    }

    state, temp_dir = mgr.integrate_project_deliverables(plan, base_repo, deliverables)
    assert len(state.integrated_tree_hash) == 64
    assert state.applied_work_orders == ["wo-add", "wo-disp"]
    assert "src/math_ops.py" in state.modified_files
    assert "src/printer.py" in state.modified_files

    # Clean up temp dir
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_missing_intermediate_deliverable_rejected(base_repo):
    mgr = ProjectIntegrationManager()
    wo1 = ProjectWorkOrder("wo-1", "Task 1", "defect_repair", ["src/math_ops.py"], ["src/"], "implementation-engineer", [], [], 1024)
    plan = EngineeringProjectPlan("proj-miss", 1, "Obj", "repo", "commit", ["src/"], [wo1], [], "d", True)

    # Empty deliverables dictionary
    with pytest.raises(MissingDeliverableError):
        mgr.integrate_project_deliverables(plan, base_repo, {})


def test_unauthorized_scope_expansion_during_integration_rejected(base_repo):
    mgr = ProjectIntegrationManager()
    # Work order claims unauthorized file
    wo = ProjectWorkOrder("wo-bad", "Bad", "defect_repair", [".github/workflow.yml"], ["src/"], "implementation-engineer", [], [], 1024)
    plan = EngineeringProjectPlan("proj-scope", 1, "Obj", "repo", "commit", ["src/"], [wo], [], "d", True)

    delivs = {"wo-bad": {"patch_text": "+ bad", "patch_digest": "sha", "validation_status": "ACCEPTED"}}

    with pytest.raises(UnauthorizedIntegrationScopeError):
        mgr.integrate_project_deliverables(plan, base_repo, delivs)
