"""CAIS evidence pipeline end to end with STUBBED inference (docs/design/07 AC-12/AC-15, local tier).

runner -> real gateway HTTP -> stub worker -> engx hidden tests under bubblewrap -> bundle -> independent rescore ->
operator grant -> gateway enforcement -> revocation -> denial. The "model" is an oracle that returns the corpus
reference solutions (or garbage), so this proves the pipeline and its integrity checks, not any model's competence.
"""
from __future__ import annotations

import dataclasses
import json
import shutil
import sys
import threading
from pathlib import Path

import pytest

from orchestrator_gateway import GatewayServer, create_gateway
from orchestrator_runtime import CapabilityRegistry, EvidenceStore, OrchestratorRuntime, cais, cais_cli
from orchestrator_runtime.clients import Client, ClientRegistry, token_digest
from tests.test_orchestrator_runtime import worker as _base_worker


def worker(worker_id, **kw):
    """The shared fixture with a labelled hardware class: grants for the "unspecified" default are refused."""
    return dataclasses.replace(_base_worker(worker_id, **kw), hardware_class="test-accelerator")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "evaluations" / "cais"))
sys.path.insert(0, str(REPO / "evaluations" / "engx"))
pytestmark = pytest.mark.skipif(shutil.which("bwrap") is None, reason="engx grading needs bubblewrap")


