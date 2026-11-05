"""Capability-Aware Inference Scheduling (docs/design/07): eligibility is earned by evidence and enforced in routing.

Acceptance criteria covered here are named AC-xx (docs/design/07 section 12). Inference is InMemoryAdapter / stub
adapters: these tests prove gateway enforcement, not model competence.
"""
from __future__ import annotations

import dataclasses
import json
import statistics
import threading
import time
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from pathlib import Path

import pytest

from orchestrator_gateway import GatewayServer, create_gateway
from orchestrator_runtime import CapabilityRegistry, EvidenceStore, InMemoryAdapter, OrchestratorRuntime
from orchestrator_runtime import cais
from orchestrator_runtime import cais_cli
from orchestrator_runtime.clients import Client, ClientRegistry, token_digest
from orchestrator_runtime.evidence import canonical, record_hash
from orchestrator_runtime.routing import Router
from tests.test_orchestrator_metrics_contract import validate_exposition
from tests.test_orchestrator_runtime import worker as _base_worker


def worker(worker_id, **kw):
    """The shared fixture with a labelled hardware class: grants for the "unspecified" default are refused."""
    return dataclasses.replace(_base_worker(worker_id, **kw), hardware_class="test-accelerator")

CATALOG = {
    "schema": "cais-capabilities/v1",
    "policy_version": "test-1",
    "capabilities": {
        "coding.routine": {"version": 1, "description": "routine", "criteria": {
            "suite_id": "engx-base", "suite_version": "v1", "min_tasks": 10, "min_pass_lower_bound": 0.6,
            "confidence": 0.9, "max_infra_error_rate": 0.1, "max_validity_days": 30, "min_context_envelope": 1024,
            "min_independence": "internal"}},
        "coding.complex": {"version": 1, "description": "complex", "criteria": {
            "suite_id": "engx-hard", "suite_version": "v1", "min_tasks": 10, "min_pass_lower_bound": 0.45,
            "confidence": 0.9, "max_infra_error_rate": 0.1, "max_validity_days": 30, "min_context_envelope": 1024,
            "min_independence": "internal"}},
    },
}
MSG = [{"role": "user", "content": "hello"}]


def bundle_for(w, *, capability="coding.routine", passes=12, tasks=12, repeats=2, gate_fail=False, envelope=8192,
               reasoning=None, independence="internal", suite="engx-base", run_id=None):
    trials = []
    for i in range(tasks):
        for r in range(repeats):
            trials.append({"task_id": f"T{i:02d}", "repeat": r, "outcome": "pass" if i < passes else "fail",
                           "latency_ms": 1000 + i, "ttft_ms": 100 + i})
    trials.append({"task_id": "G-tool-schema", "repeat": 0, "gate": True, "outcome": "fail" if gate_fail else "pass"})
    identity = cais.profile_identity(w)
    return {"schema": cais.BUNDLE_SCHEMA, "run_id": run_id or f"run-{w.worker_id}-{capability}-{passes}",
            "capability": capability, "capability_version": 1,
            "suite": {"id": suite, "version": "v1", "tasks": [f"T{i:02d}" for i in range(tasks)] + ["G-tool-schema"]},
            "profile": identity, "profile_digest": cais.profile_digest(identity),
            "reasoning": reasoning if reasoning is not None else {"mode": "off"},
            "context_envelope": envelope, "independence": independence, "trials": trials}


def authority(tmp_path) -> Path:
    directory = tmp_path / "authority"
    directory.mkdir()
    (directory / "capabilities.json").write_text(json.dumps(CATALOG))
    return directory


def grant(directory: Path, tmp_path: Path, bundle: dict, **kw) -> str:
    path = tmp_path / f"{bundle['run_id']}.json"
    path.write_text(json.dumps(bundle))
    argv = ["grant", str(directory), "--bundle", str(path), "--authority", "test-operator"]
    if kw.get("valid_days"):
        argv += ["--valid-days", str(kw["valid_days"])]
    assert cais_cli.main(argv) == 0
    return [r for r in cais.read_ledger(directory / "ledger.jsonl").records
            if r["event"] == "qualification_granted"][-1]["qualification_id"]


def service(directory, tmp_path, *, clock=None, mode="enforce", first_enable=True):
    """A gateway with CAIS state. The first enablement over existing ledgers needs the explicit, attributable
    re-baseline the runbook prescribes (anti-rollback refuses to trust ledgers it has never seen)."""
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    svc = cais.CaisService(mode, directory, state, clock=clock or cais._now)
    if first_enable and mode == "enforce" and not (state / "cais-ledger-heads.json").exists():
        svc.rebaseline(authority="test-operator")
    return svc


def runtime_for(tmp_path, workers, svc, *, adapters=None, router=None):
    registry = CapabilityRegistry(workers)
    adapters = adapters or {w.worker_id: InMemoryAdapter(f"answer from {w.worker_id}") for w in workers}
    return OrchestratorRuntime(registry, adapters, EvidenceStore(tmp_path / "evidence.jsonl"), cais=svc, router=router)


def req(capability="coding.routine", **kw):
    return cais.CaisRequirement(capability, **kw)


# ======================================================================================================= unit: policy
def test_catalog_rejects_vague_or_unmeasurable_definitions():
    good = cais.CapabilityCatalog.from_json(json.dumps(CATALOG))
    assert sorted(good.capabilities) == ["coding.complex", "coding.routine"]
    for mutate in (
        lambda c: c["capabilities"].update({"Coding": c["capabilities"]["coding.routine"]}),
        lambda c: c["capabilities"]["coding.routine"]["criteria"].update(min_tasks=3),
        lambda c: c["capabilities"]["coding.routine"]["criteria"].pop("confidence"),
        lambda c: c["capabilities"]["coding.routine"]["criteria"].update(min_independence="self_reported"),
        lambda c: c.update(extra=True),
    ):
        broken = json.loads(json.dumps(CATALOG))
        mutate(broken)
        with pytest.raises(cais.CaisConfigError):
            cais.CapabilityCatalog.from_json(json.dumps(broken))


