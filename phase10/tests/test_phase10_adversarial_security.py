from pathlib import Path
import pytest

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.core.types import ValidationStatus
from autonomous_engineering.knowledge.manager import (
    KnowledgeCapacityExceededError,
    RepositoryKnowledgeManager,
    StaleKnowledgeError,
)
from autonomous_engineering.project.acceptance import (
    ProjectAcceptanceContract,
    ProjectAcceptanceManager,
)
from autonomous_engineering.project.context import (
    CrossProjectLeakageError,
    ProjectContextManager,
    StaleProjectContextError,
)
from autonomous_engineering.project.integration import (
    IntegratedRepositoryState,
    IntegrationConflictError,
    MissingDeliverableError,
    ProjectIntegrationManager,
    UnauthorizedIntegrationScopeError,
)
from autonomous_engineering.project.planner import (
    CyclicDependencyError,
    EngineeringProjectPlan,
    EngineeringProjectPlanner,
    ProjectWorkOrder,
    SelfAuthorizationProhibitedError,
    UnauthorizedScopeExpansionError,
)


def test_adversarial_01_unauthorized_scope_expansion_rejected():
    planner = EngineeringProjectPlanner("repo-1", "commit-1")
    wo = ProjectWorkOrder("wo-bad", "Bad", "defect_repair", [".github/secrets.yml"], [".github/"], "implementation-engineer", [], [], 1024)
    with pytest.raises(UnauthorizedScopeExpansionError):
        planner.create_project_plan("proj-adv-1", 1, "Obj", ["src/"], [wo], [])


def test_adversarial_02_dependency_cycle_injection():
    planner = EngineeringProjectPlanner("repo-1", "commit-1")
    wo1 = ProjectWorkOrder("wo-1", "T1", "defect_repair", ["src/a.py"], ["src/"], "implementation-engineer", ["wo-2"], [], 1024)
    wo2 = ProjectWorkOrder("wo-2", "T2", "defect_repair", ["src/b.py"], ["src/"], "implementation-engineer", ["wo-1"], [], 1024)
    with pytest.raises(CyclicDependencyError):
        planner.create_project_plan("proj-adv-2", 1, "Obj", ["src/"], [wo1, wo2], [("wo-1", "wo-2"), ("wo-2", "wo-1")])


def test_adversarial_03_planning_agent_self_authorization():
    planner = EngineeringProjectPlanner("repo-1", "commit-1")
    wo = ProjectWorkOrder("wo-1", "T", "defect_repair", ["src/a.py"], ["src/"], "implementation-engineer", [], [], 1024)
    plan = planner.create_project_plan("proj-adv-3", 1, "Obj", ["src/"], [wo], [])
    with pytest.raises(SelfAuthorizationProhibitedError):
        planner.authorize_plan(plan, "ai-agent-planner-v2", "Autonomous Systems Planner")


def test_adversarial_04_stale_repository_knowledge_rejected(tmp_path):
    repo_dir = tmp_path / "repo_adv4"
    repo_dir.mkdir()
    (repo_dir / "mod.py").write_text("x = 1\n")
    mgr = RepositoryKnowledgeManager()
    mgr.index_repository(repo_dir, "repo-adv4", "commit-v1")
    with pytest.raises(StaleKnowledgeError):
        mgr.get_graph("repo-adv4", expected_commit="commit-v2")


def test_adversarial_05_tampered_tree_hash_rejected(tmp_path):
    store = ArtifactStore(tmp_path / "arts")
    mgr = ProjectAcceptanceManager(store)
    ws = tmp_path / "ws_adv5"
    ws.mkdir()
    (ws / "main.py").write_text("print('hello')\n")

    state = IntegratedRepositoryState("p5", 1, "forged_tree_hash" * 4, "patch", "digest", ["main.py"], ["wo-1"], "rollback")
    contract = ProjectAcceptanceContract("c5", "p5", 1, "r", "c", ("main.py",), ())

    verdict = mgr.validate_integrated_project(contract, state, ws)
    assert verdict.status == ValidationStatus.REJECTED
    assert any("tree hash mismatch" in f for f in verdict.findings)


def test_adversarial_06_cross_project_context_leakage(tmp_path):
    ctx_mgr = ProjectContextManager(tmp_path / "ctx_adv6.db")
    with pytest.raises(CrossProjectLeakageError):
        ctx_mgr.validate_project_isolation("project-secret-corp", "project-public-open")


