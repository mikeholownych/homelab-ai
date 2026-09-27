"""Tests for Phase 8 Repository Onboarding, Contracts, and Scope Authority."""
import tempfile
from pathlib import Path
import pytest

from autonomous_engineering.authority.admission import AdmissionEvaluator
from autonomous_engineering.repository.onboarding import (
    RepositoryContract,
    RepositoryOnboardingManager,
    RepositoryError,
    RepositoryNotOnboardedError,
    RepositoryValidationError,
    ProtectedPathViolationError,
    ScopeBoundaryError,
)
from autonomous_engineering.work_order.compiler import WorkOrderCompiler


@pytest.fixture
def onboarding_manager():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "repo_contracts.sqlite"
        mgr = RepositoryOnboardingManager(db_path=db_path)
        yield mgr


def test_repository_onboarding_lifecycle(onboarding_manager):
    """Verifies complete repository onboarding lifecycle, persistence, and retrieval."""
    contract = RepositoryContract(
        repository_id="aihost-core",
        remote_url="git@github.com:mikeholownych/aihost.git",
        baseline_commit="da54731",
        permitted_branches=("main", "release"),
        authorized_mutation_paths=("orchestrator_gateway", "orchestrator_runtime"),
        protected_paths=(".github", "ci", "validators"),
        required_test_commands=("pytest tests/",),
    )

    # 1. Onboard
    onboarding_manager.onboard_repository(contract)
    assert onboarding_manager.is_onboarded("aihost-core") is True

    # 2. Retrieve
    retrieved = onboarding_manager.get_contract("aihost-core")
    assert retrieved.repository_id == "aihost-core"
    assert retrieved.baseline_commit == "da54731"
    assert "orchestrator_gateway" in retrieved.authorized_mutation_paths
    assert "ci" in retrieved.protected_paths

    # 3. Offboard
    onboarding_manager.offboard_repository("aihost-core")
    assert onboarding_manager.is_onboarded("aihost-core") is False
    with pytest.raises(RepositoryNotOnboardedError):
        onboarding_manager.get_contract("aihost-core")


def test_contract_validation_rules(onboarding_manager):
    """Verifies that invalid or dangerous contracts are rejected at onboarding time."""
    # Invalid ID
    with pytest.raises(RepositoryValidationError, match="Invalid repository ID"):
        onboarding_manager.onboard_repository(
            RepositoryContract(
                repository_id="bad id with spaces!",
                remote_url="git@github.com:mike/repo.git",
                baseline_commit="da54731",
            )
        )

    # Invalid Commit
    with pytest.raises(RepositoryValidationError, match="Invalid baseline commit"):
        onboarding_manager.onboard_repository(
            RepositoryContract(
                repository_id="repo-1",
                remote_url="git@github.com:mike/repo.git",
                baseline_commit="not-a-hex-hash",
            )
        )

    # Path traversal in protected paths
    with pytest.raises(RepositoryValidationError, match="cannot contain path traversal"):
        onboarding_manager.onboard_repository(
            RepositoryContract(
                repository_id="repo-1",
                remote_url="git@github.com:mike/repo.git",
                baseline_commit="da54731",
                protected_paths=("../etc/passwd",),
            )
        )


def test_protected_and_authorized_path_enforcement(onboarding_manager):
    """Verifies that protected paths override and path traversal attempts fail closed."""
    contract = RepositoryContract(
        repository_id="repo-scoped",
        remote_url="git@github.com:mike/repo.git",
        baseline_commit="512543a",
        authorized_mutation_paths=("src/services", "tests"),
        protected_paths=(".github", "src/services/security", "ci"),
    )
    onboarding_manager.onboard_repository(contract)

    # 1. Valid path within authorized scope
    onboarding_manager.validate_work_order_scope(
        "repo-scoped", ["src/services/api.py", "tests/test_api.py"]
    )

    # 2. Path outside authorized mutation scope
    with pytest.raises(ScopeBoundaryError, match="outside authorized mutation paths"):
        onboarding_manager.validate_work_order_scope(
            "repo-scoped", ["src/other/module.py"]
        )

    # 3. Path touching protected path within authorized parent
    with pytest.raises(ProtectedPathViolationError, match="violates protected repository path rule"):
        onboarding_manager.validate_work_order_scope(
            "repo-scoped", ["src/services/security/keys.py"]
        )

    # 4. Path traversal attempt
    with pytest.raises(ScopeBoundaryError, match="prohibited path traversal"):
        onboarding_manager.validate_work_order_scope(
            "repo-scoped", ["src/services/../../etc/shadow"]
        )


def test_admission_evaluator_integration_with_onboarding(onboarding_manager):
    """Verifies that AdmissionEvaluator automatically enforces repository onboarding and contracts."""
    contract = RepositoryContract(
        repository_id="aihost",
        remote_url="git@github.com:mikeholownych/aihost.git",
        baseline_commit="512543a",
        authorized_mutation_paths=("orchestrator_gateway",),
        protected_paths=(".github", "validators"),
    )
    onboarding_manager.onboard_repository(contract)

    admission = AdmissionEvaluator(onboarding_manager=onboarding_manager)
    compiler = WorkOrderCompiler()

    # 1. Work order for onboarded repo with authorized path -> ADMITTED
    wo_valid = compiler.compile(
        raw_text="Add helper method to server.py",
        source_channel="cli",
        source_reference="sess-1",
        repository_id="aihost",
        baseline_commit="512543a",
        proposed_mutation_paths=["orchestrator_gateway/server.py"],
    )
    dec_valid = admission.evaluate(wo_valid)
    assert dec_valid.admitted is True

    # 2. Work order targeting un-onboarded repository -> REJECTED
    wo_unonboarded = compiler.compile(
        raw_text="Add feature to unknown repo",
        source_channel="cli",
        source_reference="sess-2",
        repository_id="unregistered-repo",
        baseline_commit="512543a",
        proposed_mutation_paths=["src/main.py"],
    )
    dec_unonboarded = admission.evaluate(wo_unonboarded)
    assert dec_unonboarded.admitted is False
    assert "has not completed onboarding" in dec_unonboarded.reason

    # 3. Work order violating protected path -> REJECTED
    wo_protected = compiler.compile(
        raw_text="Modify CI workflow",
        source_channel="cli",
        source_reference="sess-3",
        repository_id="aihost",
        baseline_commit="512543a",
        proposed_mutation_paths=[".github/workflows/ci.yml"],
    )
    dec_protected = admission.evaluate(wo_protected)
    assert dec_protected.admitted is False
    assert "violates protected repository path rule" in dec_protected.reason
