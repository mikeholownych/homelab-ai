"""Unit tests for Specialist Routing Contracts (Phase 13 Workstream C)."""

import pytest
from autonomous_engineering.heterogeneous.specialist_contracts import (
    LEAD_ENGINEERING_CONTRACT,
    SECURITY_GATEKEEPER_CONTRACT,
    SPECIALIST_REGISTRY,
    STRUCTURED_OUTPUT_CONTRACT,
    TEST_SPECIALIST_CONTRACT,
    SpecialistRoutingContract,
    TaskClass,
)


def test_test_specialist_admission_success():
    contract = TEST_SPECIALIST_CONTRACT
    is_valid, msg = contract.validate_task_admission(
        task_class=TaskClass.TEST_GENERATION,
        context_token_count=4096,
        tool_calls_requested=["run_pytest"],
    )
    assert is_valid is True
    assert "admitted" in msg.lower()


def test_test_specialist_rejection_authority_escalation():
    contract = TEST_SPECIALIST_CONTRACT
    is_valid, msg = contract.validate_task_admission(
        task_class=TaskClass.ARCHITECTURAL_PLANNING,
        context_token_count=4096,
        tool_calls_requested=["read_file"],
    )
    assert is_valid is False
    assert "Authority Boundary" in msg


def test_test_specialist_rejection_context_overflow():
    contract = TEST_SPECIALIST_CONTRACT
    is_valid, msg = contract.validate_task_admission(
        task_class=TaskClass.TEST_GENERATION,
        context_token_count=35000,  # Exceeds 32,768 cap
        tool_calls_requested=["run_pytest"],
    )
    assert is_valid is False
    assert "Context Overflow" in msg


def test_test_specialist_rejection_unauthorized_tool():
    contract = TEST_SPECIALIST_CONTRACT
    is_valid, msg = contract.validate_task_admission(
        task_class=TaskClass.TEST_GENERATION,
        context_token_count=4096,
        tool_calls_requested=["execute_shell_root"],
    )
    assert is_valid is False
    assert "exceeds permitted permissions" in msg


def test_structured_output_contract_admission():
    contract = STRUCTURED_OUTPUT_CONTRACT
    is_valid, msg = contract.validate_task_admission(
        task_class=TaskClass.STRUCTURED_OUTPUT,
        context_token_count=2048,
        tool_calls_requested=["validate_json_schema"],
    )
    assert is_valid is True


def test_lead_engineering_contract_broad_authority():
    contract = LEAD_ENGINEERING_CONTRACT
    assert contract.max_context_length == 65536
    is_valid, _ = contract.validate_task_admission(
        task_class=TaskClass.MULTI_FILE_IMPLEMENTATION,
        context_token_count=50000,
        tool_calls_requested=[],
    )
    assert is_valid is True
