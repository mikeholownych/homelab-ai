#!/usr/bin/env python3
"""Produce a CAIS evidence bundle (cais-evidence-bundle/v1) by running the engx engineering corpus through the gateway.

  run_qualification.py run     --base URL --token-file F|- --model ALIAS --profile PROFILE.json \
                               --capability coding.routine --corpus base --reps 2 --out DIR
  run_qualification.py rescore BUNDLE.json      # re-grade the stored final files without the model

Separation of concerns (docs/design/07 section 5.2):
  candidate model   - reached only through the gateway (gateway-only worker access); never called directly
  fixtures/oracle   - engx task corpus with hidden tests, identified by its corpus digest (part of the suite version)
  executor          - this script on the controller; hidden tests run under bubblewrap with no network
  scoring           - engx.validate (deterministic pytest); `rescore` repeats it from the bundle alone
  decision          - orchestrator_runtime.cais.assess_bundle, re-run by the gateway at every load

Identity binding: PROFILE.json is the operator's inventory record for the serving worker (model_id, artifact_digest,
runtime_image_digest, engine, topology, hardware_class, reasoning_budget) plus the alias reasoning policy. The run
refuses to start unless the gateway's /v1/models serving entry for the alias names exactly that artifact, and refuses
to emit a bundle if the serving identity changed during the run. The bundle records what was observed.

Independence is "internal": the corpus and its hidden tests were written in this repository, not by a third party.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE.parent / "engx"))
sys.path.insert(0, str(REPO))

from orchestrator_runtime import cais  # noqa: E402

TRANSPORT_FAILURES = ("timeout", "error")  # engx.classify_error classes that are not the model's answer


def _engx(corpus: str, max_tokens: int):
    os.environ["ENGX_CORPUS"] = corpus
    os.environ["ENGX_MAX_TOKENS"] = str(max_tokens)
    import engx  # noqa: PLC0415 - configured through the environment at import
    return engx


def suite_identity(engx, corpus: str, max_attempts: int) -> dict:
    return {"id": f"engx-{corpus}", "version": f"{engx.corpus_digest(engx.TASKS)}-a{max_attempts}-t{engx.MAX_TOKENS}",
            "corpus_digest": engx.corpus_digest(engx.TASKS), "max_attempts": max_attempts,
            "max_tokens": engx.MAX_TOKENS, "temperature": 0, "tasks": [t["id"] for t in engx.TASKS]}


def _get(base: str, path: str, headers: dict) -> dict:
    with urllib.request.urlopen(urllib.request.Request(base + path, headers=headers), timeout=30,
                                context=ssl.create_default_context()) as response:
        return json.load(response)


def serving_entry(base: str, headers: dict, model: str) -> dict:
    models = _get(base, "/v1/models", headers)
    entry = next((m for m in models.get("data", []) if m.get("id") == model), None)
    if entry is None:
        raise SystemExit(f"alias {model!r} is not served by {base}")
    if len(entry.get("serving") or []) != 1:
        raise SystemExit(f"alias {model!r} reaches {len(entry.get('serving') or [])} workers; qualification needs "
                         "exactly one serving profile per run")
    return entry


def _check_identity(entry: dict, profile: dict) -> None:
    serving = entry["serving"][0]
    mismatched = [k for k in ("model_id", "artifact_digest") if serving.get(k) != profile.get(k)]
    if mismatched:
        raise SystemExit(f"serving identity {[(k, serving.get(k)) for k in mismatched]} does not match the profile")


def run(args: argparse.Namespace) -> int:
    engx = _engx(args.corpus, args.max_tokens)
    spec = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    profile = {k: spec.get(k) for k in cais.PROFILE_FIELDS}
    reasoning = spec.get("reasoning") or {}
    token = sys.stdin.read().strip() if args.token_file == "-" else Path(args.token_file).read_text().strip()
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    before = serving_entry(args.base, headers, args.model)
    _check_identity(before, profile)
    if (before.get("reasoning") or {}).get("mode") != reasoning.get("mode", "default"):
        raise SystemExit(f"alias reasoning mode {before.get('reasoning')} differs from the profile's {reasoning}")

    graded: list[tuple[dict, bool, str]] = []
    original_validate = engx.validate

    def recording_validate(task, root, files):
        ok, stage, feedback = original_validate(task, root, files)
        graded.append((dict(files), ok, stage))
        return ok, stage, feedback

    engx.validate = recording_validate
    trials, started = [], datetime.now(timezone.utc)
    for repeat in range(args.reps):
        for task in engx.TASKS:
            graded.clear()
            t0 = time.monotonic()
            rec = engx.run_task(task, args.base, headers, args.model, args.max_attempts)
            history = rec.get("history") or []
            transport = [h for h in history if h.get("termination") in TRANSPORT_FAILURES and "error" in h]
            outcome = "pass" if rec["success"] else ("infra_error" if transport and not graded else "fail")
            contexts = [(h.get("prompt_tokens") or 0) + (h.get("completion_tokens") or 0) for h in history]
            final_files = graded[-1][0] if graded else {}
            trials.append({
                "task_id": task["id"], "repeat": repeat, "outcome": outcome, "attempts": rec["attempts"],
                "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                "ttft_ms": next((h.get("ttft_ms_est") for h in history if h.get("ttft_ms_est") is not None), None),
                "max_context_tokens": max(contexts) if contexts else 0, "tokens": rec.get("tokens"),
                "terminations": [h.get("termination") for h in history],
                "final_files": final_files,
                "final_files_sha256": hashlib.sha256(json.dumps(final_files, sort_keys=True).encode()).hexdigest(),
            })
            print(f"rep{repeat} {task['id']:24s} {outcome}", flush=True)
    after = serving_entry(args.base, headers, args.model)
    _check_identity(after, profile)
    if after["serving"][0] != before["serving"][0]:
        raise SystemExit("serving identity changed during the run; evidence discarded")

    graded_contexts = [t["max_context_tokens"] for t in trials if t["outcome"] != "infra_error"]
    script = Path(__file__).read_bytes()
    commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    bundle = {
        "schema": cais.BUNDLE_SCHEMA,
        "run_id": f"{args.capability}-{profile['artifact_digest'][7:19]}-{started.strftime('%Y%m%dT%H%M%SZ')}",
        "capability": args.capability, "capability_version": args.capability_version,
        "suite": suite_identity(engx, args.corpus, args.max_attempts),
        "profile": profile, "profile_digest": cais.profile_digest(profile), "reasoning": reasoning,
        # The envelope is what the trials actually exercised, never the configured or advertised maximum.
        "context_envelope": max(graded_contexts) if graded_contexts else 0,
        "independence": "internal",
        "independence_basis": "in-repo engx corpus with hidden pytest oracles; graded under bubblewrap; re-scorable",
        "executor": {"id": "evaluations/cais/run_qualification.py", "sha256": hashlib.sha256(script).hexdigest(),
                     "git_commit": commit, "host": os.uname().nodename},
        "observed_serving": {"before": before["serving"][0], "after": after["serving"][0],
                             "alias_reasoning": before.get("reasoning"), "alias": args.model, "gateway": args.base},
        "sampling": {"temperature": 0, "seed": None, "note": "temperature 0; repeats are correlated, the task is the unit"},
        "started_at": started.isoformat(), "finished_at": datetime.now(timezone.utc).isoformat(),
        "trials": trials,
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{bundle['run_id']}.json"
    path.write_text(json.dumps(bundle, indent=1, sort_keys=True), encoding="utf-8")
    print(f"BUNDLE {path}")
    return 0


def rescore(args: argparse.Namespace) -> int:
    """Re-grade every stored final answer with the same hidden tests. No model, no gateway: independent of both."""
    bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
    suite = bundle["suite"]
    engx = _engx(suite["id"].removeprefix("engx-"), int(suite["max_tokens"]))
    if engx.corpus_digest(engx.TASKS) != suite["corpus_digest"]:
        raise SystemExit("this checkout's corpus differs from the one the bundle was graded with")
    tasks = {t["id"]: t for t in engx.TASKS}
    mismatches = []
    for trial in bundle["trials"]:
        if trial["outcome"] == "infra_error":
            continue
        files = trial.get("final_files") or {}
        if hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest() != trial.get("final_files_sha256"):
            mismatches.append((trial["task_id"], trial["repeat"], "final_files_sha256"))
            continue
        ok = bool(files) and engx.validate(tasks[trial["task_id"]], None, files)[0]
        if ok != (trial["outcome"] == "pass"):
            mismatches.append((trial["task_id"], trial["repeat"], trial["outcome"]))
    print(json.dumps({"bundle": bundle.get("run_id"), "trials": len(bundle["trials"]), "mismatches": mismatches}))
    return 1 if mismatches else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("run")
    p.add_argument("--base", required=True)
    p.add_argument("--token-file", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--profile", required=True)
    p.add_argument("--capability", required=True)
    p.add_argument("--capability-version", type=int, default=1)
    p.add_argument("--corpus", choices=("base", "hard"), required=True)
    p.add_argument("--reps", type=int, default=2)
    p.add_argument("--max-attempts", type=int, default=3)
    p.add_argument("--max-tokens", type=int, default=8192)
    p.add_argument("--out", required=True)
    p.set_defaults(func=run)
    p = sub.add_parser("rescore")
    p.add_argument("bundle")
    p.set_defaults(func=rescore)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
