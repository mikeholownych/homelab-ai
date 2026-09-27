"""Review models and typed handoff contracts."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from autonomous_engineering.core.crypto import content_hash


class ReviewDisposition(StrEnum):
    RECOMMEND_ACCEPT = "RECOMMEND_ACCEPT"
    RECOMMEND_REVISE = "RECOMMEND_REVISE"
    BLOCK = "BLOCK"


class FindingSeverity(StrEnum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"
    ADVISORY = "ADVISORY"


@dataclass(frozen=True)
class ReviewFinding:
    finding_id: str
    severity: FindingSeverity
    file_path: str
    line_number: int | None
    description: str
    suggested_action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "severity": str(self.severity),
            "file_path": self.file_path,
            "line_number": self.line_number,
            "description": self.description,
            "suggested_action": self.suggested_action,
        }


@dataclass(frozen=True)
class ReviewReport:
    report_id: str
    target_artifact_hash: str
    reviewer_worker_id: str
    disposition: ReviewDisposition
    findings: tuple[ReviewFinding, ...]
    summary: str
    is_advisory: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "target_artifact_hash": self.target_artifact_hash,
            "reviewer_worker_id": self.reviewer_worker_id,
            "disposition": str(self.disposition),
            "findings": [f.to_dict() for f in self.findings],
            "summary": self.summary,
            "is_advisory": self.is_advisory,
        }

    @property
    def report_hash(self) -> str:
        return content_hash(self.to_dict())