def test_assessment_uses_tasks_not_correlated_repeats_and_gates_cannot_be_averaged_away():
    definition = cais.CapabilityCatalog.from_json(json.dumps(CATALOG)).capabilities["coding.routine"]
    w = worker("a")
    assert cais.assess_bundle(bundle_for(w, passes=10), definition).qualified  # LB(10/12, 0.9) = 0.658
    below = cais.assess_bundle(bundle_for(w, passes=9), definition)
    assert not below.qualified and "pass_rate_below_threshold" in below.reasons
    # 50 repeats of the same 12 tasks must not buy statistical confidence 9/12 does not have.
    assert not cais.assess_bundle(bundle_for(w, passes=9, repeats=50), definition).qualified
    gated = cais.assess_bundle(bundle_for(w, passes=12, gate_fail=True), definition)
    assert not gated.qualified and gated.functional["gate_failures"] == ["G-tool-schema"]
    unstable = bundle_for(w, passes=12)
    unstable["trials"][1]["outcome"] = "fail"  # T00 passes once, fails once
    result = cais.assess_bundle(unstable, definition)
    assert result.functional["unstable_tasks"] == ["T00"] and result.functional["task_passes"] == 11
    few = cais.assess_bundle(bundle_for(w, passes=8, tasks=8), definition)
    assert "insufficient_tasks" in few.reasons
    infra = bundle_for(w)
    for trial in infra["trials"][:6]:
        trial["outcome"] = "infra_error"
    assert "insufficient_evidence_infra_errors" in cais.assess_bundle(infra, definition).reasons
    assert "suite_mismatch" in cais.assess_bundle(bundle_for(w, suite="other"), definition).reasons


def test_profile_identity_is_scoped_and_excludes_placement():
    a, b = worker("a"), worker("b")
    same_artifact_other_gpu = cais.profile_identity(a) | {"model_id": b.model_id}
    assert cais.profile_digest(cais.profile_identity(b)) == cais.profile_digest(same_artifact_other_gpu)
    for field, value in (("artifact_digest", "sha256:" + "e" * 64), ("runtime_image_digest", "sha256:" + "f" * 64),
                         ("hardware_class", "amd-strix-halo-128g"), ("reasoning_budget", 4096), ("engine", "vllm")):
        assert cais.profile_digest({**cais.profile_identity(a), field: value}) != cais.profile_digest(cais.profile_identity(a))


def test_requirement_headers_are_strict():
    headers = {"X-AIHost-Capability": "coding.routine", "X-AIHost-Min-Context": "32768",
               "X-AIHost-Routing-Priority": "latency"}
    parsed = cais.CaisRequirement.from_headers(headers.get)
    assert (parsed.capability, parsed.min_context, parsed.priority, parsed.fallback) == \
        ("coding.routine", 32768, "latency", "qualified_only")
    assert cais.CaisRequirement.from_headers({}.get) is None
    for bad in ({"X-AIHost-Capability": ""}, {"X-AIHost-Capability": "x.y", "X-AIHost-Qualification": "preferred"},
                {"X-AIHost-Capability": "x.y", "X-AIHost-Min-Context": "-1"},
                {"X-AIHost-Capability": "x.y", "X-AIHost-Fallback": "any"}):
        with pytest.raises(ValueError):
            cais.CaisRequirement.from_headers(bad.get)


# =================================================================================================== qualification state
def test_grant_is_rederived_from_evidence_and_tampering_is_detected(tmp_path):  # AC-03, AC-09
    directory = authority(tmp_path)
    w = worker("a")
    qid = grant(directory, tmp_path, bundle_for(w))
    snapshot = cais.build_snapshot(directory, None, None)
    assert snapshot.valid and snapshot.qualifications[qid].state == cais.QUALIFIED
    assert snapshot.qualifications[qid].bundle_sha256.startswith("sha256:")

    bundle_path = directory / "bundles" / snapshot.qualifications[qid].bundle
    original = bundle_path.read_bytes()
    edited = original.replace(b'"latency_ms": 1000', b'"latency_ms": 10')  # any after-the-fact edit
    assert edited != original
    bundle_path.write_bytes(edited)
    tampered = cais.build_snapshot(directory, None, None).qualifications[qid]
    assert tampered.state == cais.INVALID and tampered.reasons == ("bundle_digest_mismatch",)
    bundle_path.unlink()
    assert cais.build_snapshot(directory, None, None).qualifications[qid].reasons == ("bundle_missing",)
    bundle_path.write_bytes(original)

    ledger = directory / "ledger.jsonl"
    lines = ledger.read_text().splitlines()
    record = json.loads(lines[0])
    record["context_envelope"] = 65536  # widen the grant without re-hashing
    ledger.write_text(canonical(record) + "\n")
    broken = cais.build_snapshot(directory, None, None)
    assert not broken.valid and any("record_hash" in p for p in broken.problems)


