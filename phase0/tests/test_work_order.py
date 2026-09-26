"""Contract tests for Work-Order Compilation, Models, and Revision Invalidation."""
import pytest
from autonomous_engineering.core.types import AmbiguityStatus, WorkOrderState
from autonomous_engineering.work_order.compiler import WorkOrderCompiler, CompilationError
from autonomous_engineering.work_order.models import (
    AcceptanceCriterion,
    Ambiguity,
    Authorization,
    WorkOrder,
)
from autonomous_engineering.work_order.versioning import WorkOrderRevisionManager


def test_work_order_compilation_preserves_intent():
    compiler = WorkOrderCompiler()
    raw = "Fix zero division error in calculate_ratio when denominator is 0"
    wo = compiler.compile(
        raw_text=raw,
        source_channel="cli_adapter",
        source_reference="cli-session-001",
        repository_id="homelab-ai",
        baseline_commit="1aa374a",
        proposed_mutation_paths=["src/calculator/math_utils.py"],
    )

    assert wo.work_order_id.startswith("wo-")
    assert wo.version == 1
    assert wo.predecessor_hash is None
    assert wo.source_instruction.raw_text == raw
    assert wo.intent.normalized_objective == raw
    assert wo.intent.target_repo.repository_id == "homelab-ai"
    assert wo.intent.target_repo.baseline_commit == "1aa374a"
    assert "src/calculator/math_utils.py" in wo.authorization.authorized_mutation_paths
    assert wo.state.current_stage == WorkOrderState.DRAFT
    assert len(wo.contract_hash) == 64


def test_ambiguity_detection_and_preservation():
    compiler = WorkOrderCompiler()
    raw = "Fix ratio calculation either by returning zero or by raising an error"
    wo = compiler.compile(
        raw_text=raw,
        source_channel="cli_adapter",
        source_reference="cli-session-002",
        repository_id="homelab-ai",
        baseline_commit="1aa374a",
    )

    # Invariant: Ambiguity surfaced and marks state AMBIGUOUS
    assert wo.is_ambiguous() is True
    assert wo.state.current_stage == WorkOrderState.AMBIGUOUS
    assert len(wo.ambiguities) >= 1
    assert wo.ambiguities[0].status == AmbiguityStatus.UNRESOLVED


def test_empty_instruction_fails_closed():
    compiler = WorkOrderCompiler()
    with pytest.raises(CompilationError, match="cannot be empty"):
        compiler.compile(
            raw_text="   ",
            source_channel="cli",
            source_reference="ref-1",
            repository_id="repo",
            baseline_commit="commit",
        )


def test_work_order_revision_and_invalidation():
    compiler = WorkOrderCompiler()
    v1 = compiler.compile(
        raw_text="Fix calculate_ratio bug",
        source_channel="cli",
        source_reference="ref-1",
        repository_id="homelab-ai",
        baseline_commit="1aa374a",
        proposed_mutation_paths=["src/calculator/math_utils.py"],
    )

    # Create revision expanding scope
    v2 = WorkOrderRevisionManager.create_revision(
        current_wo=v1,
        change_reason="Scope expansion to config file",
        author="human_operator",
        updated_paths=["src/calculator/math_utils.py", "config/settings.json"],
    )

    assert v2.version == 2
    assert v2.predecessor_hash == v1.contract_hash
    assert v2.state.fencing_token == v1.state.fencing_token + 1
    assert len(v2.history) == 2

    # Invalidation impact evaluation
    impact = WorkOrderRevisionManager.evaluate_invalidation(v1, v2)
    assert impact["scope_expanded"] is True
    assert impact["requires_reauthorization"] is True
    assert impact["all_active_assignments_stale"] is True


def test_three_canonical_examples():
    compiler = WorkOrderCompiler()

    # Example 1: Simple Defect Repair
    ex1 = compiler.compile(
        raw_text="Fix ZeroDivisionError in calculate_ratio",
        source_channel="opencode",
        source_reference="opencode-1",
        repository_id="homelab-ai",
        baseline_commit="1aa374a",
        proposed_mutation_paths=["src/calculator/math_utils.py"],
        acceptance_criteria=[
            AcceptanceCriterion(
                criterion_id="crit-unit",
                description="Run pytest tests/test_math_utils.py",
                validator_type="pytest",
                test_target="tests/test_math_utils.py",
                required=True,
            )
        ],
    )
    assert len(ex1.authorization.authorized_mutation_paths) == 1
    assert ex1.budget.max_retries == 3

    # Example 2: Multi-File Implementation
    ex2 = compiler.compile(
        raw_text="Implement format_ratio and integrate with calculator core",
        source_channel="harness",
        source_reference="harness-step-4",
        repository_id="homelab-ai",
        baseline_commit="1aa374a",
        proposed_mutation_paths=[
            "src/calculator/math_utils.py",
            "src/calculator/formatter.py",
            "tests/test_calculator.py",
        ],
    )
    assert len(ex2.authorization.authorized_mutation_paths) == 3

    # Example 3: Revised Work Order with Scope Invalidation
    ex3_v1 = compiler.compile(
        raw_text="Modify math utils",
        source_channel="cli",
        source_reference="cli-ex3",
        repository_id="homelab-ai",
        baseline_commit="1aa374a",
        proposed_mutation_paths=["src/calculator/math_utils.py"],
    )
    ex3_v2 = WorkOrderRevisionManager.create_revision(
        current_wo=ex3_v1,
        change_reason="Touch database migration",
        author="human_operator",
        updated_paths=["src/calculator/math_utils.py", "db/migrations/001.py"],
    )
    impact = WorkOrderRevisionManager.evaluate_invalidation(ex3_v1, ex3_v2)
    assert impact["scope_expanded"] is True
    assert impact["requires_reauthorization"] is True
