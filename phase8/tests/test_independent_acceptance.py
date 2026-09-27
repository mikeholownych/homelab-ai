"""Tests for Independent Engineering Acceptance and Validator Authority."""
import tempfile
from pathlib import Path
import pytest

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.core.types import ValidationStatus
from autonomous_engineering.repository.onboarding import RepositoryContract
from autonomous_engineering.validator.acceptance import (
    AcceptanceContract,
    IndependentAcceptanceManager,
    ValidatorTamperingError,
)
from autonomous_engineering.work_order.compiler import WorkOrderCompiler


@pytest.fixture
def acceptance_env():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        art_store = ArtifactStore(tmp_path / "artifacts")
        repo_dir = tmp_path / "target_repo"
        repo_dir.mkdir()
        (repo_dir / "calc.py").write_text("def add(a, b):\n    return a + b\n")
        (repo_dir / "tests").mkdir()
        (repo_dir / "tests" / "test_calc.py").write_text(
            "from calc import add\ndef test_add(): assert add(2, 3) == 5\n"
        )

        manager = IndependentAcceptanceManager(artifact_store=art_store)
        repo_contract = RepositoryContract(
            repository_id="math-core",
            remote_url="git@github.com:mike/math.git",
            baseline_commit="da54731",
            authorized_mutation_paths=("calc.py",),
            required_test_commands=("python3 -m pytest tests/test_calc.py",),
        )
        compiler = WorkOrderCompiler()
        wo = compiler.compile(
            raw_text="Optimize addition logic",
            source_channel="cli",
            source_reference="s-acc-1",
            repository_id="math-core",
            baseline_commit="da54731",
            proposed_mutation_paths=["calc.py"],
        )
        object.__setattr__(wo, "work_order_id", "wo-math-01")

        yield {
            "manager": manager,
            "repo_dir": repo_dir,
            "repo_contract": repo_contract,
            "work_order": wo,
            "art_store": art_store,
        }


def test_acceptance_contract_creation_and_binding(acceptance_env):
    """Verifies that acceptance contract binds work order revision, baseline commit, and test commands."""
    manager = acceptance_env["manager"]
    wo = acceptance_env["work_order"]
    contract = manager.create_contract(wo, acceptance_env["repo_contract"])

    assert contract.contract_id == f"ac-{wo.work_order_id}-v{wo.version}"
    assert contract.repository_id == "math-core"
    assert contract.baseline_commit == "da54731"
    assert "calc.py" in contract.authorized_scope
    assert len(contract.contract_digest()) == 64


def test_anti_tampering_blocks_validator_modification(acceptance_env):
    """Verifies that an untrusted worker attempting to modify validator files triggers ValidatorTamperingError."""
    manager = acceptance_env["manager"]
    wo = acceptance_env["work_order"]
    contract = manager.create_contract(wo, acceptance_env["repo_contract"])

    tampering_patch = (
        "--- a/validators/acceptance.py\n"
        "+++ b/validators/acceptance.py\n"
        "@@ -1,1 +1,2 @@\n"
        "+# Malicious modification of validator definition\n"
    )

    with pytest.raises(ValidatorTamperingError, match="attempts to modify protected validator definition"):
        manager.validate_proposed_tree(
            contract=contract,
            proposed_repo_dir=acceptance_env["repo_dir"],
            patch_text=tampering_patch,
        )


def test_static_ast_and_security_rule_failures(acceptance_env):
    """Verifies that syntax errors or security violations reject the deliverable tree."""
    manager = acceptance_env["manager"]
    wo = acceptance_env["work_order"]
    repo_dir = acceptance_env["repo_dir"]
    contract = manager.create_contract(wo, acceptance_env["repo_contract"])

    # 1. Security Violation: eval() injection
    sec_patch = "--- calc.py\n+++ calc.py\n@@ -1,1 +1,2 @@\n+eval('2+2')\n"
    verdict_sec = manager.validate_proposed_tree(
        contract=contract,
        proposed_repo_dir=repo_dir,
        patch_text=sec_patch,
    )
    assert verdict_sec.status == ValidationStatus.REJECTED
    assert any("dynamic code execution" in f for f in verdict_sec.findings)

    # 2. Syntax Error in Proposed Tree
    (repo_dir / "calc.py").write_text("def broken_syntax(:\n")
    verdict_ast = manager.validate_proposed_tree(
        contract=contract,
        proposed_repo_dir=repo_dir,
        patch_text="",
    )
    assert verdict_ast.status == ValidationStatus.REJECTED
    assert any("SyntaxError" in f for f in verdict_ast.findings)


def test_independent_test_command_execution_and_digest(acceptance_env):
    """Verifies end-to-end execution of required test commands and CAS artifact custody."""
    manager = acceptance_env["manager"]
    wo = acceptance_env["work_order"]
    repo_dir = acceptance_env["repo_dir"]
    contract = manager.create_contract(wo, acceptance_env["repo_contract"])

    # Valid tree
    (repo_dir / "calc.py").write_text("def add(a, b):\n    return int(a) + int(b)\n")
    valid_patch = "--- calc.py\n+++ calc.py\n@@ -1,2 +1,2 @@\n def add(a, b):\n-    return a + b\n+    return int(a) + int(b)\n"

    verdict = manager.validate_proposed_tree(
        contract=contract,
        proposed_repo_dir=repo_dir,
        patch_text=valid_patch,
    )

    assert verdict.status == ValidationStatus.ACCEPTED
    assert len(verdict.execution_records) == 1
    assert verdict.execution_records[0].exit_code == 0
    assert len(verdict.execution_records[0].stdout_digest) == 64
    assert verdict.artifact_hash is not None

    # Verify verdict stored in CAS
    stored_art = acceptance_env["art_store"].get_record(verdict.artifact_hash)
    assert stored_art is not None
    assert stored_art.work_order_id == wo.work_order_id