def test_forged_grants_are_invalid_even_with_a_valid_hash_chain(tmp_path):  # adversarial: forged qualification
    directory = authority(tmp_path)
    w = worker("a")
    failing = bundle_for(w, passes=5, run_id="failing")
    (directory / "bundles").mkdir()
    data = json.dumps(failing).encode()
    (directory / "bundles" / "failing.json").write_bytes(data)
    identity = cais.profile_identity(w)
    base = dict(capability="coding.routine", capability_version=1, profile=identity,
                profile_digest=cais.profile_digest(identity), reasoning={"mode": "off"}, context_envelope=8192,
                independence="internal", bundle="failing.json", bundle_sha256=cais._sha256_bytes(data),
                issued_at=cais._now().isoformat(), expires_at=(cais._now() + timedelta(days=10)).isoformat(),
                authority="attacker")
    cais.append_ledger(directory / "ledger.jsonl", "qualification_granted", qualification_id="forged-1", **base)
    passing = bundle_for(worker("other"), run_id="passing")  # genuine passing evidence for a different profile
    pdata = json.dumps(passing).encode()
    (directory / "bundles" / "passing.json").write_bytes(pdata)
    cais.append_ledger(directory / "ledger.jsonl", "qualification_granted", qualification_id="forged-2",
                       **{**base, "bundle": "passing.json", "bundle_sha256": cais._sha256_bytes(pdata)})
    good = bundle_for(w, run_id="good")
    gdata = json.dumps(good).encode()
    (directory / "bundles" / "good.json").write_bytes(gdata)
    cais.append_ledger(directory / "ledger.jsonl", "qualification_granted", qualification_id="forged-3",
                       **{**base, "bundle": "good.json", "bundle_sha256": cais._sha256_bytes(gdata),
                          "context_envelope": 65536})
    cais.append_ledger(directory / "ledger.jsonl", "qualification_granted", qualification_id="forged-4",
                       **{**base, "bundle": "../../etc/passwd", "bundle_sha256": "sha256:00"})
    cais.append_ledger(directory / "ledger.jsonl", "qualification_granted", qualification_id="forged-5",
                       **{**base, "bundle": "good.json", "bundle_sha256": cais._sha256_bytes(gdata),
                          "expires_at": (cais._now() + timedelta(days=365)).isoformat()})
    states = cais.build_snapshot(directory, None, None).qualifications
    assert states["forged-1"].reasons[0].startswith("assessment:")
    assert states["forged-2"].reasons == ("bundle_profile_mismatch",)
    assert states["forged-3"].reasons == ("grant_scope_exceeds_evidence",)
    assert states["forged-4"].reasons == ("bundle_path_invalid",)
    assert states["forged-5"].reasons == ("grant_validity_exceeds_policy",)
    assert all(q.state == cais.INVALID for q in states.values())
    assert cais_cli.main(["grant", str(directory), "--bundle", str(directory / "bundles" / "failing.json"),
                          "--authority", "x"]) == 1  # the CLI refuses too; there is no --force


def test_revocation_is_durable_across_restart_reconnect_and_reregistration(tmp_path):  # AC-04
    directory = authority(tmp_path)
    w = worker("a")
    qid = grant(directory, tmp_path, bundle_for(w))
    svc = service(directory, tmp_path)
    svc.suspend(qid, reason_code="regression_confirmed", authority="ops", revoke=True)
    assert svc.snapshot.qualifications[qid].state == cais.REVOKED
    for _ in range(2):  # gateway restart, then a worker re-registering the same profile
        restarted = service(directory, tmp_path)
        assert restarted.snapshot.qualifications[qid].state == cais.REVOKED
        assert restarted.evaluate(req(), [worker("a")], required_context=10).failure_class == "qualification_revoked"
    # A reinstatement cannot undo a revocation; only a new grant on new evidence can.
    cais.append_ledger(directory / "ledger.jsonl", "qualification_reinstated", qualification_id=qid, lifts=["x"],
                       reason_code="oops", authority="ops")
    assert service(directory, tmp_path).snapshot.qualifications[qid].state == cais.REVOKED


def test_gateway_suspension_is_lifted_only_by_an_authoritative_reinstatement(tmp_path):
    directory = authority(tmp_path)
    w = worker("a")
    qid = grant(directory, tmp_path, bundle_for(w))
    svc = service(directory, tmp_path)
    suspension = svc.suspend(qid, reason_code="digest_drift", authority="ops")["evidence_id"]
    assert svc.evaluate(req(), [w], required_context=10).failure_class == "qualification_suspended"
    assert cais_cli.main(["reinstate", str(directory), qid, "--lifts", "unrelated", "--reason", "x",
                          "--authority", "ops"]) == 0
    assert service(directory, tmp_path).snapshot.qualifications[qid].state == cais.SUSPENDED
    assert cais_cli.main(["reinstate", str(directory), qid, "--lifts", suspension, "--reason", "requalified",
                          "--authority", "ops"]) == 0
    assert service(directory, tmp_path).snapshot.qualifications[qid].state == cais.QUALIFIED


def test_gateway_ledger_can_never_grant(tmp_path):  # AC-14: the gateway's own state cannot promote
    directory = authority(tmp_path)
    w = worker("a")
    grant(directory, tmp_path, bundle_for(w))
    state = tmp_path / "state"
    state.mkdir()
    cais.append_ledger(state / "cais-suspensions.jsonl", "qualification_reinstated", qualification_id="q",
                       lifts=[], authority="gateway")
    snapshot = service(directory, tmp_path).snapshot
    assert not snapshot.valid and "forbidden event" in snapshot.problems[0]


def test_ledger_rollback_cannot_restore_a_revoked_qualification(tmp_path):
    directory = authority(tmp_path)
    w = worker("a")
    qid = grant(directory, tmp_path, bundle_for(w))
    before = (directory / "ledger.jsonl").read_text()
    assert cais_cli.main(["revoke", str(directory), qid, "--reason", "bad", "--authority", "ops"]) == 0
    svc = service(directory, tmp_path)
    assert svc.snapshot.qualifications[qid].state == cais.REVOKED and svc.snapshot.anti_rollback == "enforced"
    (directory / "ledger.jsonl").write_text(before)  # e.g. a Git revert of the revocation commit
    rolled = svc.reload()
    assert not rolled.valid and rolled.problems[0].startswith("authoritative_ledger_rollback")
    assert svc.evaluate(req(), [w], required_context=10).failure_class == "qualification_state_unavailable"


