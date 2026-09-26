"""Contract tests for Authority, Admission Evaluator, and ScopeGuard."""
from datetime import datetime, timezone
import pytest

from autonomous_engineering.authority.admission import AdmissionEvaluator
from autonomous_engineering.authority.guard import ScopeGuard, ScopeViolationError
from autonomous_engineering.authority.tokens import CapabilityToken
from autonomous_engineering.core.types import FailureClass, WorkOrderState
from autonomous_engineering.work_order.compiler import WorkOrderCompiler
from autonomous_engineering.work_order.models import Ambiguity, AmbiguityStatus


def test_admission_evaluator_admits_valid_work_order():
    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Fix calculate_ratio bug",
        source_channel="cli",
        source_reference="ref-1",
        repository_id="homelab-ai",
        baseline_commit="1aa374a",
        proposed_mutation_paths=["src/calculator/math_utils.py"],
    )

    evaluator = AdmissionEvaluator()
    decision = evaluator.evaluate(wo, human_approval_present=True)

    assert decision.admitted is True
    assert decision.token is not None
    assert decision.admitted_work_order is not None
    assert decision.admitted_work_order.state.current_stage == WorkOrderState.ADMITTED
    assert decision.token.work_order_id == wo.work_order_id
    assert decision.token.is_valid() is True


def test_admission_fails_closed_on_unresolved_ambiguity():
    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Fix calculate_ratio either by returning 0 or raising error",
        source_channel="cli",
        source_reference="ref-2",
        repository_id="homelab-ai",
        baseline_commit="1aa374a",
    )

    evaluator = AdmissionEvaluator()
    decision = evaluator.evaluate(wo, human_approval_present=True)

    assert decision.admitted is False
    assert "unresolved material ambiguities" in decision.reason
    assert decision.token is None


def test_admission_fails_closed_without_human_approval():
    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Fix calculate_ratio bug",
        source_channel="cli",
        source_reference="ref-3",
        repository_id="homelab-ai",
        baseline_commit="1aa374a",
        proposed_mutation_paths=["src/calculator/math_utils.py"],
    )

    evaluator = AdmissionEvaluator()
    decision = evaluator.evaluate(wo, human_approval_present=False)

    assert decision.admitted is False
    assert "Missing required human approval" in decision.reason


def test_admission_fails_closed_on_expired_authority():
    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Fix calculate_ratio bug",
        source_channel="cli",
        source_reference="ref-4",
        repository_id="homelab-ai",
        baseline_commit="1aa374a",
        proposed_mutation_paths=["src/calculator/math_utils.py"],
        valid_until="2020-01-01T00:00:00Z",  # Expired in past
    )

    evaluator = AdmissionEvaluator()
    decision = evaluator.evaluate(wo, human_approval_present=True)

    assert decision.admitted is False
    assert "expired" in decision.reason.lower()


def test_scope_guard_enforces_mutation_path_whitelist():
    token = CapabilityToken(
        token_id="token-001",
        work_order_id="wo-001",
        work_order_version=1,
        task_id="step-1",
        authorized_paths=("src/calculator/*.py",),
        authorized_tools=("read_file", "write_patch"),
        max_retries=2,
        fencing_token=1,
        issued_at=datetime.now(timezone.utc).isoformat(),
        expires_at="2030-01-01T00:00:00Z",
    )

    # Valid mutation inside authorized paths
    ScopeGuard.check_mutation_path(token, "src/calculator/math_utils.py")

    # Unauthorized mutation outside authorized paths
    with pytest.raises(ScopeViolationError) as exc_info:
        ScopeGuard.check_mutation_path(token, "config/secrets.env")
    assert exc_info.value.failure_class == FailureClass.SCOPE_VIOLATION


def test_scope_guard_fails_closed_on_revoked_token():
    token = CapabilityToken(
        token_id="token-002",
        work_order_id="wo-002",
        work_order_version=1,
        task_id="step-1",
        authorized_paths=("src/**",),
        authorized_tools=("write_patch",),
        max_retries=1,
        fencing_token=1,
        issued_at=datetime.now(timezone.utc).isoformat(),
        expires_at="2030-01-01T00:00:00Z",
        revoked=True,
    )

    with pytest.raises(ScopeViolationError) as exc_info:
        ScopeGuard.check_mutation_path(token, "src/calculator/math_utils.py")
    assert exc_info.value.failure_class == FailureClass.CAPABILITY_EXPIRED_OR_REVOKED