def test_adversarial_07_merge_conflict_detection(tmp_path):
    base_repo = tmp_path / "repo_adv7"
    base_repo.mkdir()
    (base_repo / "main.py").write_text("line 1\nline 2\n")

    integ = ProjectIntegrationManager()
    wo1 = ProjectWorkOrder("wo-1", "T1", "defect_repair", ["main.py"], ["main.py"], "implementation-engineer", [], [], 1024)
    wo2 = ProjectWorkOrder("wo-2", "T2", "defect_repair", ["main.py"], ["main.py"], "implementation-engineer", [], [], 1024)
    plan = EngineeringProjectPlan("p7", 1, "Obj", "r", "c", ["main.py"], [wo1, wo2], [], "d", True)

    # Conflicting patches targeting the exact same line with contradictory replacements
    delivs = {
        "wo-1": {"patch_text": "--- a/main.py\n+++ b/main.py\n@@ -1,2 +1,2 @@\n-line 1\n+line 1 modified by wo1\n line 2\n", "patch_digest": "s1", "validation_status": "ACCEPTED"},
        "wo-2": {"patch_text": "--- a/main.py\n+++ b/main.py\n@@ -1,2 +1,2 @@\n-line 1\n+line 1 modified by wo2\n line 2\n", "patch_digest": "s2", "validation_status": "ACCEPTED"},
    }

    # Second patch cannot apply cleanly on top of first
    with pytest.raises(IntegrationConflictError):
        integ.integrate_project_deliverables(plan, base_repo, delivs)


def test_adversarial_08_missing_intermediate_deliverable_evasion(tmp_path):
    base_repo = tmp_path / "repo_adv8"
    base_repo.mkdir()
    integ = ProjectIntegrationManager()
    wo = ProjectWorkOrder("wo-1", "T", "defect_repair", ["main.py"], ["main.py"], "implementation-engineer", [], [], 1024)
    plan = EngineeringProjectPlan("p8", 1, "Obj", "r", "c", ["main.py"], [wo], [], "d", True)

    with pytest.raises(MissingDeliverableError):
        integ.integrate_project_deliverables(plan, base_repo, {})


def test_adversarial_09_unauthorized_path_injection_during_integration(tmp_path):
    base_repo = tmp_path / "repo_adv9"
    base_repo.mkdir()
    integ = ProjectIntegrationManager()
    wo = ProjectWorkOrder("wo-bad", "T", "defect_repair", ["ci.yml"], ["src/"], "implementation-engineer", [], [], 1024)
    plan = EngineeringProjectPlan("p9", 1, "Obj", "r", "c", ["src/"], [wo], [], "d", True)

    delivs = {"wo-bad": {"patch_text": "+ bad", "patch_digest": "s", "validation_status": "ACCEPTED"}}
    with pytest.raises(UnauthorizedIntegrationScopeError):
        integ.integrate_project_deliverables(plan, base_repo, delivs)


def test_adversarial_10_ast_eval_injection_rejected(tmp_path):
    store = ArtifactStore(tmp_path / "arts_10")
    mgr = ProjectAcceptanceManager(store)
    ws = tmp_path / "ws_adv10"
    ws.mkdir()
    (ws / "app.py").write_text("eval('malicious()')\n")

    import hashlib
    h = hashlib.sha256(b"app.py" + (ws / "app.py").read_bytes()).hexdigest()
    state = IntegratedRepositoryState("p10", 1, h, "patch", "digest", ["app.py"], ["wo-1"], "rollback")
    contract = ProjectAcceptanceContract("c10", "p10", 1, "r", "c", ("app.py",), ())

    verdict = mgr.validate_integrated_project(contract, state, ws)
    assert verdict.status == ValidationStatus.REJECTED
    assert any("prohibited call to 'eval()'" in f for f in verdict.findings)


def test_adversarial_11_forbidden_module_import_rejected(tmp_path):
    store = ArtifactStore(tmp_path / "arts_11")
    mgr = ProjectAcceptanceManager(store)
    ws = tmp_path / "ws_adv11"
    ws.mkdir()
    (ws / "mod.py").write_text("import subprocess\n")

    import hashlib
    h = hashlib.sha256(b"mod.py" + (ws / "mod.py").read_bytes()).hexdigest()
    state = IntegratedRepositoryState("p11", 1, h, "patch", "digest", ["mod.py"], ["wo-1"], "rollback")
    contract = ProjectAcceptanceContract("c11", "p11", 1, "r", "c", ("mod.py",), ())

    verdict = mgr.validate_integrated_project(contract, state, ws)
    assert verdict.status == ValidationStatus.REJECTED
    assert any("prohibited import 'subprocess'" in f for f in verdict.findings)