def test_expiry_supersession_and_unknown_capability(tmp_path):
    directory = authority(tmp_path)
    w = worker("a")
    qid = grant(directory, tmp_path, bundle_for(w), valid_days=1)
    later = service(directory, tmp_path, clock=lambda: cais._now() + timedelta(days=2))
    assert later.evaluate(req(), [w], required_context=10).failure_class == "qualification_expired"
    assert service(directory, tmp_path).evaluate(req("review.security"), [w],
                                                 required_context=10).failure_class == "capability_unknown"
    bumped = json.loads(json.dumps(CATALOG))
    bumped["capabilities"]["coding.routine"]["version"] = 2
    (directory / "capabilities.json").write_text(json.dumps(bumped))
    svc = service(directory, tmp_path)
    assert svc.snapshot.qualifications[qid].state == cais.SUPERSEDED
    assert svc.evaluate(req(), [w], required_context=10).failure_class == "no_qualified_model"


def test_unreadable_or_misconfigured_state_fails_closed(tmp_path):
    assert not cais.CaisService("enforce", tmp_path / "missing", None).snapshot.valid
    svc = cais.CaisService("enforc", tmp_path, None)  # typo: enforces with an invalid state, never "off"
    assert svc.enabled and svc.snapshot.problems == ("invalid_mode: 'enforc'",)
    assert cais.CaisService("off", None, None).evaluate(req(), [worker("a")], required_context=1).failure_class == \
        "cais_disabled"


# ========================================================================================================= routing
def _qualified_pair(tmp_path, **kw):
    directory = authority(tmp_path)
    good, other = worker("good"), worker("other")
    qid = grant(directory, tmp_path, bundle_for(good, **kw))
    return directory, good, other, qid


def test_legacy_requests_are_untouched_and_capability_requests_fail_closed_when_disabled(tmp_path):  # AC-01
    w = worker("a")
    runtime = runtime_for(tmp_path, [w], None)
    assert runtime.complete({"model": "engineering/a", "messages": MSG})["status"] == "ok"
    denied = runtime.complete({"model": "engineering/a", "messages": MSG}, cais_requirement=req())
    assert (denied["failure_class"], denied["http_status"]) == ("cais_disabled", 503)
    (tmp_path / "x").mkdir()
    off = runtime_for(tmp_path / "x", [w], cais.CaisService("off", None, None))
    assert off.complete({"model": "engineering/a", "messages": MSG}, cais_requirement=req())["failure_class"] == "cais_disabled"


def test_only_qualified_profiles_are_selected_and_fallback_never_leaves_them(tmp_path):  # AC-02, AC-05
    directory, good, other, qid = _qualified_pair(tmp_path)
    runtime = runtime_for(tmp_path, [other, good], service(directory, tmp_path))
    for _ in range(4):
        result = runtime.complete({"model": "engineering/auto", "messages": MSG}, cais_requirement=req())
        assert result["status"] == "ok" and result["response"]["choices"][0]["message"]["content"] == "answer from good"
        assert result["headers"]["X-AIHost-Qualification-Id"] == qid
        assert result["headers"]["X-AIHost-Execution-Profile"] == cais.profile_digest(cais.profile_identity(good))
    runtime.drain("good")  # the only qualified worker is unavailable; the unqualified one is healthy
    blocked = runtime.complete({"model": "engineering/auto", "messages": MSG}, cais_requirement=req())
    assert (blocked["failure_class"], blocked["http_status"]) == ("worker_unavailable", 503)
    assert runtime.complete({"model": "engineering/other", "messages": MSG})["status"] == "ok"  # legacy unaffected
    none = runtime.complete({"model": "engineering/auto", "messages": MSG}, cais_requirement=req("coding.complex"))
    assert (none["failure_class"], none["http_status"]) == ("no_qualified_model", 422)
    assert none["details"]["cais"]["rejected"] == {"good": "no_qualification", "other": "no_qualification"}


def test_explicit_model_alias_or_pin_never_substitutes_another_profile(tmp_path):
    directory, good, other, _ = _qualified_pair(tmp_path)
    router = Router.from_config([{"id": "default", "match": {}, "pool": "lead"}], {"engineering/other-alias": "lead"})
    w_other = cais.profile_identity(other)  # noqa: F841 - documents that "other" is the lead pool's only profile
    good_deep = type(good)(**{**good.__dict__, "pool": "deep"})
    runtime = runtime_for(tmp_path, [other, good_deep], service(directory, tmp_path), router=router)
    alias = runtime.complete({"model": "engineering/other-alias", "messages": MSG}, cais_requirement=req())
    assert alias["failure_class"] == "no_qualified_model" and set(alias["details"]["cais"]["rejected"]) == {"good", "other"}
    pinned = runtime.complete({"model": "x", "messages": MSG}, worker_id="other", cais_requirement=req())
    assert pinned["failure_class"] == "no_qualified_model"
    assert runtime.complete({"model": "x", "messages": MSG}, worker_id="good", cais_requirement=req())["status"] == "ok"


def test_context_envelope_is_enforced(tmp_path):  # AC-08
    directory, good, _, _ = _qualified_pair(tmp_path, envelope=4096)
    runtime = runtime_for(tmp_path, [good], service(directory, tmp_path))
    assert runtime.complete({"messages": MSG}, cais_requirement=req(min_context=4096))["status"] == "ok"
    denied = runtime.complete({"messages": MSG}, cais_requirement=req(min_context=4097))
    assert (denied["failure_class"], denied["details"]["cais"]["required_context"]) == ("context_unsupported", 4097)
    big = [{"role": "user", "content": "x" * 3 * 5000}]  # ~5000 tokens by the conservative estimate
    assert runtime.complete({"messages": big}, cais_requirement=req())["failure_class"] == "context_unsupported"


