from datetime import datetime, timedelta, timezone
import pytest

from autonomous_engineering.capabilities.registry import (
    ModelCapabilityRecord,
    ModelCapabilityRegistry,
    ModelExecutionTier,
    QualificationKey,
    QualificationStatus,
)


def test_baseline_capabilities_registered():
    registry = ModelCapabilityRegistry()
    b0 = registry.get_model_capability("engineering/b0")
    assert b0 is not None
    assert b0.model_revision == "qwen3-coder-30b-awq-v1"
    assert b0.execution_tier == ModelExecutionTier.PHYSICAL_HARDWARE
    assert b0.context_capacity == 65536
    assert b0.supports_tool_calling is True

    phi4 = registry.get_model_capability("reviewer/phi4-calibrated")
    assert phi4 is not None
    assert phi4.execution_tier == ModelExecutionTier.CALIBRATED_ADAPTER


def test_qualification_key_and_certificate_lifecycle():
    registry = ModelCapabilityRegistry()

    key = QualificationKey(
        profile_digest="abc123profiledigest",
        model_revision="qwen3-coder-30b-awq-v1",
        inference_config_digest="cfg456awq",
        workload_class="defect_repair",
        qualification_suite_version="v1",
    )

    # Not qualified initially
    assert registry.is_qualified(key) is False

    # Record successful qualification
    cert = registry.record_qualification(
        key=key,
        status=QualificationStatus.QUALIFIED,
        evaluation_run_id="run-001",
        acceptance_rate=0.95,
        average_repair_count=0.4,
        passed_validation_suites=["syntax_ast", "sandbox_test_suite"],
        evidence_digest="evidence-hash-789",
    )
    assert cert.status == QualificationStatus.QUALIFIED
    assert registry.is_qualified(key) is True

    # Revoke qualification
    registry.revoke_qualification(key, "Observed regression on regression test suite")
    assert registry.is_qualified(key) is False


def test_qualification_expiration():
    registry = ModelCapabilityRegistry()

    key = QualificationKey(
        profile_digest="prof-digest-expire",
        model_revision="qwen3-coder-30b-awq-v1",
        inference_config_digest="cfg456awq",
        workload_class="defect_repair",
        qualification_suite_version="v1",
    )

    # Valid until 10 minutes ago
    past_iso = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    registry.record_qualification(
        key=key,
        status=QualificationStatus.QUALIFIED,
        evaluation_run_id="run-expired",
        acceptance_rate=1.0,
        average_repair_count=0.0,
        passed_validation_suites=["syntax_ast"],
        evidence_digest="evidence-hash-expire",
        valid_until_utc=past_iso,
    )

    # Fails closed on expiration
    assert registry.is_qualified(key) is False