def test_adversarial_12_test_timeout_containment(tmp_path):
    store = ArtifactStore(tmp_path / "arts_12")
    mgr = ProjectAcceptanceManager(store)
    ws = tmp_path / "ws_adv12"
    ws.mkdir()
    (ws / "main.py").write_text("x = 1\n")

    import hashlib
    h = hashlib.sha256(b"main.py" + (ws / "main.py").read_bytes()).hexdigest()
    state = IntegratedRepositoryState("p12", 1, h, "patch", "digest", ["main.py"], ["wo-1"], "rollback")
    # Execute a command that sleeps longer than timeout_seconds=1.0
    contract = ProjectAcceptanceContract("c12", "p12", 1, "r", "c", ("main.py",), ("sleep 5",), timeout_seconds=1.0)

    verdict = mgr.validate_integrated_project(contract, state, ws)
    assert verdict.status == ValidationStatus.REJECTED
    assert any("timed out" in f for f in verdict.findings)


def test_adversarial_13_knowledge_capacity_overflow(tmp_path):
    repo_dir = tmp_path / "repo_adv13"
    repo_dir.mkdir()
    for i in range(10):
        (repo_dir / f"file_{i}.py").write_text(f"class Class{i}: pass\n")
    mgr = RepositoryKnowledgeManager(max_symbols_per_repo=3)
    with pytest.raises(KnowledgeCapacityExceededError):
        mgr.index_repository(repo_dir, "repo-adv13", "c")


def test_adversarial_14_stale_project_context_rejection(tmp_path):
    ctx_mgr = ProjectContextManager(tmp_path / "ctx_adv14.db")
    wo = ProjectWorkOrder("wo-1", "T", "defect_repair", ["a.py"], ["a.py"], "implementation-engineer", [], [], 1024)
    plan = EngineeringProjectPlan("p14", 1, "Obj", "repo", "commit-v1", ["a.py"], [wo], [], "d", True)
    ctx_mgr.save_project_plan(plan)

    with pytest.raises(StaleProjectContextError):
        ctx_mgr.get_project_plan("p14", expected_commit="commit-v2")


def test_adversarial_15_cascading_failure_containment(tmp_path):
    from autonomous_engineering.project.engine import ProjectExecutionEngine, ProjectExecutionStatus
    repo_dir = tmp_path / "repo_adv15"
    repo_dir.mkdir()
    (repo_dir / "src").mkdir()
    (repo_dir / "src" / "a.py").write_text("def a(): pass\n")
    (repo_dir / "src" / "b.py").write_text("def b(): pass\n")

    store = ArtifactStore(tmp_path / "arts_15")
    ctx_mgr = ProjectContextManager(tmp_path / "ctx_15.db")
    engine = ProjectExecutionEngine(ctx_mgr, store)

    # Task 1 targets unauthorized path causing immediate scope failure
    wo1 = ProjectWorkOrder("wo-upstream-fail", "T1", "defect_repair", [".github/secrets.yml"], [".github/"], "implementation-engineer", [], [], 1024)
    wo2 = ProjectWorkOrder("wo-downstream", "T2", "defect_repair", ["src/b.py"], ["src/b.py"], "implementation-engineer", ["wo-upstream-fail"], [], 1024)

    # Bypass planner scope check by constructing plan directly with is_human_authorized=True
    plan = EngineeringProjectPlan("p15", 1, "Obj", "repo", "commit", ["src/", ".github/"], [wo1, wo2], [("wo-upstream-fail", "wo-downstream")], "d", True)

    result = engine.execute_project(plan, repo_dir)
    assert result.status == ProjectExecutionStatus.CASCADING_ABORTED
    assert "FAILED_UPSTREAM_TASK_wo-upstream-fail" in result.disposition


def test_adversarial_16_syntax_error_in_integrated_tree(tmp_path):
    store = ArtifactStore(tmp_path / "arts_16")
    mgr = ProjectAcceptanceManager(store)
    ws = tmp_path / "ws_adv16"
    ws.mkdir()
    (ws / "syntax_err.py").write_text("def broken(:\n")

    import hashlib
    h = hashlib.sha256(b"syntax_err.py" + (ws / "syntax_err.py").read_bytes()).hexdigest()
    state = IntegratedRepositoryState("p16", 1, h, "patch", "digest", ["syntax_err.py"], ["wo-1"], "rollback")
    contract = ProjectAcceptanceContract("c16", "p16", 1, "r", "c", ("syntax_err.py",), ())

    verdict = mgr.validate_integrated_project(contract, state, ws)
    assert verdict.status == ValidationStatus.REJECTED
    assert any("SyntaxError" in f for f in verdict.findings)
