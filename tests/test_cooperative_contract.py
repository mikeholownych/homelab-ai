from datetime import datetime, timedelta, timezone

import pytest

from orchestrator_contract import (
    Authority,
    Capability,
    EvidenceState,
    FakeAdapter,
    Handoff,
    Observation,
    Orchestrator,
    Task,
    Validation,
)
from orchestrator_contract.core import RetryableFailure


def make_task(**changes):
    values = {
        "task_id": "task-001",
        "repository": "git@example/repo",
        "commit": "a" * 40,
        "requested_capabilities": frozenset({"navigation"}),
        "scope": frozenset({"read"}),
        "state_version": 1,
    }
    values.update(changes)
    return Task(**values)


def make_authority(task, *, revoked=False):
    return Authority(
        task_id=task.task_id,
        task_state_hash=task.state_hash,
        allowed_actions=frozenset({"read"}),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        revoked=revoked,
    )


def make_orchestrator(*adapters, validator=True, authority=None):
    return Orchestrator(
        adapters=list(adapters),
        validator=validator,
        authority=authority,
    )


def test_routes_to_healthy_worker_with_proven_capability():
    worker = FakeAdapter("fast", {"navigation"})
    task = make_task()

    result = make_orchestrator(worker).execute(task, make_authority(task))

    assert result.status == "validated"
    assert result.worker_id == "fast"
    assert result.validation.accepted is True


def test_rejects_when_no_worker_proves_required_capability():
    task = make_task(requested_capabilities=frozenset({"debugging"}))

    result = make_orchestrator(FakeAdapter("fast", {"navigation"})).execute(
        task, make_authority(task)
    )

    assert result.status == "unsupported"
    assert result.failure_class == "capability"


def test_rejects_stale_observation_before_routing():
    task = make_task(observations=(Observation(
        observation_id="obs-1",
        repository="git@example/repo",
        commit="b" * 40,
        source="README.md",
        content_hash="c" * 64,
        state=EvidenceState.VERIFIED,
        retrieval_method="exact-read",
        observed_at="2026-09-25T00:00:00Z",
    ),))

    result = make_orchestrator(FakeAdapter("fast", {"navigation"})).execute(
        task, make_authority(task)
    )

    assert result.status == "blocked"
    assert result.failure_class == "stale_evidence"


def test_rejects_malformed_handoff_without_replacing_source_evidence():
    task = make_task()
    handoff = Handoff(
        task_id=task.task_id,
        repository=task.repository,
        commit=task.commit,
        observations=(),
        interpretation="model says tests passed",
        proposed_actions=("run tests",),
        validation_history=(),
    )

    with pytest.raises(ValueError, match="source observations"):
        handoff.validate(task)


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("validator_unavailable", "validator_unavailable"),
        ("revoked_authority", "authority"),
        ("worker_failure", "worker"),
        ("timeout", "timeout"),
        ("cancelled", "cancelled"),
        ("retry_limit", "retry_limit"),
    ],
)
def test_failures_are_bounded_and_classified(case, expected):
    task = make_task()
    worker = FakeAdapter("fast", {"navigation"}, behavior=case)
    authority = make_authority(task, revoked=case == "revoked_authority")
    orchestrator = make_orchestrator(
        worker,
        validator=case != "validator_unavailable",
        authority=authority,
    )

    result = orchestrator.execute(task, authority, max_retries=2)

    assert result.status == "blocked"
    assert result.failure_class == expected
    assert result.attempts <= 3


def test_recovery_uses_a_healthy_worker_after_transient_failure():
    task = make_task()
    failed = FakeAdapter("failed", {"navigation"}, behavior="worker_failure")
    healthy = FakeAdapter("healthy", {"navigation"})

    result = make_orchestrator(failed, healthy).execute(task, make_authority(task))

    assert result.status == "validated"
    assert result.worker_id == "healthy"
    assert result.attempts == 2


def test_retry_success_returns_validated_result():
    task = make_task()
    class RetryOnceAdapter(FakeAdapter):
        calls = 0

        def run(self, task):
            self.calls += 1
            if self.calls == 1:
                raise RetryableFailure("transient")
            return super().run(task)

    worker = RetryOnceAdapter("retrying", {"navigation"})

    result = make_orchestrator(worker).execute(task, make_authority(task), max_retries=2)

    assert result.status == "validated"
    assert result.worker_id == "retrying"
    assert result.attempts == 2


def test_model_output_cannot_grant_authority_or_expand_scope():
    task = make_task(scope=frozenset({"read"}))
    worker = FakeAdapter(
        "fast",
        {"navigation"},
        model_output={
            "grant_authority": True,
            "expand_scope": ["write", "deploy"],
            "waive_validation": True,
        },
    )

    result = make_orchestrator(worker).execute(task, make_authority(task))

    assert result.status == "validated"
    assert result.authority.allowed_actions == frozenset({"read"})
    assert result.validation.accepted is True
    assert result.evidence_scope == frozenset({"read"})


def test_observations_are_immutable_and_handoff_preserves_identity():
    observation = Observation(
        observation_id="obs-1",
        repository="git@example/repo",
        commit="a" * 40,
        source="src/main.py:10",
        content_hash="c" * 64,
        state=EvidenceState.VERIFIED,
        retrieval_method="exact-read",
        observed_at="2026-09-25T00:00:00Z",
    )
    task = make_task(observations=(observation,))
    handoff = Handoff.from_task(task, "inspect implementation")

    assert handoff.task_id == task.task_id
    assert handoff.repository == task.repository
    assert handoff.commit == task.commit
    assert handoff.observations[0].content_hash == observation.content_hash
    with pytest.raises(AttributeError):
        observation.content_hash = "d" * 64


def test_authority_is_bound_to_current_task_state_and_action():
    task = make_task()
    authority = make_authority(task)

    assert authority.allows(task, "read")
    assert not authority.allows(make_task(state_version=2), "read")
    assert not authority.allows(task, "write")


def test_validation_record_is_explicit_and_not_model_claim():
    validation = Validation(
        validator_id="pytest-contract",
        accepted=True,
        checks=("scope", "identity", "sentinel"),
        source="independent-test",
    )

    assert validation.accepted is True
    assert validation.source == "independent-test"
