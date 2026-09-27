from pathlib import Path
import pytest

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.project.context import ProjectContextManager
from autonomous_engineering.project.engine import (
    ProjectExecutionEngine,
    ProjectExecutionStatus,
)
from autonomous_engineering.project.planner import (
    EngineeringProjectPlan,
    ProjectWorkOrder,
)


@pytest.fixture
def project_execution_env(tmp_path):
    repo_dir = tmp_path / "exec_repo"
    repo_dir.mkdir()
    (repo_dir / "src").mkdir()
    (repo_dir / "src" / "service.py").write_text("def run(): return 1\n")
    (repo_dir / "src" / "client.py").write_text("from src.service import run\ndef call(): return run()\n")
    (repo_dir / "tests").mkdir()
    (repo_dir / "tests" / "test_service.py").write_text("def test_dummy(): assert True\n")

    store = ArtifactStore(tmp_path / "artifacts")
    ctx_mgr = ProjectContextManager(tmp_path / "context.db")
    engine = ProjectExecutionEngine(context_manager=ctx_mgr, artifact_store=store)

    return {
        "repo_dir": repo_dir,
        "engine": engine,
        "ctx_mgr": ctx_mgr,
        "store": store,
    }


def test_end_to_end_project_execution(project_execution_env):
    engine = project_execution_env["engine"]
    repo_dir = project_execution_env["repo_dir"]

    wo1 = ProjectWorkOrder(
        work_order_id="wo-srv-01",
        title="Refactor core service",
        task_class="defect_repair",
        target_files=["src/service.py"],
        authorized_mutation_paths=["src/service.py"],
        required_specialization="implementation-engineer",
        prerequisite_task_ids=[],
        acceptance_criteria=["python3 -m pytest tests/test_service.py"],
        resource_budget_tokens=2048,
    )
    wo2 = ProjectWorkOrder(
        work_order_id="wo-cli-02",
        title="Update client interface",
        task_class="multi_file",
        target_files=["src/client.py"],
        authorized_mutation_paths=["src/client.py"],
        required_specialization="implementation-engineer",
        prerequisite_task_ids=["wo-srv-01"],
        acceptance_criteria=["python3 -m pytest tests/test_service.py"],
        resource_budget_tokens=2048,
    )

    plan = EngineeringProjectPlan(
        project_id="proj-e2e-1",
        plan_version=1,
        objective="Modernize service and client layer",
        repository_id="aihost",
        baseline_commit="commit-e2e-base",
        authorized_project_scope=["src/"],
        work_orders=[wo1, wo2],
        dependency_edges=[("wo-srv-01", "wo-cli-02")],
        plan_digest="digest-e2e-1",
        is_human_authorized=True,
        authorized_by="human-lead@corp.com",
    )

    result = engine.execute_project(plan=plan, base_repo_dir=repo_dir)

    assert result.status == ProjectExecutionStatus.ACCEPTED
    assert result.disposition == "PROJECT_ACCEPTED_PROVEN"
    assert result.executed_work_orders == ["wo-srv-01", "wo-cli-02"]
    assert len(result.intermediate_deliverable_digests) == 2
    assert result.integrated_state is not None
    assert len(result.integrated_state.integrated_tree_hash) == 64


def test_unauthorized_plan_fails_closed(project_execution_env):
    engine = project_execution_env["engine"]
    repo_dir = project_execution_env["repo_dir"]

    wo = ProjectWorkOrder("wo-1", "Task", "defect_repair", ["src/service.py"], ["src/"], "implementation-engineer", [], [], 1024)
    # is_human_authorized=False
    plan = EngineeringProjectPlan("proj-unauth", 1, "Obj", "repo", "commit", ["src/"], [wo], [], "d", False)

    result = engine.execute_project(plan, repo_dir)
    assert result.status == ProjectExecutionStatus.UNAUTHORIZED_PLAN
    assert result.disposition == "REJECTED_UNAUTHORIZED_PLAN"