def test_ranking_is_deterministic_and_qualification_strength_beats_latency_for_quality(tmp_path):  # AC-06
    directory = authority(tmp_path)
    strong, weak = worker("zz-strong"), worker("aa-weak")
    grant(directory, tmp_path, bundle_for(strong, passes=12))
    grant(directory, tmp_path, bundle_for(weak, passes=10))
    svc = service(directory, tmp_path)
    latency = {"zz-strong": 900.0, "aa-weak": 100.0}
    decisions = [svc.evaluate(req(), [weak, strong], required_context=10, latency_ms=latency) for _ in range(5)]
    assert {tuple(c.worker_id for c in d.candidates) for d in decisions} == {("zz-strong", "aa-weak")}
    fast = svc.evaluate(req(priority="latency"), [strong, weak], required_context=10, latency_ms=latency)
    assert [c.worker_id for c in fast.candidates] == ["aa-weak", "zz-strong"]
    assert fast.describe()["inputs"]["latency_ms"] == latency  # the mutable input is captured with the decision
    only = svc.evaluate(req(fallback="none"), [strong, weak], required_context=10)
    assert [c.worker_id for c in only.candidates] == ["zz-strong"] and only.rejected["aa-weak"] == "fallback_prohibited"


def test_qualified_responses_are_never_served_from_cache_after_revocation(tmp_path):
    directory, good, _, qid = _qualified_pair(tmp_path)
    svc = service(directory, tmp_path)
    runtime = runtime_for(tmp_path, [good], svc)
    body = {"messages": MSG, "temperature": 0}
    warm = {**body, "model": "engineering/good"}
    assert runtime.complete(dict(warm))["status"] == "ok"
    assert runtime.complete(dict(warm))["headers"]["X-AIHost-Cache"] == "HIT"  # the legacy cache is really warm
    served = runtime.complete(dict(warm), cais_requirement=req())
    assert served["headers"]["X-AIHost-Cache"] != "HIT" and served["headers"]["X-AIHost-Qualification-Id"] == qid
    assert runtime.complete(dict(body), cais_requirement=req())["status"] == "ok"
    runtime.cais_suspend(qid, reason_code="test", authority="ops")
    assert runtime.complete(dict(body), cais_requirement=req())["failure_class"] == "qualification_suspended"


def test_revocation_while_queued_is_not_executed(tmp_path):
    directory, good, _, qid = _qualified_pair(tmp_path)
    svc = service(directory, tmp_path)
    runtime = runtime_for(tmp_path, [good], svc)
    acquire = runtime.admission.acquire

    def acquire_then_revoke(ticket, eligible):
        granted = acquire(ticket, eligible)
        svc.suspend(qid, reason_code="queued_revocation", authority="ops", revoke=True)
        return granted

    runtime.admission.acquire = acquire_then_revoke
    result = runtime.complete({"messages": MSG}, cais_requirement=req())
    assert result["failure_class"] == "qualification_revoked"
    assert runtime.admission.inflight("good") == 0  # the granted slot was released, nothing was dispatched
    assert not [r for r in runtime.evidence.records() if r["event"] in ("response_validated", "response_rejected", "execution_failed")]


class _BlockingAdapter:
    supports_cancel = True  # the runtime passes the cancel event only to adapters that declare support

    def __init__(self):
        self.started = threading.Event()

    def complete(self, request, timeout, cancel=None, **_):
        self.started.set()
        from orchestrator_runtime import RequestCancelled
        while not cancel.wait(0.01):
            pass
        raise RequestCancelled()


def test_revocation_during_execution_cancels_and_marks_output_untrusted(tmp_path):
    directory, good, _, qid = _qualified_pair(tmp_path)
    adapter = _BlockingAdapter()
    runtime = runtime_for(tmp_path, [good], service(directory, tmp_path), adapters={"good": adapter})
    results = {}
    thread = threading.Thread(target=lambda: results.update(r=runtime.complete({"messages": MSG}, cais_requirement=req())))
    thread.start()
    assert adapter.started.wait(5)
    outcome = runtime.cais_suspend(qid, reason_code="incident", authority="ops", revoke=True)
    thread.join(5)
    assert outcome["cancelled_in_flight"] == 1
    assert (results["r"]["failure_class"], results["r"]["http_status"]) == ("qualification_revoked", 409)
    assert "must not be trusted" in results["r"]["message"]


def test_subsystem_failure_denies_qualified_work_and_leaves_legacy_routing_up(tmp_path):  # AC-10
    directory, good, _, _ = _qualified_pair(tmp_path)
    svc = service(directory, tmp_path)
    runtime = runtime_for(tmp_path, [good], svc)
    (directory / "ledger.jsonl").write_text("{not json\n")
    runtime.cais_reload()
    denied = runtime.complete({"messages": MSG}, cais_requirement=req())
    assert (denied["failure_class"], denied["http_status"]) == ("qualification_state_unavailable", 503)
    assert runtime.complete({"model": "engineering/good", "messages": MSG})["status"] == "ok"


def test_every_decision_is_evidenced_without_prompt_content(tmp_path):  # section 6.1
    directory, good, other, qid = _qualified_pair(tmp_path)
    runtime = runtime_for(tmp_path, [good, other], service(directory, tmp_path))
    runtime.complete({"messages": [{"role": "user", "content": "SECRET-PROMPT"}]}, cais_requirement=req())
    runtime.complete({"messages": MSG}, cais_requirement=req("coding.complex"))
    events = [r for r in runtime.evidence.records() if r["event"] == "cais_routing_decision"]
    assert [e["outcome"] for e in events] == ["ok", "denied"]
    served = events[0]
    assert served["qualification_id"] == qid and served["decision"]["policy_version"] == "test-1"
    assert served["decision"]["rejected"] == {"other": "no_qualification"}
    assert served["decision"]["ledger_heads"]["authoritative"]
    assert "SECRET-PROMPT" not in json.dumps(runtime.evidence.records())


