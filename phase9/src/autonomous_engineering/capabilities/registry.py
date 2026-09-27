"""
Autonomous Engineering System - Phase 9
Workstream C: Model Capability and Qualification Registry

Tracks verified model capabilities and authoritative 5-tuple qualification records:
    Qualification Key = Profile Digest × Model Revision × Inference Config × Workload Class × Suite Version
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class QualificationStatus(str, Enum):
    QUALIFIED = "QUALIFIED"
    EXPERIMENTAL = "EXPERIMENTAL"
    DISQUALIFIED = "DISQUALIFIED"
    REVOKED = "REVOKED"


class ModelExecutionTier(str, Enum):
    PHYSICAL_HARDWARE = "PHYSICAL_HARDWARE"
    CALIBRATED_ADAPTER = "CALIBRATED_ADAPTER"
    SIMULATED_TEST_DOUBLE = "SIMULATED_TEST_DOUBLE"


class ModelCapabilityError(Exception):
    """Base exception for model capability and qualification errors."""


class UnqualifiedModelError(ModelCapabilityError):
    """Raised when an operation requests an unqualified or disqualified model."""


class QualificationExpiredError(ModelCapabilityError):
    """Raised when a qualification certificate has expired."""


@dataclass(frozen=True)
class QualificationKey:
    """
    Authoritative 5-tuple qualification key uniquely identifying a verified capability boundary.
    """
    profile_digest: str
    model_revision: str
    inference_config_digest: str
    workload_class: str
    qualification_suite_version: str

    def to_hash(self) -> str:
        data = {
            "profile_digest": self.profile_digest,
            "model_revision": self.model_revision,
            "inference_config_digest": self.inference_config_digest,
            "workload_class": self.workload_class,
            "qualification_suite_version": self.qualification_suite_version,
        }
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ModelCapabilityRecord:
    """
    Detailed hardware, backend, and benchmark measurements for a model deployment.
    """
    model_identifier: str
    model_revision: str
    quantization: str
    inference_backend: str
    backend_version: str
    execution_tier: ModelExecutionTier
    context_capacity: int
    output_capacity: int
    supports_tool_calling: bool
    supports_structured_output: bool
    supported_reasoning_controls: List[str]
    measured_tokens_per_sec: float
    measured_ttft_ms: float
    memory_footprint_bytes: int
    created_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(frozen=True)
class QualificationCertificate:
    """
    Evidence-backed qualification record binding a key to an outcome.
    """
    key: QualificationKey
    key_hash: str
    status: QualificationStatus
    evaluation_suite_run_id: str
    acceptance_rate: float
    average_repair_count: float
    passed_validation_suites: List[str]
    qualification_evidence_digest: str
    certified_at_utc: str
    valid_until_utc: Optional[str] = None
    disqualification_reason: Optional[str] = None


class ModelCapabilityRegistry:
    """
    Authoritative registry managing model capabilities and qualification records.
    Prevents unverified models from receiving execution dispatches.
    """

    def __init__(self) -> None:
        self._capabilities: Dict[str, ModelCapabilityRecord] = {}
        self._certificates: Dict[str, QualificationCertificate] = {}
        self._initialize_baseline_capabilities()

    def register_model_capability(self, capability: ModelCapabilityRecord) -> None:
        """Registers verified hardware and interface capability parameters for a model."""
        self._capabilities[capability.model_identifier] = capability

    def record_qualification(
        self,
        key: QualificationKey,
        status: QualificationStatus,
        evaluation_run_id: str,
        acceptance_rate: float,
        average_repair_count: float,
        passed_validation_suites: List[str],
        evidence_digest: str,
        valid_until_utc: Optional[str] = None,
        disqualification_reason: Optional[str] = None,
    ) -> QualificationCertificate:
        """
        Records an evidence-backed qualification evaluation.
        Preserves records for both successful and disqualified/unsuccessful candidates.
        """
        key_hash = key.to_hash()
        cert = QualificationCertificate(
            key=key,
            key_hash=key_hash,
            status=status,
            evaluation_suite_run_id=evaluation_run_id,
            acceptance_rate=acceptance_rate,
            average_repair_count=average_repair_count,
            passed_validation_suites=passed_validation_suites,
            qualification_evidence_digest=evidence_digest,
            certified_at_utc=datetime.now(timezone.utc).isoformat(),
            valid_until_utc=valid_until_utc,
            disqualification_reason=disqualification_reason,
        )
        self._certificates[key_hash] = cert
        return cert

    def is_qualified(
        self,
        key: QualificationKey,
        current_time_utc: Optional[str] = None,
    ) -> bool:
        """
        Verifies whether the exact 5-tuple qualification key is currently QUALIFIED.
        Fails closed on missing or expired certificates.
        """
        key_hash = key.to_hash()
        cert = self._certificates.get(key_hash)
        if not cert:
            return False

        if cert.status != QualificationStatus.QUALIFIED:
            return False

        if cert.valid_until_utc:
            now_iso = current_time_utc or datetime.now(timezone.utc).isoformat()
            if now_iso > cert.valid_until_utc:
                return False

        return True

    def get_qualification_certificate(self, key: QualificationKey) -> Optional[QualificationCertificate]:
        return self._certificates.get(key.to_hash())

    def get_model_capability(self, model_identifier: str) -> Optional[ModelCapabilityRecord]:
        return self._capabilities.get(model_identifier)

    def list_qualified_models_for_workload(
        self,
        profile_digest: str,
        workload_class: str,
        suite_version: str,
    ) -> List[str]:
        """
        Returns all model identifiers with active qualification for the specified profile and workload.
        """
        qualified_models: List[str] = []
        for cert in self._certificates.values():
            if (
                cert.key.profile_digest == profile_digest
                and cert.key.workload_class == workload_class
                and cert.key.qualification_suite_version == suite_version
                and cert.status == QualificationStatus.QUALIFIED
            ):
                # Match to capability record by revision
                for cap in self._capabilities.values():
                    if cap.model_revision == cert.key.model_revision:
                        if cap.model_identifier not in qualified_models:
                            qualified_models.append(cap.model_identifier)
        return qualified_models

    def revoke_qualification(self, key: QualificationKey, reason: str) -> None:
        """Explicitly revokes qualification for a previously approved configuration."""
        key_hash = key.to_hash()
        if key_hash in self._certificates:
            old = self._certificates[key_hash]
            self._certificates[key_hash] = QualificationCertificate(
                key=old.key,
                key_hash=old.key_hash,
                status=QualificationStatus.REVOKED,
                evaluation_suite_run_id=old.evaluation_suite_run_id,
                acceptance_rate=old.acceptance_rate,
                average_repair_count=old.average_repair_count,
                passed_validation_suites=old.passed_validation_suites,
                qualification_evidence_digest=old.qualification_evidence_digest,
                certified_at_utc=old.certified_at_utc,
                valid_until_utc=old.valid_until_utc,
                disqualification_reason=reason,
            )

    def _initialize_baseline_capabilities(self) -> None:
        """Registers the physical T5820 resident model and benchmarked profiles."""
        # 1. Physical Hardware resident Qwen3-Coder
        self.register_model_capability(
            ModelCapabilityRecord(
                model_identifier="engineering/b0",
                model_revision="qwen3-coder-30b-awq-v1",
                quantization="AWQ-4bit",
                inference_backend="vllm-xpu-tp1",
                backend_version="0.6.3+xpu",
                execution_tier=ModelExecutionTier.PHYSICAL_HARDWARE,
                context_capacity=65536,
                output_capacity=1024,
                supports_tool_calling=True,
                supports_structured_output=True,
                supported_reasoning_controls=["temperature", "top_p", "max_tokens"],
                measured_tokens_per_sec=38.4,
                measured_ttft_ms=310.0,
                memory_footprint_bytes=26306674688,  # ~24.5 GiB
            )
        )

        # 2. Calibrated Review Specialist (simulated adapter for orchestration contract testing)
        self.register_model_capability(
            ModelCapabilityRecord(
                model_identifier="reviewer/phi4-calibrated",
                model_revision="phi4-fp8-v1",
                quantization="FP8",
                inference_backend="vllm-calibrated-adapter",
                backend_version="0.6.3",
                execution_tier=ModelExecutionTier.CALIBRATED_ADAPTER,
                context_capacity=32768,
                output_capacity=1024,
                supports_tool_calling=True,
                supports_structured_output=True,
                supported_reasoning_controls=["temperature", "max_tokens"],
                measured_tokens_per_sec=42.1,
                measured_ttft_ms=180.0,
                memory_footprint_bytes=16320875724,  # ~15.2 GiB
            )
        )
