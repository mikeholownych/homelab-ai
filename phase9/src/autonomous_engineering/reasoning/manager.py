"""
Autonomous Engineering System - Phase 9
Workstream F: Adaptive Reasoning Allocation

Manages capability-based reasoning tiers and bounded evidence-driven escalations.
Enforces maximum escalation depth and strictly preserves repository authority.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from autonomous_engineering.classifier.classifier import (
    FailureConsequence,
    ReasoningComplexity,
    WorkloadRequirements,
)


class ReasoningTier(str, Enum):
    TIER_1_STANDARD = "TIER_1_STANDARD"
    TIER_2_DEEP = "TIER_2_DEEP"
    TIER_3_SPECIALIST = "TIER_3_SPECIALIST"


class FailureCause(str, Enum):
    SCHEMA_VIOLATION = "SCHEMA_VIOLATION"
    SYNTAX_OR_LINT_ERROR = "SYNTAX_OR_LINT_ERROR"
    VALIDATION_TEST_FAILURE = "VALIDATION_TEST_FAILURE"
    MISSING_CONTEXT = "MISSING_CONTEXT"
    SCOPE_VIOLATION = "SCOPE_VIOLATION"
    INFRASTRUCTURE_TIMEOUT = "INFRASTRUCTURE_TIMEOUT"


class EscalationAction(str, Enum):
    EXPAND_CONTEXT = "EXPAND_CONTEXT"
    UPGRADE_REASONING_TIER = "UPGRADE_REASONING_TIER"
    DISPATCH_SPECIALIST_REVIEW = "DISPATCH_SPECIALIST_REVIEW"
    TASK_DECOMPOSITION = "TASK_DECOMPOSITION"
    FAIL_CLOSED_REJECT = "FAIL_CLOSED_REJECT"
    HUMAN_ESCALATION = "HUMAN_ESCALATION"


class ReasoningEscalationError(Exception):
    """Raised when reasoning escalation exceeds bounds or violates safety policies."""


class EscalationDepthExceededError(ReasoningEscalationError):
    """Raised when escalation attempts exceed max_escalation_depth."""


@dataclass(frozen=True)
class ReasoningBudget:
    """
    Allocated token and step budgets for an agent execution turn.
    """
    tier: ReasoningTier
    max_tokens: int
    temperature: float
    max_execution_steps: int
    max_repair_attempts: int
    enable_ast_callgraph_retrieval: bool
    enable_chain_of_thought_prompt: bool


@dataclass(frozen=True)
class EscalationRecord:
    """
    Evidence-backed audit trail of an escalation event.
    """
    escalation_id: str
    work_order_id: str
    escalation_depth: int
    failure_cause: FailureCause
    failure_details: str
    action_taken: EscalationAction
    new_reasoning_tier: ReasoningTier
    allocated_budget: ReasoningBudget
    escalated_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ReasoningBudgetManager:
    """
    Allocates and dynamically escalates reasoning budgets based on concrete failure evidence.
    Enforces maximum escalation depth (default 2) and preserves hard authority constraints.
    """

    def __init__(self, max_escalation_depth: int = 2) -> None:
        self.max_escalation_depth = max_escalation_depth
        self._history: Dict[str, List[EscalationRecord]] = {}

    def allocate_initial_budget(
        self,
        requirements: WorkloadRequirements,
    ) -> ReasoningBudget:
        """
        Allocates the baseline reasoning budget based on classified workload requirements.
        """
        complexity = requirements.reasoning_complexity
        consequence = requirements.failure_consequence

        if complexity == ReasoningComplexity.CRITICAL or consequence == FailureConsequence.IRREVERSIBLE:
            return ReasoningBudget(
                tier=ReasoningTier.TIER_3_SPECIALIST,
                max_tokens=2048,
                temperature=0.0,
                max_execution_steps=15,
                max_repair_attempts=3,
                enable_ast_callgraph_retrieval=True,
                enable_chain_of_thought_prompt=True,
            )
        elif complexity == ReasoningComplexity.HIGH or consequence == FailureConsequence.HIGH:
            return ReasoningBudget(
                tier=ReasoningTier.TIER_2_DEEP,
                max_tokens=1536,
                temperature=0.1,
                max_execution_steps=10,
                max_repair_attempts=2,
                enable_ast_callgraph_retrieval=True,
                enable_chain_of_thought_prompt=True,
            )
        else:
            return ReasoningBudget(
                tier=ReasoningTier.TIER_1_STANDARD,
                max_tokens=1024,
                temperature=0.2,
                max_execution_steps=5,
                max_repair_attempts=1,
                enable_ast_callgraph_retrieval=False,
                enable_chain_of_thought_prompt=False,
            )

    def escalate(
        self,
        work_order_id: str,
        current_depth: int,
        failure_cause: FailureCause,
        failure_details: str,
        current_budget: ReasoningBudget,
    ) -> EscalationRecord:
        """
        Evaluates failure cause and escalates reasoning or dispatches specialist review.
        Fails closed with EscalationDepthExceededError if depth exceeds maximum.
        Scope violations cannot be escalated and trigger immediate rejection.
        """
        # Hard Rule 1: Scope violations are never escalatable; fail closed immediately
        if failure_cause == FailureCause.SCOPE_VIOLATION:
            record = EscalationRecord(
                escalation_id=f"esc-{work_order_id}-{current_depth + 1}",
                work_order_id=work_order_id,
                escalation_depth=current_depth + 1,
                failure_cause=failure_cause,
                failure_details=failure_details,
                action_taken=EscalationAction.FAIL_CLOSED_REJECT,
                new_reasoning_tier=current_budget.tier,
                allocated_budget=current_budget,
            )
            self._record_history(work_order_id, record)
            return record

        # Hard Rule 2: Enforce max escalation depth
        if current_depth >= self.max_escalation_depth:
            record = EscalationRecord(
                escalation_id=f"esc-{work_order_id}-{current_depth + 1}",
                work_order_id=work_order_id,
                escalation_depth=current_depth + 1,
                failure_cause=failure_cause,
                failure_details=f"Max escalation depth ({self.max_escalation_depth}) reached. {failure_details}",
                action_taken=EscalationAction.HUMAN_ESCALATION,
                new_reasoning_tier=current_budget.tier,
                allocated_budget=current_budget,
            )
            self._record_history(work_order_id, record)
            raise EscalationDepthExceededError(
                f"Work order {work_order_id} exceeded maximum escalation depth ({self.max_escalation_depth})"
            )

        # Determine appropriate escalation action based on failure cause
        new_depth = current_depth + 1
        if failure_cause == FailureCause.MISSING_CONTEXT:
            action = EscalationAction.EXPAND_CONTEXT
            new_tier = current_budget.tier
            new_budget = ReasoningBudget(
                tier=new_tier,
                max_tokens=current_budget.max_tokens,
                temperature=current_budget.temperature,
                max_execution_steps=current_budget.max_execution_steps + 2,
                max_repair_attempts=current_budget.max_repair_attempts,
                enable_ast_callgraph_retrieval=True,
                enable_chain_of_thought_prompt=current_budget.enable_chain_of_thought_prompt,
            )
        elif failure_cause == FailureCause.SYNTAX_OR_LINT_ERROR:
            action = EscalationAction.UPGRADE_REASONING_TIER
            new_tier = (
                ReasoningTier.TIER_2_DEEP
                if current_budget.tier == ReasoningTier.TIER_1_STANDARD
                else ReasoningTier.TIER_3_SPECIALIST
            )
            new_budget = ReasoningBudget(
                tier=new_tier,
                max_tokens=min(2048, current_budget.max_tokens + 512),
                temperature=0.0,
                max_execution_steps=current_budget.max_execution_steps,
                max_repair_attempts=current_budget.max_repair_attempts + 1,
                enable_ast_callgraph_retrieval=True,
                enable_chain_of_thought_prompt=True,
            )
        elif failure_cause == FailureCause.VALIDATION_TEST_FAILURE:
            action = EscalationAction.DISPATCH_SPECIALIST_REVIEW
            new_tier = ReasoningTier.TIER_3_SPECIALIST
            new_budget = ReasoningBudget(
                tier=new_tier,
                max_tokens=2048,
                temperature=0.0,
                max_execution_steps=current_budget.max_execution_steps + 3,
                max_repair_attempts=current_budget.max_repair_attempts + 1,
                enable_ast_callgraph_retrieval=True,
                enable_chain_of_thought_prompt=True,
            )
        else:
            action = EscalationAction.UPGRADE_REASONING_TIER
            new_tier = ReasoningTier.TIER_2_DEEP
            new_budget = ReasoningBudget(
                tier=new_tier,
                max_tokens=1536,
                temperature=0.1,
                max_execution_steps=current_budget.max_execution_steps,
                max_repair_attempts=current_budget.max_repair_attempts,
                enable_ast_callgraph_retrieval=True,
                enable_chain_of_thought_prompt=True,
            )

        record = EscalationRecord(
            escalation_id=f"esc-{work_order_id}-{new_depth}",
            work_order_id=work_order_id,
            escalation_depth=new_depth,
            failure_cause=failure_cause,
            failure_details=failure_details,
            action_taken=action,
            new_reasoning_tier=new_tier,
            allocated_budget=new_budget,
        )
        self._record_history(work_order_id, record)
        return record

    def get_escalation_history(self, work_order_id: str) -> List[EscalationRecord]:
        return list(self._history.get(work_order_id, []))

    def _record_history(self, work_order_id: str, record: EscalationRecord) -> None:
        if work_order_id not in self._history:
            self._history[work_order_id] = []
        self._history[work_order_id].append(record)
