from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from orchestrator_contract import Authority, EvidenceState, FakeAdapter, Handoff, Observation, Orchestrator, Task


ROOT = Path(__file__).parents[1]


def _task() -> Task:
    observation = Observation(
        observation_id="observation-contract",
        repository="fixture/repository",
        commit="a" * 40,
        source="README.md",
        content_hash="b" * 64,
        state=EvidenceState.VERIFIED,
        retrieval_method="exact-read",
        observed_at="2026-09-25T00:00:00Z",
    )
    return Task(
        task_id="contract-task",
        repository="fixture/repository",
        commit="a" * 40,
        requested_capabilities=frozenset({"navigation"}),
        scope=frozenset({"read"}),
        state_version=1,
        observations=(observation,),
    )


def _authority(task: Task, revoked: bool = False) -> Authority:
    return Authority(
        task_id=task.task_id,
        task_state_hash=task.state_hash,
        allowed_actions=frozenset({"read"}),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        revoked=revoked,
    )


def _run_case(case_id: str) -> str:
    task = _task()
    worker = FakeAdapter("fixture-worker", {"navigation"})
    if case_id == "unsupported-capability":
        task = Task(**{**task.__dict__, "requested_capabilities": frozenset({"debugging"})})
    if case_id == "stale-observation":
        stale = Observation(**{**task.observations[0].__dict__, "commit": "c" * 40})
        task = Task(**{**task.__dict__, "observations": (stale,)})
    if case_id == "malformed-handoff":
        try:
            Handoff(task.task_id, task.repository, task.commit, (), "invalid", (), ()).validate(task)
        except ValueError:
            return "rejected"
    if case_id == "unavailable-validator":
        result = Orchestrator([worker], validator=False).execute(task, _authority(task))
        return result.status
    if case_id == "revoked-authority":
        return Orchestrator([worker]).execute(task, _authority(task, revoked=True)).status
    if case_id == "worker-failure-recovery":
        result = Orchestrator([FakeAdapter("failed", {"navigation"}, behavior="worker_failure"), worker]).execute(task, _authority(task))
        return result.status
    if case_id == "timeout":
        return Orchestrator([FakeAdapter("timeout", {"navigation"}, behavior="timeout")]).execute(task, _authority(task)).status
    if case_id == "cancellation":
        return Orchestrator([FakeAdapter("cancelled", {"navigation"}, behavior="cancelled")]).execute(task, _authority(task)).status
    if case_id == "retry-limit":
        return Orchestrator([FakeAdapter("retry", {"navigation"}, behavior="retry_limit")]).execute(task, _authority(task)).status
    return Orchestrator([worker]).execute(task, _authority(task)).status


def run_cases(output: str | Path | None = None) -> dict:
    cases = yaml.safe_load((ROOT / "evaluations/cooperative-cases.yml").read_text())
    results = []
    for case in cases["cases"]:
        actual = _run_case(case["id"])
        results.append({"id": case["id"], "expected": case["expected"], "actual": actual, "validator": case["validator"]})
    report = {
        "schema_version": "1.0.0",
        "run_id": str(uuid.uuid4()),
        "network_access": False,
        "production_credentials": False,
        "active_b0_access": False,
        "results": results,
    }
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = run_cases(args.output)
    return 0 if all(item["expected"] == item["actual"] for item in report["results"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