class OracleAdapter:
    """Answers each engx task with its reference solution, recognised by the task instruction in the prompt."""

    def __init__(self, tasks, *, wrong=False):
        self.tasks, self.wrong = tasks, wrong

    def complete(self, request, timeout):
        prompt = " ".join(str(m.get("content")) for m in request["messages"])
        task = next(t for t in self.tasks if t["instruction"] in prompt)
        files = {"src/nothing.py": "x = 1\n"} if self.wrong else task["reference"]
        text = "\n".join(f"### FILE: {path}\n```python\n{body}\n```" for path, body in files.items())
        # Like llama.cpp, report exact usage; the runner derives the measured context envelope from it.
        return {"content": text, "tool_calls": [],
                "usage": {"prompt_tokens": len(prompt) // 4, "completion_tokens": len(text) // 4}}


def _gateway(tmp_path, adapter, svc=None):
    lead = worker("lead")
    runtime = OrchestratorRuntime(CapabilityRegistry([lead]), {"lead": adapter},
                                  EvidenceStore(tmp_path / "evidence.jsonl"), cais=svc)
    clients = ClientRegistry([Client("qualification", token_digest("q-token"), frozenset({"qualification"})),
                              Client("nexus", token_digest("n-token"), frozenset({"workload"}))])
    server = GatewayServer(("127.0.0.1", 0), create_gateway(runtime, clients=clients))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return lead, runtime, server, f"http://127.0.0.1:{server.server_address[1]}"


def _profile(tmp_path, w, **override):
    path = tmp_path / "profile.json"
    path.write_text(json.dumps({**cais.profile_identity(w), "reasoning": {}, **override}))
    return path


def _run(tmp_path, base, profile):
    import run_qualification
    token = tmp_path / "token"
    token.write_text("q-token")
    out = tmp_path / "bundles-out"
    code = run_qualification.main(["run", "--base", base, "--token-file", str(token), "--model", "engineering/lead",
                                   "--profile", str(profile), "--capability", "coding.routine", "--corpus", "base",
                                   "--reps", "1", "--out", str(out)])
    assert code == 0
    return next(out.glob("*.json")), run_qualification


def _catalog(directory: Path, suite_version: str):
    directory.mkdir(exist_ok=True)
    (directory / "capabilities.json").write_text(json.dumps({
        "schema": "cais-capabilities/v1", "policy_version": "pipeline-test",
        "capabilities": {"coding.routine": {"version": 1, "description": "engx base corpus", "criteria": {
            "suite_id": "engx-base", "suite_version": suite_version, "min_tasks": 10, "min_pass_lower_bound": 0.6,
            "confidence": 0.9, "max_infra_error_rate": 0.1, "max_validity_days": 30, "min_context_envelope": 1,
            "min_independence": "internal"}}}}))


def test_pipeline_qualifies_rescore_detects_tampering_and_enforcement_follows_revocation(tmp_path):
    import engx_tasks
    lead, runtime, server, base = _gateway(tmp_path, OracleAdapter(engx_tasks.TASKS))
    try:
        bundle_path, runner = _run(tmp_path, base, _profile(tmp_path, lead))
    finally:
        server.shutdown()
        server.server_close()
    bundle = json.loads(bundle_path.read_text())
    assert {t["outcome"] for t in bundle["trials"]} == {"pass"} and len(bundle["trials"]) == 12
    assert bundle["observed_serving"]["before"]["artifact_digest"] == lead.artifact_digest
    assert 0 < bundle["context_envelope"] < lead.context_limit  # measured, not the configured maximum

    assert runner.main(["rescore", str(bundle_path)]) == 0  # independent re-grading agrees
    tampered = json.loads(bundle_path.read_text())
    tampered["trials"][0]["outcome"] = "fail"
    tampered_path = tmp_path / "tampered.json"
    tampered_path.write_text(json.dumps(tampered))
    assert runner.main(["rescore", str(tampered_path)]) == 1

    directory = tmp_path / "authority"
    _catalog(directory, bundle["suite"]["version"])
    assert cais_cli.main(["grant", str(directory), "--bundle", str(bundle_path), "--authority", "pipeline-test"]) == 0
    state = tmp_path / "state"
    state.mkdir()
    svc = cais.CaisService("enforce", directory, state)
    assert not svc.snapshot.valid  # anti-rollback: ledgers this gateway has never accepted are not trusted
    svc.rebaseline(authority="pipeline-test")  # the runbook's explicit first-enablement step
    qid = next(iter(svc.snapshot.qualifications))
    assert svc.snapshot.qualifications[qid].state == cais.QUALIFIED

    (tmp_path / "g2").mkdir()
    _lead2, runtime2, server2, _ = _gateway(tmp_path / "g2", OracleAdapter(engx_tasks.TASKS), svc)
    try:
        request = {"model": "engineering/auto", "messages": [{"role": "user", "content": engx_tasks.TASKS[0]["instruction"]}]}
        served = runtime2.complete(dict(request), cais_requirement=cais.CaisRequirement("coding.routine"))
        assert served["status"] == "ok" and served["headers"]["X-AIHost-Qualification-Id"] == qid
        runtime2.cais_suspend(qid, reason_code="pipeline_revocation", authority="pipeline-test", revoke=True)
        denied = runtime2.complete(dict(request), cais_requirement=cais.CaisRequirement("coding.routine"))
        assert denied["failure_class"] == "qualification_revoked"
    finally:
        server2.shutdown()
        server2.server_close()


def test_pipeline_refuses_wrong_identity_and_failing_models_cannot_be_granted(tmp_path):
    import engx_tasks
    lead, _runtime, server, base = _gateway(tmp_path, OracleAdapter(engx_tasks.TASKS, wrong=True))
    try:
        import run_qualification
        token = tmp_path / "token"
        token.write_text("q-token")
        wrong = _profile(tmp_path, lead, artifact_digest="sha256:" + "9" * 64)
        with pytest.raises(SystemExit, match="does not match the profile"):
            run_qualification.main(["run", "--base", base, "--token-file", str(token), "--model", "engineering/lead",
                                    "--profile", str(wrong), "--capability", "coding.routine", "--corpus", "base",
                                    "--reps", "1", "--out", str(tmp_path / "never")])
        bundle_path, _ = _run(tmp_path, base, _profile(tmp_path, lead))
    finally:
        server.shutdown()
        server.server_close()
    bundle = json.loads(bundle_path.read_text())
    assert {t["outcome"] for t in bundle["trials"]} == {"fail"}
    directory = tmp_path / "authority"
    _catalog(directory, bundle["suite"]["version"])
    assert cais_cli.main(["grant", str(directory), "--bundle", str(bundle_path), "--authority", "x"]) == 1
    assert not (directory / "ledger.jsonl").exists()
