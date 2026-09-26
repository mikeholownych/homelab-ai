"""Contract tests for Bounded Repair Controller and Failure Classifier."""
from pathlib import Path
import pytest

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.core.types import ArtifactType, FailureClass, ValidationStatus
from autonomous_engineering.repair.controller import BoundedRepairController
from autonomous_engineering.validator.independent import CheckResult, ValidationVerdict
from autonomous_engineering.work_order.compiler import WorkOrderCompiler


def test_failure_classification_categories():
    controller = BoundedRepairController()

    # Syntax Error
    verdict_syntax = ValidationVerdict(
        verdict_id="vrd-1",
        work_order_id="wo-1",
        work_order_version=1,
        artifact_hash="hash-1",
        status=ValidationStatus.REJECTED,
        checks=(),
        diagnostic_logs="SyntaxError: invalid syntax in math_utils.py line 12",
    )
    c1 = controller.classify_failure(verdict_syntax)
    assert c1.failure_class == FailureClass.SYNTAX_OR_COMPILATION_ERROR

    # Assertion Error
    verdict_assertion = ValidationVerdict(
        verdict_id="vrd-2",
        work_order_id="wo-1",
        work_order_version=1,
        artifact_hash="hash-2",
        status=ValidationStatus.REJECTED,
        checks=(),
        diagnostic_logs="FAILED tests/test_math_utils.py - AssertionError: 0.0 != ValueError",
    )
    c2 = controller.classify_failure(verdict_assertion)
    assert c2.failure_class == FailureClass.ASSERTION_ERROR

    # Scope Violation
    verdict_scope = ValidationVerdict(
        verdict_id="vrd-3",
        work_order_id="wo-1",
        work_order_version=1,
        artifact_hash="hash-3",
        status=ValidationStatus.REJECTED,
        checks=(),
        diagnostic_logs="ScopeViolationError: path 'config/secret' outside authorized scope",
    )
    c3 = controller.classify_failure(verdict_scope)
    assert c3.failure_class == FailureClass.SCOPE_VIOLATION


def test_bounded_repair_synthesizes_work_order_and_enforces_budget(tmp_path: Path):
    store = ArtifactStore(tmp_path / "artifacts")
    controller = BoundedRepairController()
    compiler = WorkOrderCompiler()

    wo = compiler.compile(
        raw_text="Fix defect",
        source_channel="test",
        source_reference="ref-1",
        repository_id="homelab-ai",
        baseline_commit="1aa374a",
        max_retries=1,  # Budget = exactly 1 repair attempt
    )

    art = store.put(
        content="faulty patch",
        artifact_type=ArtifactType.PATCH,
        work_order_id=wo.work_order_id,
        work_order_version=1,
        step_id="step-patch",
        producing_worker_id="w-1",
        producing_profile_hash="p-1",
        capability_token_id="t-1",
    )

    verdict_fail = ValidationVerdict(
        verdict_id="vrd-f1",
        work_order_id=wo.work_order_id,
        work_order_version=1,
        artifact_hash=art.artifact_hash,
        status=ValidationStatus.REJECTED,
        checks=(),
        diagnostic_logs="AssertionError: expected ValueError",
    )

    # First repair attempt permitted
    repair_wo = controller.prepare_repair_work_order(wo, art, verdict_fail)
    assert repair_wo is not None
    assert repair_wo.version == 2
    assert "Bounded repair" in repair_wo.history[-1].change_reason

    # Second repair attempt: budget exhausted (max_retries=1)
    repair_wo_exhausted = controller.prepare_repair_work_order(repair_wo, art, verdict_fail)
    assert repair_wo_exhausted is None
