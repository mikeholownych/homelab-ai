"""Contract tests for Independent Acceptance Validator."""
from pathlib import Path
import pytest

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.core.types import ArtifactType, ValidationStatus
from autonomous_engineering.validator.independent import IndependentValidator
from autonomous_engineering.work_order.models import AcceptanceCriterion


@pytest.fixture
def repo_fixture_path() -> Path:
    base = Path(__file__).parent.parent / "fixtures" / "sample_repo"
    assert base.exists()
    return base


def test_independent_validator_accepts_valid_patch(tmp_path: Path, repo_fixture_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")
    validator = IndependentValidator(store)

    valid_patch = (
        "diff --git a/src/calculator/math_utils.py b/src/calculator/math_utils.py\n"
        "--- a/src/calculator/math_utils.py\n"
        "+++ b/src/calculator/math_utils.py\n"
        "@@ -6,2 +6,4 @@\n"
        " def calculate_ratio(a: float, b: float) -> float:\n"
        "+    if b == 0:\n"
        "+        raise ValueError('Denominator cannot be zero')\n"
        "     return a / b\n"
    )

    art = store.put(
        content=valid_patch,
        artifact_type=ArtifactType.PATCH,
        work_order_id="wo-val-1",
        work_order_version=1,
        step_id="step-patch",
        producing_worker_id="worker-b65-0",
        producing_profile_hash="prof-1",
        capability_token_id="tok-1",
    )

    criteria = (
        AcceptanceCriterion(
            criterion_id="crit-unit",
            description="Run pytest tests/test_math_utils.py",
            validator_type="pytest",
            test_target="tests/test_math_utils.py",
            required=True,
        ),
    )

    verdict = validator.validate(art, criteria, repo_fixture_path)
    assert verdict.status == ValidationStatus.ACCEPTED
    assert all(c.passed for c in verdict.checks)


def test_independent_validator_rejects_flawed_patch(tmp_path: Path, repo_fixture_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")
    validator = IndependentValidator(store)

    flawed_patch = (
        "diff --git a/src/calculator/math_utils.py b/src/calculator/math_utils.py\n"
        "--- a/src/calculator/math_utils.py\n"
        "+++ b/src/calculator/math_utils.py\n"
        "@@ -6,2 +6,4 @@\n"
        " def calculate_ratio(a: float, b: float) -> float:\n"
        "+    if b == 0:\n"
        "+        return 0.0  # Incorrect logic, fails ValueError assertion!\n"
        "     return a / b\n"
    )

    art = store.put(
        content=flawed_patch,
        artifact_type=ArtifactType.PATCH,
        work_order_id="wo-val-2",
        work_order_version=1,
        step_id="step-patch",
        producing_worker_id="worker-faulty",
        producing_profile_hash="prof-faulty",
        capability_token_id="tok-2",
    )

    criteria = (
        AcceptanceCriterion(
            criterion_id="crit-unit",
            description="Run pytest tests/test_math_utils.py",
            validator_type="pytest",
            test_target="tests/test_math_utils.py",
            required=True,
        ),
    )

    verdict = validator.validate(art, criteria, repo_fixture_path)
    assert verdict.status == ValidationStatus.REJECTED
    assert any(not c.passed for c in verdict.checks)
