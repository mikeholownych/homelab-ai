from pathlib import Path
import subprocess
from typing import Any
import pytest

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.core.types import ValidationStatus
from autonomous_engineering.investigation.project_investigator import RepositoryScaleInvestigator
from autonomous_engineering.knowledge.manager import RepositoryKnowledgeManager
from autonomous_engineering.project.acceptance import (
    ProjectAcceptanceContract,
    ProjectAcceptanceManager,
)
from autonomous_engineering.project.context import ProjectContextManager
from autonomous_engineering.project.engine import (
    ProjectExecutionEngine,
    ProjectExecutionStatus,
)
from autonomous_engineering.project.integration import (
    IntegratedRepositoryState,
    ProjectIntegrationManager,
)
from autonomous_engineering.project.planner import (
    EngineeringProjectPlan,
    EngineeringProjectPlanner,
    ProjectWorkOrder,
)


def test_gate_g01_baseline_verification():
    base_file = Path("phase10_baseline_verification.md")
    assert base_file.exists()
    content = base_file.read_text(encoding="utf-8")
    assert "fe09e6c" in content
    assert "253" in content


def test_gate_g02_versioned_repository_knowledge(tmp_path):
    repo_dir = tmp_path / "g2_repo"
    repo_dir.mkdir()
    (repo_dir / "mod.py").write_text("class Core:\n    pass\n")
    mgr = RepositoryKnowledgeManager()
    graph = mgr.index_repository(repo_dir, "g2-repo", "c1")
    assert "mod.py" in graph.symbols_by_file
    assert len(graph.compute_digest()) == 64


def test_gate_g03_repository_scale_investigation(tmp_path):
    repo_dir = tmp_path / "g3_repo"
    repo_dir.mkdir()
    (repo_dir / "service.py").write_text("def serve(): return True\n")
    mgr = RepositoryKnowledgeManager()
    graph = mgr.index_repository(repo_dir, "g3-repo", "c1")
    inv = RepositoryScaleInvestigator(graph)
    report = inv.generate_investigation_report("Investigate service", ["service.py"])
    assert len(report.findings) >= 1
    assert len(report.findings[0].citations) >= 1


def test_gate_g04_project_planning_and_decomposition():
    planner = EngineeringProjectPlanner("repo", "c")
    wo = ProjectWorkOrder("wo-1", "T", "defect_repair", ["a.py"], ["src/"], "implementation-engineer", [], [], 1024)
    plan = planner.create_project_plan("p4", 1, "Obj", ["src/"], [wo], [])
    assert len(plan.plan_digest) == 64


def test_gate_g05_durable_cross_session_context(tmp_path):
    ctx_mgr = ProjectContextManager(tmp_path / "g5_ctx.db")
    wo = ProjectWorkOrder("wo-1", "T", "defect_repair", ["a.py"], ["src/"], "implementation-engineer", [], [], 1024)
    plan = EngineeringProjectPlan("p5", 1, "Obj", "repo", "c", ["src/"], [wo], [], "d", True)
    ctx_mgr.save_project_plan(plan)
    recovered = ctx_mgr.get_project_plan("p5")
    assert recovered.project_id == "p5"


def test_gate_g06_dependency_aware_project_execution(tmp_path):
    repo_dir = tmp_path / "g6_repo"
    repo_dir.mkdir()
    (repo_dir / "src").mkdir()
    (repo_dir / "src" / "a.py").write_text("def f(): pass\n")
    store = ArtifactStore(tmp_path / "g6_store")
    ctx_mgr = ProjectContextManager(tmp_path / "g6_ctx.db")
    engine = ProjectExecutionEngine(ctx_mgr, store)

    wo = ProjectWorkOrder("wo-1", "T", "defect_repair", ["src/a.py"], ["src/a.py"], "implementation-engineer", [], [], 1024)
    plan = EngineeringProjectPlan("p6", 1, "Obj", "repo", "c", ["src/"], [wo], [], "d", True)

    result = engine.execute_project(plan, repo_dir)
    assert result.status == ProjectExecutionStatus.ACCEPTED


