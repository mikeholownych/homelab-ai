"""Specialist Routing Contracts and Profile Definitions for Phase 13 Heterogeneous Architecture.

Enforces strict authority boundaries, permitted task classes, context limits,
and fail-closed escalation rules for specialized agents.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class TaskClass(str, Enum):
    TEST_GENERATION = "TEST_GENERATION"
    STRUCTURED_OUTPUT = "STRUCTURED_OUTPUT"
    SECURITY_REVIEW = "SECURITY_REVIEW"
    ADVERSARIAL_SCOPE_CHECK = "ADVERSARIAL_SCOPE_CHECK"
    FOCUSED_BUG_FIX = "FOCUSED_BUG_FIX"
    REFACTORING = "REFACTORING"
    ARCHITECTURAL_PLANNING = "ARCHITECTURAL_PLANNING"
    MULTI_FILE_IMPLEMENTATION = "MULTI_FILE_IMPLEMENTATION"
    PROJECT_INTEGRATION = "PROJECT_INTEGRATION"


class ModelRole(str, Enum):
    LEAD_ENGINEERING_AUTHORITY = "LEAD_ENGINEERING_AUTHORITY"
    BOUNDED_SPECIALIST = "BOUNDED_SPECIALIST"


@dataclass(frozen=True)
class SpecialistRoutingContract:
    profile_id: str
    target_model: str
    target_revision: str
    max_context_length: int
    permitted_task_classes: List[TaskClass]
    tool_permissions: List[str]
    output_schema: str
    independent_validator: str
    escalation_model: str
    retry_budget: int
    failure_disposition: str
    requires_external_acceptance: bool = True

    def validate_task_admission(self, task_class: TaskClass, context_token_count: int, tool_calls_requested: List[str]) -> tuple[bool, str]:
        """Validates whether a task is admitted to this specialist profile."""
        if task_class not in self.permitted_task_classes:
            return False, f"Task class {task_class} is not permitted for specialist {self.profile_id} (Authority Boundary)"

        if context_token_count > self.max_context_length:
            return False, f"Context length {context_token_count} exceeds specialist ceiling {self.max_context_length} (Context Overflow)"

        for tool in tool_calls_requested:
            if tool not in self.tool_permissions:
                return False, f"Requested tool '{tool}' exceeds permitted permissions for {self.profile_id}"

        return True, "Task admitted to specialist"


# Authoritative Immutable Specialist Contracts
TEST_SPECIALIST_CONTRACT = SpecialistRoutingContract(
    profile_id="specialist-test-engineer-v1",
    target_model="Qwen/Qwen2.5-7B-Instruct-AWQ",
    target_revision="b25037543e9394b818fdfca67ab2a00ecc7dd641",
    max_context_length=32768,
    permitted_task_classes=[TaskClass.TEST_GENERATION],
    tool_permissions=["read_file", "run_pytest", "inspect_ast"],
    output_schema="pytest_test_suite",
    independent_validator="pytest_coverage_validator",
    escalation_model="cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
    retry_budget=2,
    failure_disposition="ESCALATE_TO_LEAD",
    requires_external_acceptance=True,
)

STRUCTURED_OUTPUT_CONTRACT = SpecialistRoutingContract(
    profile_id="specialist-structured-output-v1",
    target_model="Qwen/Qwen2.5-7B-Instruct-AWQ",
    target_revision="b25037543e9394b818fdfca67ab2a00ecc7dd641",
    max_context_length=32768,
    permitted_task_classes=[TaskClass.STRUCTURED_OUTPUT],
    tool_permissions=["validate_json_schema", "format_openapi"],
    output_schema="strict_json_or_openapi",
    independent_validator="json_schema_validator",
    escalation_model="cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
    retry_budget=1,
    failure_disposition="ESCALATE_TO_LEAD",
    requires_external_acceptance=True,
)

SECURITY_GATEKEEPER_CONTRACT = SpecialistRoutingContract(
    profile_id="specialist-security-gatekeeper-v1",
    target_model="Qwen/Qwen2.5-7B-Instruct-AWQ",
    target_revision="b25037543e9394b818fdfca67ab2a00ecc7dd641",
    max_context_length=32768,
    permitted_task_classes=[TaskClass.SECURITY_REVIEW, TaskClass.ADVERSARIAL_SCOPE_CHECK],
    tool_permissions=["run_sast_rules", "inspect_scope_boundaries"],
    output_schema="structured_security_findings",
    independent_validator="sast_rule_verifier",
    escalation_model="cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
    retry_budget=1,
    failure_disposition="FAIL_CLOSED_REJECT",
    requires_external_acceptance=True,
)

LEAD_ENGINEERING_CONTRACT = SpecialistRoutingContract(
    profile_id="lead-engineering-authority-v1",
    target_model="cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
    target_revision="4bd30395b72ea6045edd04806c4fea448d4467b3",
    max_context_length=65536,
    permitted_task_classes=[
        TaskClass.ARCHITECTURAL_PLANNING,
        TaskClass.MULTI_FILE_IMPLEMENTATION,
        TaskClass.PROJECT_INTEGRATION,
        TaskClass.FOCUSED_BUG_FIX,
        TaskClass.REFACTORING,
        TaskClass.TEST_GENERATION,
        TaskClass.STRUCTURED_OUTPUT,
        TaskClass.SECURITY_REVIEW,
        TaskClass.ADVERSARIAL_SCOPE_CHECK,
    ],
    tool_permissions=["all"],
    output_schema="full_engineering_deliverable",
    independent_validator="multi_stage_integration_validator",
    escalation_model="HUMAN_SUPERVISOR",
    retry_budget=3,
    failure_disposition="HUMAN_INTERVENTION_REQUIRED",
    requires_external_acceptance=True,
)

SPECIALIST_REGISTRY = {
    "specialist-test-engineer-v1": TEST_SPECIALIST_CONTRACT,
    "specialist-structured-output-v1": STRUCTURED_OUTPUT_CONTRACT,
    "specialist-security-gatekeeper-v1": SECURITY_GATEKEEPER_CONTRACT,
    "lead-engineering-authority-v1": LEAD_ENGINEERING_CONTRACT,
}
