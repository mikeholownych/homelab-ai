"""Deterministic tests for Phase 14 Item 01 Handoff Contract."""

import pytest

from autonomous_engineering.heterogeneous.containment import ExternalAuthorityBoundary
from autonomous_engineering.pipeline_rebalancing.handoff_contract import (
    InvestigationFinding,
    InvestigationHandoffEnvelope,
    InvestigationHandoffStatus,
    Item01HandoffValidator,
)


@pytest.fixture
def handoff_validator():
    return Item01HandoffValidator()


@pytest.fixture
def valid_envelope():
    env = InvestigationHandoffEnvelope(
        task_id="PROJ-API-01-01",
        invocation_id="inv-12345",
        worker_id="worker_2",
        model_name="cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
        model_revision="AWQ-4bit",
        repo_commit_sha="ca5385348321fba5a2f17f7f19f457bfe0d52eba",
        inspected_files=["src/engine.py"],
        inspected_symbols=["EngineService"],
        findings=[
            InvestigationFinding(
                file_path="src/engine.py",
                symbol="EngineService",
                finding_type="COMPONENT_BOUNDARY",
                description="Core state transition engine",
            )
        ],
        explicit_unknowns=[],
        detected_blockers=[],
        raw_content="### Architecture Findings\nFound EngineService in src/engine.py with isolation boundaries.",
    )
    env.seal()
    return env


def test_valid_handoff_accepted(handoff_validator, valid_envelope):
    res = handoff_validator.validate_handoff(
        envelope=valid_envelope,
        expected_repo_sha="ca5385348321fba5a2f17f7f19f457bfe0d52eba",
    )
    assert res.is_accepted is True
    assert res.status == InvestigationHandoffStatus.CLEAN
    assert res.sanitized_content is not None
    assert "BEGIN QUARANTINED INVESTIGATION HANDOFF" in res.sanitized_content
    assert res.evidence_digest != ""


def test_missing_envelope_rejected(handoff_validator):
    res = handoff_validator.validate_handoff(
        envelope=None,
        expected_repo_sha="ca5385348321fba5a2f17f7f19f457bfe0d52eba",
    )
    assert res.is_accepted is False
    assert res.status == InvestigationHandoffStatus.MALFORMED
    assert "Missing handoff envelope" in res.rejection_reason


def test_stale_repo_commit_rejected(handoff_validator, valid_envelope):
    # Expecting different git commit SHA
    res = handoff_validator.validate_handoff(
        envelope=valid_envelope,
        expected_repo_sha="different_commit_sha_1234567890",
    )
    assert res.is_accepted is False
    assert res.status == InvestigationHandoffStatus.STALE
    assert "Stale repo snapshot" in res.rejection_reason


def test_timeout_handled_fail_closed(handoff_validator):
    res = handoff_validator.validate_handoff(
        envelope=None,
        expected_repo_sha="ca5385348321fba5a2f17f7f19f457bfe0d52eba",
        timeout_occurred=True,
    )
    assert res.is_accepted is False
    assert res.status == InvestigationHandoffStatus.TIMED_OUT
    assert "timed out" in res.rejection_reason


def test_corrupted_digest_rejected(handoff_validator, valid_envelope):
    # Tamper with content after sealing
    valid_envelope.raw_content = "Tampered content after seal"
    res = handoff_validator.validate_handoff(
        envelope=valid_envelope,
        expected_repo_sha="ca5385348321fba5a2f17f7f19f457bfe0d52eba",
    )
    assert res.is_accepted is False
    assert res.status == InvestigationHandoffStatus.MALFORMED
    assert "digest mismatch" in res.rejection_reason
