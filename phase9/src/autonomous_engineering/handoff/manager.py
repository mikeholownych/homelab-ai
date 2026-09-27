"""
Autonomous Engineering System - Phase 9
Workstream G: Typed Inter-Agent Cooperation

Manages typed, immutable evidence handoff packages between specialized agents.
Enforces strict separation of concerns, structural invariance, and prevents recursive delegation.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class PayloadType(str, Enum):
    INVESTIGATION_REPORT = "INVESTIGATION_REPORT"
    ARCHITECTURAL_PLAN = "ARCHITECTURAL_PLAN"
    IMPLEMENTATION_DIFF = "IMPLEMENTATION_DIFF"
    REVIEW_VERDICT = "REVIEW_VERDICT"
    TEST_RESULTS = "TEST_RESULTS"
    SECURITY_AUDIT = "SECURITY_AUDIT"


class PermittedDownstreamUse(str, Enum):
    PLANNING = "PLANNING"
    IMPLEMENTATION = "IMPLEMENTATION"
    REVIEW = "REVIEW"
    REPAIR = "REPAIR"
    VALIDATION = "VALIDATION"
    EXPORT = "EXPORT"


class HandoffError(Exception):
    """Base exception for inter-agent handoff errors."""


class HandoffValidationError(HandoffError):
    """Raised when an evidence package fails schema, digest, or integrity validation."""


class UnauthorizedHandoffUseError(HandoffError):
    """Raised when a downstream agent attempts an unpermitted use of a handoff package."""


class InvariantViolationError(HandoffError):
    """Raised when an agent attempts an illegal state modification (e.g. reviewer modifying code)."""


class RecursiveDelegationError(HandoffError):
    """Raised when agents attempt cyclic or unbounded recursive delegation chains."""


@dataclass(frozen=True)
class EvidencePackage:
    """
    Immutable, content-addressed package exchanged between specialized agents.
    """
    package_id: str
    producer_instance_id: str
    producer_profile_id: str
    consumer_profile_id: str
    work_order_id: str
    work_order_revision: int
    baseline_commit: str
    payload_type: PayloadType
    payload_content: Dict[str, Any]
    payload_digest: str
    schema_version: str
    permitted_uses: List[PermittedDownstreamUse]
    created_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def verify_digest(self) -> bool:
        canonical = json.dumps(self.payload_content, sort_keys=True, separators=(",", ":"))
        computed = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return computed == self.payload_digest


class InterAgentHandoffManager:
    """
    Governs handoff validation, delivery, and enforcement of structural boundaries.
    """

    def __init__(self, max_chain_depth: int = 5) -> None:
        self.max_chain_depth = max_chain_depth
        self._packages: Dict[str, EvidencePackage] = {}
        self._delegation_chains: Dict[str, List[str]] = {}

    def create_package(
        self,
        package_id: str,
        producer_instance_id: str,
        producer_profile_id: str,
        consumer_profile_id: str,
        work_order_id: str,
        work_order_revision: int,
        baseline_commit: str,
        payload_type: PayloadType,
        payload_content: Dict[str, Any],
        schema_version: str,
        permitted_uses: List[PermittedDownstreamUse],
    ) -> EvidencePackage:
        """
        Creates and stores an immutable, cryptographically verified EvidencePackage.
        Enforces structural invariants based on producer and payload type.
        """
        # Invariant 1: Reviewer cannot generate implementation diffs
        if "reviewer" in producer_profile_id and payload_type == PayloadType.IMPLEMENTATION_DIFF:
            raise InvariantViolationError(
                f"Reviewer profile '{producer_profile_id}' is prohibited from producing IMPLEMENTATION_DIFF"
            )

        # Invariant 2: Planning profile cannot grant execution authority
        if "architect" in producer_profile_id or "planning" in producer_profile_id:
            if "grant_authority" in payload_content or "authorized_mutation_paths" in payload_content:
                raise InvariantViolationError(
                    "Planning agent cannot expand or define repository mutation authority"
                )

        # Compute payload digest
        canonical = json.dumps(payload_content, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        # Track delegation chain depth to prevent recursive explosion
        chain_key = f"{work_order_id}@{work_order_revision}"
        current_chain = self._delegation_chains.get(chain_key, [])
        if len(current_chain) >= self.max_chain_depth:
            raise RecursiveDelegationError(
                f"Delegation chain depth ({len(current_chain)}) exceeded maximum ({self.max_chain_depth}) for {work_order_id}"
            )

        package = EvidencePackage(
            package_id=package_id,
            producer_instance_id=producer_instance_id,
            producer_profile_id=producer_profile_id,
            consumer_profile_id=consumer_profile_id,
            work_order_id=work_order_id,
            work_order_revision=work_order_revision,
            baseline_commit=baseline_commit,
            payload_type=payload_type,
            payload_content=payload_content,
            payload_digest=digest,
            schema_version=schema_version,
            permitted_uses=permitted_uses,
        )

        self._packages[package_id] = package
        current_chain.append(package_id)
        self._delegation_chains[chain_key] = current_chain

        return package

    def accept_package(
        self,
        package_id: str,
        consumer_profile_id: str,
        intended_use: PermittedDownstreamUse,
        expected_baseline_commit: str,
    ) -> EvidencePackage:
        """
        Validates an EvidencePackage before consumption by a downstream agent.
        Ensures digest matches, consumer is authorized, intended use is permitted,
        and repository baseline commit matches.
        """
        package = self._packages.get(package_id)
        if not package:
            raise HandoffValidationError(f"Evidence package {package_id} not found")

        # 1. Cryptographic payload integrity verification
        if not package.verify_digest():
            raise HandoffValidationError(
                f"Payload digest mismatch for package {package_id}. Content has been tampered."
            )

        # 2. Consumer profile authorization check
        if package.consumer_profile_id != consumer_profile_id and package.consumer_profile_id != "*":
            raise UnauthorizedHandoffUseError(
                f"Consumer '{consumer_profile_id}' not authorized for package {package_id} (intended for '{package.consumer_profile_id}')"
            )

        # 3. Permitted downstream use check
        if intended_use not in package.permitted_uses:
            raise UnauthorizedHandoffUseError(
                f"Intended use '{intended_use.value}' is not permitted for package {package_id}. Permitted: {[u.value for u in package.permitted_uses]}"
            )

        # 4. Baseline commit match check (stale context detection)
        if package.baseline_commit != expected_baseline_commit:
            raise HandoffValidationError(
                f"Baseline commit mismatch: package binds '{package.baseline_commit}', but current repo is '{expected_baseline_commit}'"
            )

        return package

    def get_package(self, package_id: str) -> Optional[EvidencePackage]:
        return self._packages.get(package_id)

    def get_handoff_trail(self, work_order_id: str, work_order_revision: int) -> List[EvidencePackage]:
        """Returns the chronological audit trail of handoff packages for a work order."""
        chain_key = f"{work_order_id}@{work_order_revision}"
        package_ids = self._delegation_chains.get(chain_key, [])
        return [self._packages[pid] for pid in package_ids if pid in self._packages]
