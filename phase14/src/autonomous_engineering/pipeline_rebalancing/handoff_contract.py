"""Item 01 Investigation Handoff Contract for Phase 14 Pipeline Rebalancing.

Defines the explicit, immutable data contract governing the transfer of
investigation findings from Worker 2 to Lead Worker 1:
- Non-authoritative, advisory status.
- Cryptographic provenance and repo snapshot pinning.
- Out-of-process quarantine and external threat scanning.
- Fail-closed handling for missing, malformed, stale, or rejected deliverables.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from typing import Any, Dict, List, Optional, Tuple

from autonomous_engineering.heterogeneous.containment import (
    ContainmentEnvelope,
    ContainmentStatus,
    ExternalAuthorityBoundary,
    ThreatVector,
)


class InvestigationHandoffStatus(str, Enum):
    CLEAN = "CLEAN"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"
    STALE = "STALE"
    MALFORMED = "MALFORMED"
    TIMED_OUT = "TIMED_OUT"


class HandoffValidationError(Exception):
    """Raised when an Item 01 handoff fails mandatory validation invariants."""
    pass


@dataclass(frozen=True)
class InvestigationFinding:
    file_path: str
    symbol: str
    finding_type: str
    description: str
    line_reference: Optional[str] = None
    confidence: float = 1.0


@dataclass
class InvestigationHandoffEnvelope:
    task_id: str
    invocation_id: str
    worker_id: str
    model_name: str
    model_revision: str
    repo_commit_sha: str
    inspected_files: List[str]
    inspected_symbols: List[str]
    findings: List[InvestigationFinding]
    explicit_unknowns: List[str]
    detected_blockers: List[str]
    raw_content: str
    sanitized_content: Optional[str] = None
    evidence_digest: str = ""
    status: InvestigationHandoffStatus = InvestigationHandoffStatus.CLEAN
    rejection_reason: Optional[str] = None
    is_accepted: bool = False
    created_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def compute_digest(self) -> str:
        """Computes deterministic SHA-256 digest over the handoff payload."""
        payload = {
            "task_id": self.task_id,
            "invocation_id": self.invocation_id,
            "worker_id": self.worker_id,
            "repo_commit_sha": self.repo_commit_sha,
            "raw_content": self.raw_content,
        }
        serialized = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def seal(self) -> None:
        """Computes and freezes the cryptographic evidence digest."""
        self.evidence_digest = self.compute_digest()


class Item01HandoffValidator:
    """Enforces the Item 01 handoff contract before downstream consumption."""

    def __init__(self, boundary: Optional[ExternalAuthorityBoundary] = None):
        self.boundary = boundary or ExternalAuthorityBoundary()

    def validate_handoff(
        self,
        envelope: Optional[InvestigationHandoffEnvelope],
        expected_repo_sha: str,
        timeout_occurred: bool = False,
    ) -> InvestigationHandoffEnvelope:
        """Validates envelope integrity, staleness, and security quarantine."""
        # 1. Missing / Timed out check
        if timeout_occurred:
            return InvestigationHandoffEnvelope(
                task_id="UNKNOWN",
                invocation_id="UNKNOWN",
                worker_id="worker_2",
                model_name="UNKNOWN",
                model_revision="UNKNOWN",
                repo_commit_sha=expected_repo_sha,
                inspected_files=[],
                inspected_symbols=[],
                findings=[],
                explicit_unknowns=[],
                detected_blockers=["Execution timed out"],
                raw_content="",
                status=InvestigationHandoffStatus.TIMED_OUT,
                rejection_reason="Worker 2 timed out during Item 01 investigation",
                is_accepted=False,
            )

        if envelope is None:
            return InvestigationHandoffEnvelope(
                task_id="UNKNOWN",
                invocation_id="UNKNOWN",
                worker_id="worker_2",
                model_name="UNKNOWN",
                model_revision="UNKNOWN",
                repo_commit_sha=expected_repo_sha,
                inspected_files=[],
                inspected_symbols=[],
                findings=[],
                explicit_unknowns=[],
                detected_blockers=["Missing envelope"],
                raw_content="",
                status=InvestigationHandoffStatus.MALFORMED,
                rejection_reason="Missing handoff envelope (null deliverable)",
                is_accepted=False,
            )

        # 2. Staleness check: Git SHA must match exactly
        if envelope.repo_commit_sha != expected_repo_sha:
            envelope.status = InvestigationHandoffStatus.STALE
            envelope.rejection_reason = (
                f"Stale repo snapshot: handoff has {envelope.repo_commit_sha[:8]}, "
                f"expected {expected_repo_sha[:8]}"
            )
            envelope.is_accepted = False
            return envelope

        # 3. Malformed check: Required fields
        if not envelope.raw_content or len(envelope.raw_content.strip()) < 20:
            envelope.status = InvestigationHandoffStatus.MALFORMED
            envelope.rejection_reason = "Deliverable content empty or truncated (< 20 chars)"
            envelope.is_accepted = False
            return envelope

        # Verify digest
        expected_digest = envelope.compute_digest()
        if envelope.evidence_digest and envelope.evidence_digest != expected_digest:
            envelope.status = InvestigationHandoffStatus.MALFORMED
            envelope.rejection_reason = "Cryptographic digest mismatch (corrupted handoff)"
            envelope.is_accepted = False
            return envelope
        envelope.evidence_digest = expected_digest

        # 4. External Authority Boundary Security Scanning
        quarantine_env: ContainmentEnvelope = self.boundary.inspect_and_quarantine(
            task_id=envelope.task_id,
            source_model=envelope.model_name,
            source_role="SPECIALIST_INVESTIGATOR",
            raw_output=envelope.raw_content,
            channel="item01_investigation_handoff",
        )

        if quarantine_env.status == ContainmentStatus.REJECTED:
            envelope.status = InvestigationHandoffStatus.REJECTED
            envelope.rejection_reason = f"Security boundary violation: {quarantine_env.quarantine_reason}"
            envelope.is_accepted = False
            envelope.sanitized_content = None
            return envelope

        # 5. Quarantine Wrapping & Sanitization
        envelope.sanitized_content = (
            f"<!-- BEGIN QUARANTINED INVESTIGATION HANDOFF [{envelope.task_id}] -->\n"
            f"# Verified Advisory Reconnaissance from {envelope.worker_id} ({envelope.model_name})\n"
            f"Repo SHA: {envelope.repo_commit_sha}\n"
            f"{envelope.raw_content.strip()}\n"
            f"<!-- END QUARANTINED INVESTIGATION HANDOFF [{envelope.task_id}] -->"
        )
        envelope.status = InvestigationHandoffStatus.CLEAN
        envelope.is_accepted = True
        return envelope
