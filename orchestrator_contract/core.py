from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class EvidenceState(StrEnum):
    VERIFIED = "verified"
    HISTORICAL = "historical"
    INTERPRETATION = "interpretation"
    CONTRADICTORY = "contradictory"


@dataclass(frozen=True)
class Observation:
    observation_id: str
    repository: str
    commit: str
    source: str
    content_hash: str
    state: EvidenceState
    retrieval_method: str
    observed_at: str
    complete: bool = True
    truncated: bool = False

    def __post_init__(self) -> None:
        if self.state is not EvidenceState.VERIFIED:
            return
        if self.retrieval_method != "exact-read":
            raise ValueError("verified observations require exact-read")
        if not self.complete or self.truncated:
            raise ValueError("verified observations must be complete")

    def as_record(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "repository": self.repository,
            "commit": self.commit,
            "source": self.source,
            "content_hash": self.content_hash,
            "state": self.state.value,
            "retrieval_method": self.retrieval_method,
            "observed_at": self.observed_at,
            "complete": self.complete,
            "truncated": self.truncated,
        }


@dataclass(frozen=True)
class Task:
    task_id: str
    repository: str
    commit: str
    requested_capabilities: frozenset[str]
    scope: frozenset[str]
    state_version: int
    observations: tuple[Observation, ...] = ()

    @property
    def state_hash(self) -> str:
        return content_hash(
            {
                "task_id": self.task_id,
                "repository": self.repository,
                "commit": self.commit,
                "requested_capabilities": sorted(self.requested_capabilities),
                "scope": sorted(self.scope),
                "state_version": self.state_version,
                "observations": [item.as_record() for item in self.observations],
            }
        )


@dataclass(frozen=True)
class Authority:
    task_id: str
    task_state_hash: str
    allowed_actions: frozenset[str]
    expires_at: datetime
    revoked: bool = False

    def allows(self, task: Task, action: str, now: datetime | None = None) -> bool:
        current = now or datetime.now(self.expires_at.tzinfo)
        return (
            not self.revoked
            and self.task_id == task.task_id
            and self.task_state_hash == task.state_hash
            and action in self.allowed_actions
            and current < self.expires_at
        )


@dataclass(frozen=True)
class Capability:
    name: str
    evidence_id: str
    measured_at: str
    expires_at: str
    revoked: bool = False


@dataclass(frozen=True)
class Handoff:
    task_id: str
    repository: str
    commit: str
    observations: tuple[Observation, ...]
    interpretation: str
    proposed_actions: tuple[str, ...]
    validation_history: tuple[str, ...]

    @classmethod
    def from_task(cls, task: Task, interpretation: str) -> "Handoff":
        return cls(
            task_id=task.task_id,
            repository=task.repository,
            commit=task.commit,
            observations=task.observations,
            interpretation=interpretation,
            proposed_actions=(),
            validation_history=(),
        )

    def validate(self, task: Task) -> None:
        if (self.task_id, self.repository, self.commit) != (
            task.task_id,
            task.repository,
            task.commit,
        ):
            raise ValueError("handoff task identity mismatch")
        if not self.observations:
            raise ValueError("handoff must preserve source observations")
        for observation in self.observations:
            if observation.repository != task.repository or observation.commit != task.commit:
                raise ValueError("handoff contains stale source observations")


@dataclass(frozen=True)
class Validation:
    validator_id: str
    accepted: bool
    checks: tuple[str, ...]
    source: str


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    failure_class: str | None
    worker_id: str | None
    attempts: int
    validation: Validation | None
    authority: Authority
    evidence_scope: frozenset[str]


class WorkerFailure(RuntimeError):
    pass


class RetryableFailure(RuntimeError):
    pass


class CancelledFailure(RuntimeError):
    pass


@dataclass
class FakeAdapter:
    worker_id: str
    capabilities: set[str] | frozenset[str]
    behavior: str = "success"
    model_output: dict[str, Any] = field(default_factory=dict)
    healthy: bool = True

    def can_handle(self, task: Task) -> bool:
        return self.healthy and task.requested_capabilities <= set(self.capabilities)

    def run(self, task: Task) -> dict[str, Any]:
        if self.behavior == "worker_failure":
            self.healthy = False
            raise WorkerFailure("worker failed")
        if self.behavior == "timeout":
            raise TimeoutError("worker deadline exceeded")
        if self.behavior == "cancelled":
            raise CancelledFailure("request cancelled")
        if self.behavior == "retry_limit":
            raise RetryableFailure("retryable worker failure")
        return {"task_id": task.task_id, "model_output": self.model_output}


class Orchestrator:
    def __init__(
        self,
        adapters: list[FakeAdapter],
        validator: bool = True,
        authority: Authority | None = None,
    ) -> None:
        self.adapters = adapters
        self.validator = validator
        self.authority = authority

    def execute(self, task: Task, authority: Authority, max_retries: int = 2) -> ExecutionResult:
        if not authority.allows(task, "read"):
            return self._blocked("authority", 0, authority, task.scope)
        if any(
            observation.repository != task.repository
            or observation.commit != task.commit
            or observation.state is not EvidenceState.VERIFIED
            for observation in task.observations
        ):
            return self._blocked("stale_evidence", 0, authority, task.scope)
        if not self.validator:
            return self._blocked("validator_unavailable", 0, authority, task.scope)

        eligible = [adapter for adapter in self.adapters if adapter.can_handle(task)]
        if not eligible:
            return self._blocked("capability", 0, authority, task.scope, status="unsupported")

        attempts = 0
        for adapter in eligible:
            attempts += 1
            try:
                adapter.run(task)
            except WorkerFailure:
                continue
            except TimeoutError:
                return self._blocked("timeout", attempts, authority, task.scope)
            except CancelledFailure:
                return self._blocked("cancelled", attempts, authority, task.scope)
            except RetryableFailure:
                for _ in range(max_retries):
                    attempts += 1
                    try:
                        adapter.run(task)
                    except RetryableFailure:
                        continue
                    else:
                        validation = Validation(
                            validator_id="fake-independent-validator",
                            accepted=True,
                            checks=("task-identity", "scope", "worker-result"),
                            source="contract-harness",
                        )
                        return ExecutionResult(
                            status="validated",
                            failure_class=None,
                            worker_id=adapter.worker_id,
                            attempts=attempts,
                            validation=validation,
                            authority=authority,
                            evidence_scope=task.scope,
                        )
                return self._blocked("retry_limit", attempts, authority, task.scope)
            else:
                validation = Validation(
                    validator_id="fake-independent-validator",
                    accepted=True,
                    checks=("task-identity", "scope", "worker-result"),
                    source="contract-harness",
                )
                return ExecutionResult(
                    status="validated",
                    failure_class=None,
                    worker_id=adapter.worker_id,
                    attempts=attempts,
                    validation=validation,
                    authority=authority,
                    evidence_scope=task.scope,
                )

        return self._blocked("worker", attempts, authority, task.scope)

    @staticmethod
    def _blocked(
        failure_class: str,
        attempts: int,
        authority: Authority,
        scope: frozenset[str],
        status: str = "blocked",
    ) -> ExecutionResult:
        return ExecutionResult(
            status=status,
            failure_class=failure_class,
            worker_id=None,
            attempts=attempts,
            validation=None,
            authority=authority,
            evidence_scope=scope,
        )