def test_cais_metrics_are_bounded_and_valid_exposition(tmp_path):
    directory, good, _, _ = _qualified_pair(tmp_path)
    runtime = runtime_for(tmp_path, [good], None)
    service(directory, tmp_path)  # first enablement (re-baseline)
    runtime.cais = cais.CaisService("enforce", directory, tmp_path / "state", metrics=runtime.metrics)
    runtime.complete({"messages": MSG}, cais_requirement=req())
    runtime.complete({"messages": MSG}, cais_requirement=req("attacker.controlled.string"))
    text = runtime.metrics.render_prometheus_text()
    validate_exposition(text)
    assert 'aihost_cais_requests_total{capability="coding.routine",result="served"} 1' in text
    assert 'aihost_cais_requests_total{capability="unknown",result="capability_unknown"} 1' in text
    assert 'aihost_cais_qualifications{capability="coding.routine",state="qualified"} 1' in text
    assert "aihost_cais_state_valid 1" in text and "attacker" not in text


def test_routing_overhead_is_within_budget(tmp_path):  # AC-11 (budget: docs/design/07 section 11)
    directory = authority(tmp_path)
    workers = [worker(f"w{i:02d}") for i in range(16)]
    for w in workers:
        grant(directory, tmp_path, bundle_for(w))
    svc = service(directory, tmp_path)
    samples = []
    for _ in range(300):
        started = time.perf_counter()
        svc.evaluate(req(), workers, required_context=100)
        samples.append(time.perf_counter() - started)
    samples.sort()
    p50, p99 = statistics.median(samples), samples[int(len(samples) * 0.99) - 1]
    print(f"cais.evaluate 16 workers/16 qualifications: p50={p50 * 1e6:.0f}us p99={p99 * 1e6:.0f}us")
    assert p99 < 0.005  # 5 ms, against multi-second inference


