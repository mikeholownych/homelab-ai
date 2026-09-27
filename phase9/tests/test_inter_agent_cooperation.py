import pytest

from autonomous_engineering.handoff.manager import (
    EvidencePackage,
    HandoffValidationError,
    InterAgentHandoffManager,
    InvariantViolationError,
    PayloadType,
    PermittedDownstreamUse,
    RecursiveDelegationError,
    UnauthorizedHandoffUseError,
)


def test_package_creation_and_digest_verification():
    mgr = InterAgentHandoffManager()

    pkg = mgr.create_package(
        package_id="pkg-001",
        producer_instance_id="inst-inv-01",
        producer_profile_id="repo-investigator",
        consumer_profile_id="implementation-engineer",
        work_order_id="wo-100",
        work_order_revision=1,
        baseline_commit="commit-100",
        payload_type=PayloadType.INVESTIGATION_REPORT,
        payload_content={"symbols": ["add", "subtract"]},
        schema_version="1.0.0",
        permitted_uses=[PermittedDownstreamUse.IMPLEMENTATION],
    )

    assert pkg.verify_digest() is True

    # Consuming agent validates package
    accepted = mgr.accept_package(
        package_id="pkg-001",
        consumer_profile_id="implementation-engineer",
        intended_use=PermittedDownstreamUse.IMPLEMENTATION,
        expected_baseline_commit="commit-100",
    )
    assert accepted.package_id == "pkg-001"


def test_reviewer_prohibited_from_producing_code_diff():
    mgr = InterAgentHandoffManager()

    with pytest.raises(InvariantViolationError):
        mgr.create_package(
            package_id="pkg-bad-diff",
            producer_instance_id="inst-rev-01",
            producer_profile_id="security-reviewer",
            consumer_profile_id="implementation-engineer",
            work_order_id="wo-101",
            work_order_revision=1,
            baseline_commit="commit-101",
            payload_type=PayloadType.IMPLEMENTATION_DIFF,
            payload_content={"diff": "+ bad code"},
            schema_version="1.0.0",
            permitted_uses=[PermittedDownstreamUse.VALIDATION],
        )


def test_stale_baseline_commit_rejected_on_handoff():
    mgr = InterAgentHandoffManager()

    pkg = mgr.create_package(
        package_id="pkg-002",
        producer_instance_id="inst-inv-02",
        producer_profile_id="repo-investigator",
        consumer_profile_id="implementation-engineer",
        work_order_id="wo-102",
        work_order_revision=1,
        baseline_commit="commit-old",
        payload_type=PayloadType.INVESTIGATION_REPORT,
        payload_content={"findings": "ok"},
        schema_version="1.0.0",
        permitted_uses=[PermittedDownstreamUse.IMPLEMENTATION],
    )

    # Repository was updated to "commit-new"; handoff must reject stale context
    with pytest.raises(HandoffValidationError):
        mgr.accept_package(
            package_id="pkg-002",
            consumer_profile_id="implementation-engineer",
            intended_use=PermittedDownstreamUse.IMPLEMENTATION,
            expected_baseline_commit="commit-new",
        )


def test_recursive_delegation_chain_depth_capping():
    mgr = InterAgentHandoffManager(max_chain_depth=3)

    # Create 3 packages in chain
    for i in range(3):
        mgr.create_package(
            package_id=f"pkg-chain-{i}",
            producer_instance_id=f"inst-{i}",
            producer_profile_id="repo-investigator",
            consumer_profile_id="implementation-engineer",
            work_order_id="wo-chain",
            work_order_revision=1,
            baseline_commit="commit-fixed",
            payload_type=PayloadType.INVESTIGATION_REPORT,
            payload_content={"step": i},
            schema_version="1.0.0",
            permitted_uses=[PermittedDownstreamUse.IMPLEMENTATION],
        )

    # 4th package exceeds max_chain_depth=3
    with pytest.raises(RecursiveDelegationError):
        mgr.create_package(
            package_id="pkg-chain-4",
            producer_instance_id="inst-4",
            producer_profile_id="repo-investigator",
            consumer_profile_id="implementation-engineer",
            work_order_id="wo-chain",
            work_order_revision=1,
            baseline_commit="commit-fixed",
            payload_type=PayloadType.INVESTIGATION_REPORT,
            payload_content={"step": 4},
            schema_version="1.0.0",
            permitted_uses=[PermittedDownstreamUse.IMPLEMENTATION],
        )