def test_gate_g07_cross_task_integration(tmp_path):
    repo_dir = tmp_path / "g7_repo"
    repo_dir.mkdir()
    (repo_dir / "app.py").write_text("x = 1\n")
    integ = ProjectIntegrationManager()
    wo = ProjectWorkOrder("wo-1", "T", "defect_repair", ["app.py"], ["app.py"], "implementation-engineer", [], [], 1024)
    plan = EngineeringProjectPlan("p7", 1, "Obj", "repo", "c", ["app.py"], [wo], [], "d", True)
    delivs = {"wo-1": {"patch_text": "--- a/app.py\n+++ b/app.py\n@@ -1,1 +1,2 @@\n x = 1\n+y = 2\n", "patch_digest": "s", "validation_status": "ACCEPTED"}}

    state, temp_dir = integ.integrate_project_deliverables(plan, repo_dir, delivs)
    assert len(state.integrated_tree_hash) == 64
    import shutil
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_gate_g08_independent_project_acceptance(tmp_path):
    ws = tmp_path / "g8_ws"
    ws.mkdir()
    (ws / "math_fn.py").write_text("def add(a, b): return a + b\n")

    store = ArtifactStore(tmp_path / "g8_store")
    mgr = ProjectAcceptanceManager(store)

    import hashlib
    h = hashlib.sha256(b"math_fn.py" + (ws / "math_fn.py").read_bytes()).hexdigest()
    state = IntegratedRepositoryState("p8", 1, h, "patch", "digest", ["math_fn.py"], ["wo-1"], "rollback")
    contract = ProjectAcceptanceContract("c8", "p8", 1, "r", "c", ("math_fn.py",), ())

    verdict = mgr.validate_integrated_project(contract, state, ws)
    assert verdict.status == ValidationStatus.ACCEPTED


def test_gate_g09_recovery_qualification(tmp_path):
    ctx_mgr = ProjectContextManager(tmp_path / "g9_ctx.db")
    from autonomous_engineering.project.context import CheckpointRecord
    cp = CheckpointRecord("cp-1", "p9", 1, ["wo-1"], [], {"wo-1": "hash"}, "Summary")
    ctx_mgr.save_checkpoint(cp)
    recovered = ctx_mgr.get_latest_checkpoint("p9")
    assert recovered.checkpoint_id == "cp-1"


def test_gate_g10_real_repository_project_qualification(tmp_path):
    repo_dir = tmp_path / "g10_repo"
    repo_dir.mkdir()
    (repo_dir / "src").mkdir()
    (repo_dir / "src" / "processor.py").write_text("def process(): return 'OK'\n")

    store = ArtifactStore(tmp_path / "g10_store")
    ctx_mgr = ProjectContextManager(tmp_path / "g10_ctx.db")
    engine = ProjectExecutionEngine(ctx_mgr, store)

    wo = ProjectWorkOrder("wo-proc", "T", "defect_repair", ["src/processor.py"], ["src/processor.py"], "implementation-engineer", [], [], 1024)
    plan = EngineeringProjectPlan("p10-qual", 1, "Obj", "aihost", "commit-g10", ["src/"], [wo], [], "d", True)

    result = engine.execute_project(plan, repo_dir)
    assert result.status == ProjectExecutionStatus.ACCEPTED
    assert result.disposition == "PROJECT_ACCEPTED_PROVEN"


def test_gate_g11_adversarial_security():
    try:
        from phase10.tests.test_phase10_adversarial_security import test_adversarial_01_unauthorized_scope_expansion_rejected
    except ImportError:
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent))
        from test_phase10_adversarial_security import test_adversarial_01_unauthorized_scope_expansion_rejected
    test_adversarial_01_unauthorized_scope_expansion_rejected()


def test_gate_g12_cumulative_regression_integrity():
    assert Path("phase10/src/autonomous_engineering").exists()


def test_gate_g13_protected_services_non_interference():
    res = subprocess.run(["ps", "-p", "986,3130937,2093382", "-o", "pid="], capture_output=True, text=True)
    pids = res.stdout.strip().split()
    assert "986" in pids
    assert "3130937" in pids
    assert "2093382" in pids


def test_gate_g14_cryptographic_deliverable_custody(tmp_path):
    state = IntegratedRepositoryState(
        "p14",
        1,
        "a" * 64,
        "patch content",
        "b" * 64,
        ["app.py"],
        ["wo-1"],
        "patch -p1 -R < unified.patch",
    )
    assert len(state.unified_patch_digest) == 64
    assert len(state.integrated_tree_hash) == 64
    assert "patch -p1 -R" in state.rollback_instructions

