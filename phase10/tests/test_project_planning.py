import pytest

from autonomous_engineering.project.planner import (
    CyclicDependencyError,
    EngineeringProjectPlanner,
    ProjectWorkOrder,
    SelfAuthorizationProhibitedError,
    UnauthorizedScopeExpansionError,
)


def test_valid_project_plan_creation():
    planner = EngineeringProjectPlanner(repository_id="aihost", baseline_commit="commit-plan-1")

    wo1 = ProjectWorkOrder(
        work_order_id="wo-core-01",
        title="Refactor core service",
        task_class="defect_repair",
        target_files=["src/service.py"],
        authorized_mutation_paths=["src/service.py"],
        required_specialization="implementation-engineer",
        prerequisite_task_ids=[],
        acceptance_criteria=["pytest tests/test_service.py"],
        resource_budget_tokens=2048,
    )
    wo2 = ProjectWorkOrder(
        work_order_id="wo-api-02",
        title="Update API routes to match new service",
        task_class="multi_file",
        target_files=["src/routes.py"],
        authorized_mutation_paths=["src/routes.py"],
        required_specialization="implementation-engineer",
        prerequisite_task_ids=["wo-core-01"],
        acceptance_criteria=["pytest tests/test_routes.py"],
        resource_budget_tokens=2048,
    )

    plan = planner.create_project_plan(
        project_id="proj-01",
        plan_version=1,
        objective="Modernize API service architecture",
        authorized_project_scope=["src/"],
        work_orders=[wo1, wo2],
        dependency_edges=[("wo-core-01", "wo-api-02")],
    )

    assert plan.project_id == "proj-01"
    assert len(plan.plan_digest) == 64
    assert plan.is_human_authorized is False

    # Human authorization
    auth_plan = planner.authorize_plan(plan, authorizer_identity="human-lead@company.com", authorizer_role="Engineering Director")
    assert auth_plan.is_human_authorized is True
    assert auth_plan.authorized_by == "human-lead@company.com"


def test_cyclic_dependency_rejected():
    planner = EngineeringProjectPlanner(repository_id="aihost", baseline_commit="commit-plan-2")

    wo1 = ProjectWorkOrder("wo-1", "Task 1", "defect_repair", ["src/a.py"], ["src/"], "implementation-engineer", ["wo-2"], [], 1024)
    wo2 = ProjectWorkOrder("wo-2", "Task 2", "defect_repair", ["src/b.py"], ["src/"], "implementation-engineer", ["wo-1"], [], 1024)

    with pytest.raises(CyclicDependencyError):
        planner.create_project_plan(
            project_id="proj-cycle",
            plan_version=1,
            objective="Cyclic task objective",
            authorized_project_scope=["src/"],
            work_orders=[wo1, wo2],
            dependency_edges=[("wo-1", "wo-2"), ("wo-2", "wo-1")],
        )


def test_unauthorized_scope_expansion_rejected():
    planner = EngineeringProjectPlanner(repository_id="aihost", baseline_commit="commit-plan-3")

    # Work order targets .github/ which is outside authorized project scope ["src/"]
    wo = ProjectWorkOrder("wo-bad", "Bad Task", "defect_repair", [".github/workflows/ci.yml"], [".github/"], "implementation-engineer", [], [], 1024)

    with pytest.raises(UnauthorizedScopeExpansionError):
        planner.create_project_plan(
            project_id="proj-bad-scope",
            plan_version=1,
            objective="Target unauthorized directory",
            authorized_project_scope=["src/"],
            work_orders=[wo],
            dependency_edges=[],
        )


def test_planner_self_authorization_prohibited():
    planner = EngineeringProjectPlanner(repository_id="aihost", baseline_commit="commit-plan-4")
    wo = ProjectWorkOrder("wo-ok", "Task", "defect_repair", ["src/ok.py"], ["src/"], "implementation-engineer", [], [], 1024)
    plan = planner.create_project_plan("proj-auth-test", 1, "Obj", ["src/"], [wo], [])

    with pytest.raises(SelfAuthorizationProhibitedError):
        planner.authorize_plan(plan, authorizer_identity="autonomous-planner-agent-v1", authorizer_role="Automated Planning Agent")