# ============================================================================================================ HTTP
def _serve(runtime, clients):
    server = GatewayServer(("127.0.0.1", 0), create_gateway(runtime, clients=clients))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _call(server, method, path, token, body=None, headers=None):
    connection = HTTPConnection(*server.server_address)
    connection.request(method, path, body=json.dumps(body) if body is not None else None,
                       headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", **(headers or {})})
    response = connection.getresponse()
    payload = response.read()
    connection.close()
    return response.status, dict(response.getheaders()), json.loads(payload) if payload else None


def test_http_contract_and_privilege_boundaries(tmp_path):  # AC-14, AC-15 (stubbed inference)
    directory, good, other, qid = _qualified_pair(tmp_path)
    runtime = runtime_for(tmp_path, [good, other], service(directory, tmp_path))
    clients = ClientRegistry([Client("nexus", token_digest("nexus-t"), frozenset({"workload"})),
                              Client("ops", token_digest("ops-t"), frozenset({"admin", "monitoring"}))])
    server = _serve(runtime, clients)
    try:
        chat = {"model": "engineering/auto", "messages": MSG}
        cap = {"X-AIHost-Capability": "coding.routine"}
        status, headers, body = _call(server, "POST", "/v1/chat/completions", "nexus-t", chat, cap)
        assert status == 200 and headers["X-AIHost-Qualification-Id"] == qid
        assert headers["X-AIHost-Routing-Decision"]
        status, _, body = _call(server, "POST", "/v1/chat/completions", "nexus-t", chat,
                                {**cap, "X-AIHost-Fallback": "anything"})
        assert status == 400 and body["error"]["code"] == "cais_request_invalid"
        status, _, body = _call(server, "GET", "/v1/cais", "nexus-t")
        assert status == 200 and body["qualifications"][qid]["state"] == "qualified"
        # Workload clients get the reduced view: no authorities, bundles, ledger heads or problem text.
        assert not {"problems", "ledger_heads", "anti_rollback"} & set(body)
        assert "authority" not in body["qualifications"][qid] and "bundle_sha256" not in body["qualifications"][qid]
        status, _, full = _call(server, "GET", "/v1/cais", "ops-t")
        assert status == 200 and "problems" in full
        status, _, _ = _call(server, "POST", "/v1/admin/cais/rebaseline", "nexus-t", {})
        assert status == 403
        # A workload client cannot remove (or add) qualifications.
        status, _, _ = _call(server, "POST", f"/v1/admin/cais/qualifications/{qid}/revoke", "nexus-t",
                             {"reason_code": "griefing"})
        assert status == 403
        status, _, body = _call(server, "POST", f"/v1/admin/cais/qualifications/{qid}/revoke", "ops-t",
                                {"reason_code": "confirmed_regression"})
        assert status == 200 and body["state"] == "revoked"
        status, _, body = _call(server, "POST", f"/v1/admin/cais/qualifications/{qid}/suspend", "ops-t",
                                {"reason_code": "again"})
        assert status == 409 and body["status"] == "conflict"  # nothing to suspend: no redundant ledger records
        status, headers, body = _call(server, "POST", "/v1/chat/completions", "nexus-t", chat, cap)
        assert status == 422 and body["error"]["code"] == "qualification_revoked"
        assert "ledger_heads" not in body["error"]["details"]["cais"]
        assert body["error"]["details"]["cais"]["rejected"]["good"] == "qualification_revoked"
        assert headers["X-AIHost-Routing-Decision"]
        status, _, _ = _call(server, "POST", "/v1/chat/completions", "nexus-t",
                             {"model": "engineering/good", "messages": MSG})  # legacy path still serves
        assert status == 200
    finally:
        server.shutdown()
        server.server_close()


def test_streaming_responses_carry_the_qualification_identity(tmp_path):
    from tests.test_orchestrator_gateway import StreamingAdapter
    directory, good, _, qid = _qualified_pair(tmp_path)
    runtime = runtime_for(tmp_path, [good], service(directory, tmp_path), adapters={"good": StreamingAdapter(content="hi")})
    server = _serve(runtime, ClientRegistry([Client("nexus", token_digest("t"), frozenset({"workload"}))]))
    try:
        connection = HTTPConnection(*server.server_address)
        connection.request("POST", "/v1/chat/completions", body=json.dumps({"messages": MSG, "stream": True}),
                           headers={"Authorization": "Bearer t", "X-AIHost-Capability": "coding.routine"})
        response = connection.getresponse()
        text = response.read().decode()
        connection.close()
        assert response.status == 200 and response.getheader("X-AIHost-Qualification-Id") == qid
        assert "[DONE]" in text
    finally:
        server.shutdown()
        server.server_close()


def test_asgi_front_end_enforces_the_same_contract(tmp_path):
    pytest.importorskip("starlette")
    from starlette.testclient import TestClient
    from orchestrator_gateway.asgi import create_asgi_gateway
    directory, good, other, qid = _qualified_pair(tmp_path)
    runtime = runtime_for(tmp_path, [good, other], service(directory, tmp_path))
    runtime.clients = ClientRegistry([Client("nexus", token_digest("t"), frozenset({"workload"})),
                                      Client("ops", token_digest("o"), frozenset({"admin"}))])
    app = create_asgi_gateway(runtime, clients=runtime.clients) if "clients" in create_asgi_gateway.__code__.co_varnames \
        else create_asgi_gateway(runtime, "t")
    with TestClient(app) as client:
        ok = client.post("/v1/chat/completions", json={"messages": MSG},
                         headers={"Authorization": "Bearer t", "X-AIHost-Capability": "coding.routine"})
        assert ok.status_code == 200 and ok.headers["X-AIHost-Qualification-Id"] == qid
        bad = client.post("/v1/chat/completions", json={"messages": MSG},
                          headers={"Authorization": "Bearer t", "X-AIHost-Capability": "coding.complex"})
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "no_qualified_model"
        assert client.post(f"/v1/admin/cais/qualifications/{qid}/suspend", json={"reason_code": "x"},
                           headers={"Authorization": "Bearer t"}).status_code == 403
        reduced = client.get("/v1/cais", headers={"Authorization": "Bearer t"}).json()
        assert "problems" not in reduced and "authority" not in reduced["qualifications"][qid]
        admin = {"Authorization": "Bearer o"}
        assert "problems" in client.get("/v1/cais", headers=admin).json()
        assert client.post(f"/v1/admin/cais/qualifications/{qid}/suspend", json={"reason_code": "x"},
                           headers=admin).status_code == 200
        assert client.post(f"/v1/admin/cais/qualifications/{qid}/suspend", json={"reason_code": "x"},
                           headers=admin).status_code == 409
        assert client.post("/v1/admin/cais/rebaseline", headers={"Authorization": "Bearer t"}).status_code == 403
        rebased = client.post("/v1/admin/cais/rebaseline", headers=admin)
        assert rebased.status_code == 200 and rebased.json()["valid"]


# ============================================================================== review and security-audit regressions
def test_truncating_or_deleting_the_gateway_suspension_ledger_fails_closed(tmp_path):  # audit H1
    directory, good, _, qid = _qualified_pair(tmp_path)
    svc = service(directory, tmp_path)
    svc.suspend(qid, reason_code="incident", authority="ops", revoke=True)
    ledger = tmp_path / "state" / "cais-suspensions.jsonl"
    for damage in (lambda: ledger.write_text(""), ledger.unlink):
        saved = ledger.read_bytes()
        damage()
        reloaded = svc.reload()
        assert not reloaded.valid and "gateway_ledger_rollback" in reloaded.problems[0]
        assert svc.evaluate(req(), [good], required_context=10).failure_class == "qualification_state_unavailable"
        ledger.write_bytes(saved)
        assert svc.reload().valid and svc.snapshot.qualifications[qid].state == cais.REVOKED


def test_deleting_the_anti_rollback_baseline_fails_closed_until_an_evidenced_rebaseline(tmp_path):  # audit H1/M1
    directory, good, _, qid = _qualified_pair(tmp_path)
    evidence = EvidenceStore(tmp_path / "evidence.jsonl")
    service(directory, tmp_path)
    svc = cais.CaisService("enforce", directory, tmp_path / "state", evidence=evidence)
    (tmp_path / "state" / "cais-ledger-heads.json").unlink()
    assert "anti_rollback_baseline_missing" in svc.reload().problems[0]
    assert svc.evaluate(req(), [good], required_context=10).failure_class == "qualification_state_unavailable"
    result = svc.rebaseline(authority="ops-ticket-42")
    assert result["valid"] and svc.evaluate(req(), [good], required_context=10).candidates
    record = [r for r in evidence.records() if r["event"] == "cais_rebaselined"][-1]
    assert record["authority"] == "ops-ticket-42" and record["previous"] is None
    # Empty ledgers on a brand-new gateway need no ceremony.
    (tmp_path / "fresh").mkdir()
    fresh = authority(tmp_path / "fresh")
    assert cais.CaisService("enforce", fresh, tmp_path / "fresh").snapshot.valid


def test_rebaseline_refuses_a_broken_ledger_and_an_unwritable_baseline_fails_closed(tmp_path):
    directory, good, _, _ = _qualified_pair(tmp_path)
    svc = service(directory, tmp_path)
    with open(directory / "ledger.jsonl", "a") as handle:
        handle.write('{"event": "forged"}\n')
    with pytest.raises(cais.CaisConflict):
        svc.rebaseline(authority="ops")
    ledgers = {"authoritative": cais.read_ledger(directory / "ledger.jsonl"),
               "gateway": cais.read_ledger(tmp_path / "state" / "cais-suspensions.jsonl")}
    problem = cais.write_head(tmp_path / "no-such-dir" / "heads.json", ledgers)
    assert problem and problem.startswith("anti_rollback_state_unwritable") and str(tmp_path) not in problem


def test_capability_header_is_validated_before_anything_is_recorded():  # audit M2
    for bad in ("x" * 65, "Coding.Routine", "coding", "coding.routine;drop", "a." + "b" * 70):
        with pytest.raises(ValueError):
            cais.CaisRequirement.from_headers({"X-AIHost-Capability": bad}.get)
    assert cais.CaisRequirement.from_headers({"X-AIHost-Capability": " coding.routine "}.get).capability == "coding.routine"


def test_redundant_suspensions_are_refused(tmp_path):  # audit M3
    directory, _, _, qid = _qualified_pair(tmp_path)
    svc = service(directory, tmp_path)
    svc.suspend(qid, reason_code="a", authority="ops")
    with pytest.raises(cais.CaisConflict):
        svc.suspend(qid, reason_code="b", authority="ops")
    svc.suspend(qid, reason_code="escalated", authority="ops", revoke=True)  # suspended -> revoked is allowed
    with pytest.raises(cais.CaisConflict):
        svc.suspend(qid, reason_code="c", authority="ops", revoke=True)
    assert len(cais.read_ledger(tmp_path / "state" / "cais-suspensions.jsonl").records) == 2


def test_infra_only_tasks_and_gates_count_as_failures():  # review 1
    definition = cais.CapabilityCatalog.from_json(json.dumps(CATALOG)).capabilities["coding.routine"]
    w = worker("a")
    hidden_gate = bundle_for(w, tasks=40, passes=40)
    for trial in hidden_gate["trials"]:
        if trial.get("gate"):
            trial["outcome"] = "infra_error"
    assessment = cais.assess_bundle(hidden_gate, definition)
    assert not assessment.qualified and "deterministic_gate_failed" in assessment.reasons
    hidden_task = bundle_for(w, tasks=12, passes=12)
    for trial in hidden_task["trials"]:
        if trial["task_id"] in ("T00", "T01"):
            trial["outcome"] = "infra_error"  # 4 of 25 trials: also over the infra budget, but counted as failures
    assert cais.assess_bundle(hidden_task, definition).functional["task_passes"] == 10
    dropped = bundle_for(w)
    dropped["trials"] = [t for t in dropped["trials"] if t["task_id"] != "T03"]
    assert "suite_task_coverage_mismatch" in cais.assess_bundle(dropped, definition).reasons


def test_identity_and_version_fields_are_type_strict():  # review 9, 10, 13
    base = cais.profile_identity(worker("a"))
    digests = {cais.profile_digest({**base, "reasoning_budget": v}) for v in (1, True, 1.0)}
    assert len(digests) == 3  # equal-hashing values must not share a cache entry
    definition = cais.CapabilityCatalog.from_json(json.dumps(CATALOG)).capabilities["coding.routine"]
    bundle = bundle_for(worker("a"))
    bundle["capability_version"] = True
    assert "bundle_capability_version_mismatch" in cais.assess_bundle(bundle, definition).reasons


def test_grants_for_an_unlabelled_hardware_class_are_invalid(tmp_path):  # review 13
    directory = authority(tmp_path)
    unlabelled = _base_worker("a")
    qid = grant(directory, tmp_path, bundle_for(unlabelled))
    q = service(directory, tmp_path).snapshot.qualifications[qid]
    assert q.state == cais.INVALID and "grant_profile_incomplete" in q.reasons


def test_reregistration_while_queued_with_a_different_artifact_is_not_executed(tmp_path):  # review 2
    directory, good, _, _ = _qualified_pair(tmp_path)
    runtime = runtime_for(tmp_path, [good], service(directory, tmp_path))
    acquire = runtime.admission.acquire

    def acquire_then_swap(ticket, eligible):
        granted = acquire(ticket, eligible)
        runtime.registry.register(dataclasses.replace(good, artifact_digest="sha256:" + "e" * 64))
        return granted

    runtime.admission.acquire = acquire_then_swap
    result = runtime.complete({"messages": MSG}, cais_requirement=req())
    assert result["failure_class"] == "no_qualified_model" and "profile_changed" in result["message"]
    assert runtime.admission.inflight("good") == 0
    assert runtime.adapters["good"].calls == 0


def test_revocation_reaches_adapters_that_cannot_be_cancelled(tmp_path):  # review 4
    directory, good, _, qid = _qualified_pair(tmp_path)
    svc = service(directory, tmp_path)

    class Uncancellable:
        def complete(self, request, timeout):
            svc.suspend(qid, reason_code="incident", authority="ops", revoke=True)  # lands mid-generation
            return {"content": "late answer", "tool_calls": []}

    runtime = runtime_for(tmp_path, [good], svc, adapters={"good": Uncancellable()})
    result = runtime.complete({"messages": MSG}, cais_requirement=req())
    assert (result["failure_class"], result["http_status"]) == ("qualification_revoked", 409)
    assert "late answer" not in json.dumps(result, default=str)


def test_reload_after_an_authoritative_revocation_cancels_in_flight_work(tmp_path):  # review 5 (SIGHUP path)
    directory, good, _, qid = _qualified_pair(tmp_path)
    adapter = _BlockingAdapter()
    runtime = runtime_for(tmp_path, [good], service(directory, tmp_path), adapters={"good": adapter})
    results = {}
    thread = threading.Thread(target=lambda: results.update(r=runtime.complete({"messages": MSG}, cais_requirement=req())))
    thread.start()
    assert adapter.started.wait(5)
    assert cais_cli.main(["revoke", str(directory), qid, "--reason", "regression", "--authority", "reviewer"]) == 0
    assert runtime.cais_reload()["cancelled_in_flight"] == 1  # what the SIGHUP handler calls
    thread.join(5)
    assert results["r"]["http_status"] == 409


def test_an_unresolvable_model_name_is_denied_not_substituted(tmp_path):  # review 8
    directory, good, _, _ = _qualified_pair(tmp_path)
    runtime = runtime_for(tmp_path, [good], service(directory, tmp_path))
    denied = runtime.complete({"model": "vendor/some-other-model", "messages": MSG}, cais_requirement=req())
    assert denied["failure_class"] == "policy_denied"
    assert runtime.complete({"model": "engineering/auto", "messages": MSG}, cais_requirement=req())["status"] == "ok"
    assert runtime.complete({"messages": MSG}, cais_requirement=req())["status"] == "ok"
