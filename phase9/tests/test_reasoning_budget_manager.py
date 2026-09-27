import pytest

from autonomous_engineering.classifier.classifier import (
    FailureConsequence,
    ReasoningComplexity,
    UncertaintyLevel,
    WorkloadRequirements,
)
from autonomous_engineering.reasoning.manager import (
    EscalationAction,
    EscalationDepthExceededError,
    FailureCause,
    ReasoningBudgetManager,
    ReasoningTier,
)


def test_initial_budget_allocation():
    mgr = ReasoningBudgetManager()

    # Critical workload gets Tier 3
    reqs_crit = WorkloadRequirements(
        workload_id="req-crit",
        version="1.0.0",
        task_class="architectural_planning",
        required_specializations=["systems-architect"],
        reasoning_complexity=ReasoningComplexity.CRITICAL,
        context_demand_tokens=32768,
        required_tools=["read_file"],
        expected_execution_cost=5.0,
        failure_consequence=FailureConsequence.HIGH,
        mandatory_validation_suites=["syntax_ast"],
        uncertainty_level=UncertaintyLevel.LOW,
        resource_constraints={},
    )
    b_crit = mgr.allocate_initial_budget(reqs_crit)
    assert b_crit.tier == ReasoningTier.TIER_3_SPECIALIST
    assert b_crit.max_tokens == 2048

    # Low workload gets Tier 1
    reqs_low = WorkloadRequirements(
        workload_id="req-low",
        version="1.0.0",
        task_class="investigation",
        required_specializations=["repo-investigator"],
        reasoning_complexity=ReasoningComplexity.LOW,
        context_demand_tokens=8192,
        required_tools=["read_file"],
        expected_execution_cost=1.0,
        failure_consequence=FailureConsequence.LOW,
        mandatory_validation_suites=["syntax_ast"],
        uncertainty_level=UncertaintyLevel.LOW,
        resource_constraints={},
    )
    b_low = mgr.allocate_initial_budget(reqs_low)
    assert b_low.tier == ReasoningTier.TIER_1_STANDARD
    assert b_low.max_tokens == 1024


def test_bounded_escalation_depth_enforced():
    mgr = ReasoningBudgetManager(max_escalation_depth=2)

    # Initial budget: Tier 1
    budget = mgr.allocate_initial_budget(
        WorkloadRequirements(
            workload_id="req-esc",
            version="1.0.0",
            task_class="defect_repair",
            required_specializations=["implementation-engineer"],
            reasoning_complexity=ReasoningComplexity.LOW,
            context_demand_tokens=8192,
            required_tools=["read_file", "write_file"],
            expected_execution_cost=1.0,
            failure_consequence=FailureConsequence.LOW,
            mandatory_validation_suites=["syntax_ast"],
            uncertainty_level=UncertaintyLevel.LOW,
            resource_constraints={},
        )
    )

    # Depth 1: Syntax error escalation
    rec1 = mgr.escalate(
        work_order_id="wo-esc-01",
        current_depth=0,
        failure_cause=FailureCause.SYNTAX_OR_LINT_ERROR,
        failure_details="SyntaxError at line 14",
        current_budget=budget,
    )
    assert rec1.escalation_depth == 1
    assert rec1.action_taken == EscalationAction.UPGRADE_REASONING_TIER
    assert rec1.new_reasoning_tier == ReasoningTier.TIER_2_DEEP

    # Depth 2: Validation test failure escalation
    rec2 = mgr.escalate(
        work_order_id="wo-esc-01",
        current_depth=1,
        failure_cause=FailureCause.VALIDATION_TEST_FAILURE,
        failure_details="AssertionError: expected 42 got 41",
        current_budget=rec1.allocated_budget,
    )
    assert rec2.escalation_depth == 2
    assert rec2.action_taken == EscalationAction.DISPATCH_SPECIALIST_REVIEW
    assert rec2.new_reasoning_tier == ReasoningTier.TIER_3_SPECIALIST

    # Depth 3: Attempting escalation beyond max_escalation_depth=2 raises EscalationDepthExceededError
    with pytest.raises(EscalationDepthExceededError):
        mgr.escalate(
            work_order_id="wo-esc-01",
            current_depth=2,
            failure_cause=FailureCause.VALIDATION_TEST_FAILURE,
            failure_details="Still failing",
            current_budget=rec2.allocated_budget,
        )


def test_scope_violations_are_not_escalatable():
    mgr = ReasoningBudgetManager()
    budget = mgr.allocate_initial_budget(
        WorkloadRequirements(
            workload_id="req-scope",
            version="1.0.0",
            task_class="defect_repair",
            required_specializations=["implementation-engineer"],
            reasoning_complexity=ReasoningComplexity.LOW,
            context_demand_tokens=8192,
            required_tools=["read_file", "write_file"],
            expected_execution_cost=1.0,
            failure_consequence=FailureConsequence.LOW,
            mandatory_validation_suites=["syntax_ast"],
            uncertainty_level=UncertaintyLevel.LOW,
            resource_constraints={},
        )
    )

    # Escalating on scope violation fails closed immediately
    rec = mgr.escalate(
        work_order_id="wo-scope-01",
        current_depth=0,
        failure_cause=FailureCause.SCOPE_VIOLATION,
        failure_details="Attempted write to /etc/shadow",
        current_budget=budget,
    )
    assert rec.action_taken == EscalationAction.FAIL_CLOSED_REJECT
