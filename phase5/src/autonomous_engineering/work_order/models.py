"""Canonical Work-Order Contract Models and Data Structures."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid

from autonomous_engineering.core.crypto import canonical_json, content_hash, sha256_digest
from autonomous_engineering.core.types import (
    AmbiguityStatus,
    WorkOrderState,
)


@dataclass(frozen=True)
class SourceInstruction:
    raw_text: str
    source_channel: str
    source_reference: str
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not self.content_hash:
            calculated = sha256_digest(self.raw_text)
            object.__setattr__(self, "content_hash", calculated)


@dataclass(frozen=True)
class TargetRepo:
    repository_id: str
    baseline_commit: str


@dataclass(frozen=True)
class Intent:
    normalized_objective: str
    target_repo: TargetRepo


@dataclass(frozen=True)
class Ambiguity:
    ambiguity_id: str
    description: str
    status: AmbiguityStatus
    resolution: str | None = None


@dataclass(frozen=True)
class Authorization:
    authority_source: str
    policy_version: str
    valid_until: str  # ISO-8601 UTC
    revocation_status: bool = False
    authorized_mutation_paths: tuple[str, ...] = ()
    prohibited_operations: tuple[str, ...] = (
        "network_egress",
        "alter_git_history",
        "rm_root",
        "pip_install_unapproved",
    )


@dataclass(frozen=True)
class AcceptanceCriterion:
    criterion_id: str
    description: str
    validator_type: str  # e.g. "pytest", "linter", "custom_script"
    test_target: str
    required: bool = True


@dataclass(frozen=True)
class Acceptance:
    criteria: tuple[AcceptanceCriterion, ...]
    independent_validation_required: bool = True


@dataclass(frozen=True)
class Dependencies:
    permitted_parallelism: int = 1
    prerequisite_work_orders: tuple[str, ...] = ()


@dataclass(frozen=True)
class Budget:
    max_retries: int = 3
    max_wallclock_seconds: int = 600
    escalation_policy: str = "FAIL_CLOSED_ON_BUDGET_EXHAUSTED"


@dataclass(frozen=True)
class WorkOrderStateRecord:
    current_stage: WorkOrderState = WorkOrderState.DRAFT
    terminal_disposition: str | None = None
    fencing_token: int = 1


@dataclass(frozen=True)
class HistoryEntry:
    version: int
    timestamp: str
    change_reason: str
    author: str


@dataclass(frozen=True)
class WorkOrder:
    work_order_id: str
    version: int
    predecessor_hash: str | None
    created_at: str
    source_instruction: SourceInstruction
    intent: Intent
    ambiguities: tuple[Ambiguity, ...]
    authorization: Authorization
    acceptance: Acceptance
    dependencies: Dependencies
    budget: Budget
    state: WorkOrderStateRecord
    history: tuple[HistoryEntry, ...] = ()

    @property
    def contract_hash(self) -> str:
        """Deterministic cryptographic hash over the immutable contract payload."""
        payload = {
            "work_order_id": self.work_order_id,
            "version": self.version,
            "predecessor_hash": self.predecessor_hash,
            "created_at": self.created_at,
            "source_instruction": {
                "raw_text": self.source_instruction.raw_text,
                "source_channel": self.source_instruction.source_channel,
                "source_reference": self.source_instruction.source_reference,
                "content_hash": self.source_instruction.content_hash,
            },
            "intent": {
                "normalized_objective": self.intent.normalized_objective,
                "target_repo": {
                    "repository_id": self.intent.target_repo.repository_id,
                    "baseline_commit": self.intent.target_repo.baseline_commit,
                },
            },
            "ambiguities": [
                {
                    "ambiguity_id": a.ambiguity_id,
                    "description": a.description,
                    "status": str(a.status),
                    "resolution": a.resolution,
                }
                for a in self.ambiguities
            ],
            "authorization": {
                "authority_source": self.authorization.authority_source,
                "policy_version": self.authorization.policy_version,
                "valid_until": self.authorization.valid_until,
                "revocation_status": self.authorization.revocation_status,
                "authorized_mutation_paths": sorted(self.authorization.authorized_mutation_paths),
                "prohibited_operations": sorted(self.authorization.prohibited_operations),
            },
            "acceptance": {
                "criteria": [
                    {
                        "criterion_id": c.criterion_id,
                        "description": c.description,
                        "validator_type": c.validator_type,
                        "test_target": c.test_target,
                        "required": c.required,
                    }
                    for c in self.acceptance.criteria
                ],
                "independent_validation_required": self.acceptance.independent_validation_required,
            },
            "dependencies": {
                "permitted_parallelism": self.dependencies.permitted_parallelism,
                "prerequisite_work_orders": sorted(self.dependencies.prerequisite_work_orders),
            },
            "budget": {
                "max_retries": self.budget.max_retries,
                "max_wallclock_seconds": self.budget.max_wallclock_seconds,
                "escalation_policy": self.budget.escalation_policy,
            },
        }
        return content_hash(payload)

    def is_ambiguous(self) -> bool:
        """Check if any material ambiguity remains unresolved."""
        return any(a.status == AmbiguityStatus.UNRESOLVED for a in self.ambiguities)

    def to_dict(self) -> dict[str, Any]:
        """Convert work order to dictionary representation."""
        return {
            "work_order_id": self.work_order_id,
            "version": self.version,
            "predecessor_hash": self.predecessor_hash,
            "contract_hash": self.contract_hash,
            "created_at": self.created_at,
            "source_instruction": {
                "raw_text": self.source_instruction.raw_text,
                "source_channel": self.source_instruction.source_channel,
                "source_reference": self.source_instruction.source_reference,
                "content_hash": self.source_instruction.content_hash,
            },
            "intent": {
                "normalized_objective": self.intent.normalized_objective,
                "target_repo": {
                    "repository_id": self.intent.target_repo.repository_id,
                    "baseline_commit": self.intent.target_repo.baseline_commit,
                },
            },
            "ambiguities": [
                {
                    "ambiguity_id": a.ambiguity_id,
                    "description": a.description,
                    "status": str(a.status),
                    "resolution": a.resolution,
                }
                for a in self.ambiguities
            ],
            "authorization": {
                "authority_source": self.authorization.authority_source,
                "policy_version": self.authorization.policy_version,
                "valid_until": self.authorization.valid_until,
                "revocation_status": self.authorization.revocation_status,
                "authorized_mutation_paths": list(self.authorization.authorized_mutation_paths),
                "prohibited_operations": list(self.authorization.prohibited_operations),
            },
            "acceptance": {
                "criteria": [
                    {
                        "criterion_id": c.criterion_id,
                        "description": c.description,
                        "validator_type": c.validator_type,
                        "test_target": c.test_target,
                        "required": c.required,
                    }
                    for c in self.acceptance.criteria
                ],
                "independent_validation_required": self.acceptance.independent_validation_required,
            },
            "dependencies": {
                "permitted_parallelism": self.dependencies.permitted_parallelism,
                "prerequisite_work_orders": list(self.dependencies.prerequisite_work_orders),
            },
            "budget": {
                "max_retries": self.budget.max_retries,
                "max_wallclock_seconds": self.budget.max_wallclock_seconds,
                "escalation_policy": self.budget.escalation_policy,
            },
            "state": {
                "current_stage": str(self.state.current_stage),
                "terminal_disposition": self.state.terminal_disposition,
                "fencing_token": self.state.fencing_token,
            },
            "history": [
                {
                    "version": h.version,
                    "timestamp": h.timestamp,
                    "change_reason": h.change_reason,
                    "author": h.author,
                }
                for h in self.history
            ],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WorkOrder:
        si = d["source_instruction"]
        source_inst = SourceInstruction(
            raw_text=si["raw_text"],
            source_channel=si["source_channel"],
            source_reference=si["source_reference"],
            content_hash=si.get("content_hash", ""),
        )
        it = d["intent"]
        intent = Intent(
            normalized_objective=it["normalized_objective"],
            target_repo=TargetRepo(
                repository_id=it["target_repo"]["repository_id"],
                baseline_commit=it["target_repo"]["baseline_commit"],
            ),
        )
        ambiguities = tuple(
            Ambiguity(
                ambiguity_id=a["ambiguity_id"],
                description=a["description"],
                status=AmbiguityStatus(a["status"]),
                resolution=a.get("resolution"),
            )
            for a in d.get("ambiguities", [])
        )
        auth = d["authorization"]
        authorization = Authorization(
            authority_source=auth["authority_source"],
            policy_version=auth["policy_version"],
            valid_until=auth["valid_until"],
            revocation_status=auth.get("revocation_status", False),
            authorized_mutation_paths=tuple(auth.get("authorized_mutation_paths", ())),
            prohibited_operations=tuple(auth.get("prohibited_operations", ())),
        )
        acc = d["acceptance"]
        acceptance = Acceptance(
            criteria=tuple(
                AcceptanceCriterion(
                    criterion_id=c["criterion_id"],
                    description=c["description"],
                    validator_type=c["validator_type"],
                    test_target=c["test_target"],
                    required=c.get("required", True),
                )
                for c in acc.get("criteria", [])
            ),
            independent_validation_required=acc.get("independent_validation_required", True),
        )
        dep = d.get("dependencies", {})
        dependencies = Dependencies(
            permitted_parallelism=dep.get("permitted_parallelism", 1),
            prerequisite_work_orders=tuple(dep.get("prerequisite_work_orders", ())),
        )
        b = d.get("budget", {})
        budget = Budget(
            max_retries=b.get("max_retries", 3),
            max_wallclock_seconds=b.get("max_wallclock_seconds", 600),
            escalation_policy=b.get("escalation_policy", "FAIL_CLOSED_ON_BUDGET_EXHAUSTED"),
        )
        st = d.get("state", {})
        state = WorkOrderStateRecord(
            current_stage=WorkOrderState(st.get("current_stage", "DRAFT")),
            terminal_disposition=st.get("terminal_disposition"),
            fencing_token=st.get("fencing_token", 1),
        )
        history = tuple(
            HistoryEntry(
                version=h["version"],
                timestamp=h["timestamp"],
                change_reason=h["change_reason"],
                author=h["author"],
            )
            for h in d.get("history", [])
        )
        return cls(
            work_order_id=d["work_order_id"],
            version=d["version"],
            predecessor_hash=d.get("predecessor_hash"),
            created_at=d["created_at"],
            source_instruction=source_inst,
            intent=intent,
            ambiguities=ambiguities,
            authorization=authorization,
            acceptance=acceptance,
            dependencies=dependencies,
            budget=budget,
            state=state,
            history=history,
        )
