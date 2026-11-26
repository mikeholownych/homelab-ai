"""Unit tests for nexus_e2e Stage 0–1 harness (no live gateway)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ENGX = REPO / "evaluations" / "engx"
NEXUS = REPO / "evaluations" / "nexus_e2e"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_engx_hard_corpus_digest_stable():
    sys.path.insert(0, str(ENGX))
    import engx

    assert engx.corpus_digest(engx.CORPORA["hard"]) == "a2e49329628243ed"
    assert len(engx.CORPORA["hard"]) == 10


def test_evidence_packet_schema_loads():
    schema = json.loads((NEXUS / "schema" / "evidence_packet.schema.json").read_text())
    assert schema["properties"]["schema"]["const"] == "nexus-e2e-evidence-packet/v1"
    assert "solo-deep" in schema["properties"]["arm"]["enum"]


def test_solo_packet_builder_accepts_only_oracle_pass():
    solo = _load("nexus_e2e_solo", NEXUS / "drivers" / "solo.py")
    corpus = {"id": "engx-hard", "digest": "a2e49329628243ed"}
    before = {"alias": "engineering/deep", "artifact_digest": "sha256:abc", "worker_id": "w"}
    after = dict(before)
    rec = {
        "id": "H01-semver-range",
        "success": True,
        "attempts": 1,
        "rep": 1,
        "wall_secs": 10.0,
        "model_secs": 9.0,
        "tokens": 100,
        "history": [{"attempt": 1, "ok": True, "stage": "hidden"}],
    }
    pkt = solo._packet("solo-deep", "run-1", rec, corpus, before, after)
    assert pkt["accepted"] is True
    rec_fail = dict(rec, success=False)
    pkt_fail = solo._packet("solo-deep", "run-1", rec_fail, corpus, before, after)
    assert pkt_fail["accepted"] is False


def test_best_of_n_selects_first_oracle_pass():
    bon = _load("nexus_e2e_bon", NEXUS / "drivers" / "best_of_n.py")
    samples = [
        {"sample": 1, "success": False},
        {"sample": 2, "success": True},
        {"sample": 3, "success": True},
    ]
    d = bon.select_first_pass(samples)
    assert d["selected"]["sample"] == 2
    assert d["reason"] == "oracle_pass"
    none = bon.select_first_pass([{"sample": 1, "success": False}])
    assert none["reason"] == "none_passed"
    assert none["oracle_coverage"] is False

    packets = [
        {
            "task_id": "H01",
            "accepted": True,
            "oracle_coverage": True,
            "metrics": {"wall_secs": 10.0, "tokens": 100, "n_run": 1},
        },
        {
            "task_id": "H03",
            "accepted": True,
            "oracle_coverage": True,
            "metrics": {"wall_secs": 20.0, "tokens": 200, "n_run": 2},
        },
    ]
    summary = bon._summarize(
        packets,
        {
            "arm": "bon3-lead",
            "alias": "engineering/lead",
            "n": 3,
            "temperature": 0.2,
            "max_attempts": 1,
            "reps": 1,
            "tasks": 2,
            "serving": {},
        },
    )
    assert summary["mean_samples_run"] == 1.5


def test_dual_parse_findings_and_investigate():
    dual = _load("nexus_e2e_dual", NEXUS / "drivers" / "dual.py")
    assert dual.parse_findings("[]") == []
    assert dual.parse_findings("No findings. LGTM.") == []
    raw = dual.parse_findings(
        '```json\n[{"id":"F1","file":"missing.py","claim":"file is missing","severity":"high"}]\n```'
    )
    assert len(raw) == 1 and raw[0]["file"] == "missing.py"

    class FakeEngx:
        @staticmethod
        def validate(task, root, files):
            return True, "hidden", "ok"

    graded, ok, _ = dual.investigate_findings(
        {"id": "t"},
        {"ok.py": "x=1\n"},
        [{"id": "F1", "file": "missing.py", "claim": "file is missing", "severity": "high"}],
        FakeEngx,
    )
    assert ok is True
    assert graded[0]["status"] == "supported"

    graded2, _, _ = dual.investigate_findings(
        {"id": "t"},
        {"ok.py": "x=1\n"},
        [{"id": "F2", "file": "ok.py", "claim": "tests fail on hidden suite", "severity": "high"}],
        FakeEngx,
    )
    assert graded2[0]["status"] == "refuted"


def test_solo_supports_explicit_candidate_alias(monkeypatch, tmp_path):
    solo = _load("nexus_e2e_solo_alias", NEXUS / "drivers" / "solo.py")
    monkeypatch.setattr(solo, "_check_lead_rocm_constraint", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should skip fleet check")))
    called = {}
    monkeypatch.setattr(
        solo,
        "_serving_snapshot",
        lambda base, headers, alias, ca=None: {
            "alias": alias,
            "context_length": 65536,
            "reasoning": {"mode": "off", "budget": 0},
            "worker_id": "candidate-devstral-small2",
            "pool": "candidate-devstral",
            "model_id": "Devstral-Small-2-24B-Instruct-2512-Q4_K_M",
            "artifact_digest": "sha256:d14ba9",
            "engine": "llama.cpp",
            "engine_version": "b0",
            "quantization": "Q4_K_M",
        },
    )
    import engx

    def fake_run_task(task, base, headers, model, max_attempts):
        called.setdefault("models", []).append(model)
        return {
            "id": task["id"],
            "discipline": task["discipline"],
            "success": True,
            "attempts": 1,
            "model_secs": 1.0,
            "wall_secs": 1.1,
            "tokens": 50,
            "history": [{"attempt": 1, "ok": True, "stage": "hidden"}],
        }

    monkeypatch.setattr(engx, "run_task", fake_run_task)
    tok = tmp_path / "tok"
    tok.write_text("dummy-token\n")
    out = tmp_path / "evid"
    rc = solo.run(
        solo.argparse.Namespace(
            pin=None,
            alias="candidate/devstral-small2",
            arm="cand-devstral-small2",
            base="https://10.0.8.5:8443",
            ca=None,
            token_file=str(tok),
            reps=1,
            max_attempts=1,
            max_tokens=8192,
            only="H02",
            stamp="test-cand",
            out=str(out),
            allow_digest_divergence=False,
            skip_fleet_check=False,
        )
    )
    assert rc == 0
    assert called["models"] == ["candidate/devstral-small2"]
    summary = json.loads((out / "cand-devstral-small2.summary.json").read_text())
    assert summary["arm"] == "cand-devstral-small2"
    assert summary["accepted_rate"] == 100.0


def test_analyze_complementarity_computes_beta_and_union(tmp_path):
    comp = _load("nexus_e2e_complementarity", NEXUS / "scripts" / "analyze_complementarity.py")
    p_a = tmp_path / "a.json"
    p_b = tmp_path / "b.json"
    p_a.write_text(
        json.dumps(
            {
                "arm": "arm-a",
                "packets": [
                    {"task_id": "H01", "rep": 1, "accepted": True},
                    {"task_id": "H02", "rep": 1, "accepted": True},
                    {"task_id": "H03", "rep": 1, "accepted": False},
                    {"task_id": "H04", "rep": 1, "accepted": False},
                ],
            }
        )
    )
    p_b.write_text(
        json.dumps(
            {
                "arm": "arm-b",
                "packets": [
                    {"task_id": "H01", "rep": 1, "accepted": True},
                    {"task_id": "H02", "rep": 1, "accepted": False},
                    {"task_id": "H03", "rep": 1, "accepted": True},
                    {"task_id": "H04", "rep": 1, "accepted": False},
                ],
            }
        )
    )
    arms = [comp.load_arm_packets(str(p_a)), comp.load_arm_packets(str(p_b))]
    rep = comp.compute_report(arms)
    pair = rep["pairwise_trials"][0]
    assert pair["n_shared"] == 4
    assert pair["both_pass"] == 1
    assert pair["only_a"] == 1
    assert pair["only_b"] == 1
    assert pair["both_fail"] == 1
    assert pair["beta"] == 0.25
    assert pair["union_pass_rate"] == 75.0
    md = comp.render_markdown(rep)
    assert "arm-a vs arm-b" in md
    assert "0.2500" in md

