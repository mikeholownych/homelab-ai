from pathlib import Path
import pytest

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.core.types import ValidationStatus
from autonomous_engineering.project.acceptance import (
    ProjectAcceptanceContract,
    ProjectAcceptanceManager,
)
from autonomous_engineering.project.integration import IntegratedRepositoryState


@pytest.fixture
def workspace_with_tests(tmp_path):
    ws_dir = tmp_path / "integrated_ws"
    ws_dir.mkdir()
    (ws_dir / "src").mkdir()
    (ws_dir / "src" / "calc.py").write_text("def add(a, b): return a + b\n")
    (ws_dir / "tests").mkdir()
    (ws_dir / "tests" / "test_calc.py").write_text("from src.calc import add\ndef test_add(): assert add(1, 2) == 3\n")

    store = ArtifactStore(tmp_path / "art_store")
    mgr = ProjectAcceptanceManager(store)

    import hashlib
    hasher = hashlib.sha256()
    for f in sorted(list(ws_dir.rglob("*.py"))):
        hasher.update(str(f.relative_to(ws_dir)).encode("utf-8"))
        hasher.update(f.read_bytes())
    tree_hash = hasher.hexdigest()

    state = IntegratedRepositoryState(
        project_id="proj-accept-1",
        plan_version=1,
        integrated_tree_hash=tree_hash,
        unified_patch="unified-patch",
        unified_patch_digest="patch-digest",
        modified_files=["src/calc.py"],
        applied_work_orders=["wo-calc"],
        rollback_instructions="rollback",
    )

    contract = ProjectAcceptanceContract(
        contract_id="contract-proj-1",
        project_id="proj-accept-1",
        plan_version=1,
        repository_id="repo-1",
        baseline_commit="commit-1",
        authorized_project_scope=("src/",),
        required_test_commands=("python3 -m pytest tests/test_calc.py",),
    )

    return {
        "manager": mgr,
        "workspace": ws_dir,
        "state": state,
        "contract": contract,
        "store": store,
    }


def test_clean_integrated_project_acceptance(workspace_with_tests):
    mgr = workspace_with_tests["manager"]
    verdict = mgr.validate_integrated_project(
        contract=workspace_with_tests["contract"],
        integrated_state=workspace_with_tests["state"],
        integrated_workspace_dir=workspace_with_tests["workspace"],
    )

    assert verdict.status == ValidationStatus.ACCEPTED
    assert len(verdict.execution_records) == 1
    assert verdict.execution_records[0].exit_code == 0


def test_tree_hash_tampering_rejected(workspace_with_tests):
    mgr = workspace_with_tests["manager"]
    # Provide a mismatched tree hash
    tampered_state = IntegratedRepositoryState(
        project_id="proj-accept-1",
        plan_version=1,
        integrated_tree_hash="deadbeef" * 8,  # Forged tree hash
        unified_patch="unified-patch",
        unified_patch_digest="patch-digest",
        modified_files=["src/calc.py"],
        applied_work_orders=["wo-calc"],
        rollback_instructions="rollback",
    )

    verdict = mgr.validate_integrated_project(
        contract=workspace_with_tests["contract"],
        integrated_state=tampered_state,
        integrated_workspace_dir=workspace_with_tests["workspace"],
    )

    assert verdict.status == ValidationStatus.REJECTED
    assert any("tree hash mismatch" in f for f in verdict.findings)


def test_prohibited_security_pattern_rejected(workspace_with_tests):
    mgr = workspace_with_tests["manager"]
    ws = workspace_with_tests["workspace"]

    # Inject eval() call
    (ws / "src" / "calc.py").write_text("def add(a, b):\n    eval('2+2')\n    return a + b\n")

    # Recompute tree hash for the state
    import hashlib
    hasher = hashlib.sha256()
    for f in sorted(list(ws.rglob("*.py"))):
        hasher.update(str(f.relative_to(ws)).encode("utf-8"))
        hasher.update(f.read_bytes())
    new_hash = hasher.hexdigest()

    sec_state = IntegratedRepositoryState(
        project_id="proj-accept-1",
        plan_version=1,
        integrated_tree_hash=new_hash,
        unified_patch="patch",
        unified_patch_digest="digest",
        modified_files=["src/calc.py"],
        applied_work_orders=["wo-calc"],
        rollback_instructions="rollback",
    )

    verdict = mgr.validate_integrated_project(
        contract=workspace_with_tests["contract"],
        integrated_state=sec_state,
        integrated_workspace_dir=ws,
    )

    assert verdict.status == ValidationStatus.REJECTED
    assert any("prohibited call to 'eval()'" in f for f in verdict.findings)
