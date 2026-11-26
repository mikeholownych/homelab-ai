#!/usr/bin/env python3
"""Stage 1 solo baseline driver: one pin through the 5820 front door.

Runs the engx hard corpus (or a task-id prefix filter) with cache bypass,
records evidence packets, and refuses to continue if lead/rocm digests diverge
unless --allow-digest-divergence is set.
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import statistics
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ENGX_DIR = REPO / "evaluations" / "engx"
sys.path.insert(0, str(ENGX_DIR))
sys.path.insert(0, str(REPO / "evaluations" / "nexus_e2e" / "scripts"))

import capture_fleet_identity as fleet  # noqa: E402

PIN_ALIASES = {
    "deep": "engineering/deep",
    "lead": "engineering/lead",
    "rocm": "engineering/interactive-rocm",
}
ARM = {"deep": "solo-deep", "lead": "solo-lead", "rocm": "solo-rocm"}


def _load_token(token_file: str) -> str:
    if token_file == "-":
        return sys.stdin.read().strip()
    return Path(token_file).read_text(encoding="utf-8").strip()


def _get(base: str, path: str, headers: dict, ca: str | None = None) -> dict:
    req = urllib.request.Request(base.rstrip("/") + path, headers=headers)
    ctx = ssl.create_default_context(cafile=ca) if ca else ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
        return json.load(resp)


def _serving_snapshot(base: str, headers: dict, alias: str, ca: str | None = None) -> dict:
    models = _get(base, "/v1/models", headers, ca=ca)
    entry = next((m for m in models.get("data", []) if m.get("id") == alias), None)
    if entry is None:
        raise SystemExit(f"alias {alias!r} is not served by {base}")
    serving = entry.get("serving") or []
    if len(serving) != 1:
        raise SystemExit(
            f"alias {alias!r} reaches {len(serving)} workers; solo baseline needs exactly one"
        )
    s = serving[0]
    return {
        "alias": alias,
        "context_length": entry.get("context_length") or entry.get("max_model_len"),
        "reasoning": entry.get("reasoning"),
        "worker_id": s.get("worker_id"),
        "pool": s.get("pool"),
        "model_id": s.get("model_id"),
        "artifact_digest": s.get("artifact_digest"),
        "engine": s.get("engine"),
        "engine_version": s.get("engine_version"),
        "quantization": s.get("quantization"),
    }


def _check_lead_rocm_constraint(base: str, headers: dict, allow: bool, ca: str | None = None) -> None:
    lead = _serving_snapshot(base, headers, "engineering/lead", ca=ca)
    rocm = _serving_snapshot(base, headers, "engineering/interactive-rocm", ca=ca)
    if lead["artifact_digest"] != rocm["artifact_digest"] and not allow:
        raise SystemExit(
            "lead/rocm artifact digests diverge "
            f"({lead['artifact_digest']!r} vs {rocm['artifact_digest']!r}); "
            "update the plan and pass --allow-digest-divergence"
        )


def _packet(arm: str, run_id: str, task_rec: dict, corpus: dict, before: dict, after: dict) -> dict:
    history = task_rec.get("history") or []
    last = history[-1] if history else {}
    oracle_pass = bool(task_rec.get("success"))
    complete = before.get("artifact_digest") is not None and after.get("artifact_digest") is not None
    return {
        "schema": "nexus-e2e-evidence-packet/v1",
        "run_id": run_id,
        "arm": arm,
        "task_id": task_rec["id"],
        "rep": task_rec.get("rep", 1),
        "accepted": oracle_pass and complete,
        "oracle": {
            "kind": "engx-hidden",
            "pass": oracle_pass,
            "stage": last.get("stage"),
            "summary": (last.get("feedback") or last.get("error") or "")[:500] or None,
        },
        "corpus": corpus,
        "serving": {
            "alias": before["alias"],
            "before": before,
            "after": after,
            "identity_stable": before.get("artifact_digest") == after.get("artifact_digest")
            and before.get("worker_id") == after.get("worker_id"),
        },
        "attempts": task_rec.get("attempts", 0),
        "metrics": {
            "wall_secs": task_rec.get("wall_secs"),
            "model_secs": task_rec.get("model_secs"),
            "tokens": task_rec.get("tokens"),
        },
        "history": [
            {
                "attempt": h.get("attempt"),
                "ok": h.get("ok"),
                "stage": h.get("stage"),
                "termination": h.get("termination"),
                "wall_secs": h.get("wall_secs"),
                "prompt_tokens": h.get("prompt_tokens"),
                "completion_tokens": h.get("completion_tokens"),
                "finish": h.get("finish"),
            }
            for h in history
        ],
        "review": None,
    }


def _summarize(packets: list[dict], meta: dict) -> dict:
    n = len(packets)
    ok = [p for p in packets if p["accepted"]]
    per_task: dict[str, list[bool]] = {}
    for p in packets:
        per_task.setdefault(p["task_id"], []).append(p["accepted"])
    return {
        "arm": meta["arm"],
        "alias": meta["alias"],
        "corpus": meta["corpus"],
        "reps": meta["reps"],
        "tasks": meta["tasks"],
        "n_trials": n,
        "accepted_rate": round(100 * len(ok) / n, 1) if n else 0.0,
        "accepted_per_rep": [
            sum(1 for p in packets if p["rep"] == k and p["accepted"]) for k in range(1, meta["reps"] + 1)
        ],
        "first_attempt_rate": round(
            100 * sum(1 for p in ok if p["attempts"] == 1) / n, 1
        ) if n else 0.0,
        "median_secs_to_accepted": round(
            statistics.median([p["metrics"]["wall_secs"] for p in ok if p["metrics"]["wall_secs"] is not None]),
            1,
        ) if ok else None,
        "mean_secs_per_task": round(
            sum(p["metrics"]["wall_secs"] or 0 for p in packets) / n, 1
        ) if n else None,
        "mean_tokens_per_task": round(
            sum(p["metrics"]["tokens"] or 0 for p in packets) / n
        ) if n else None,
        "per_task_pass": {k: f"{sum(v)}/{len(v)}" for k, v in per_task.items()},
        "always_fail": [k for k, v in per_task.items() if not any(v)],
        "flaky": [k for k, v in per_task.items() if any(v) and not all(v)],
        "serving": meta["serving"],
    }


def run(args: argparse.Namespace) -> int:
    if not args.pin and not args.alias:
        raise SystemExit("pass --pin or --alias")
    if args.ca:
        os.environ["SSL_CERT_FILE"] = args.ca
    os.environ["ENGX_CORPUS"] = "hard"
    os.environ["ENGX_MAX_TOKENS"] = str(args.max_tokens)
    os.environ.setdefault("ENGX_PYTHON", str(REPO / ".venv" / "bin" / "python"))
    import engx  # noqa: PLC0415 — configured via env before import

    engx.CORPUS = "hard"
    engx.TASKS = engx.CORPORA["hard"]
    engx.MAX_TOKENS = int(args.max_tokens)

    token = _load_token(args.token_file)
    if not token:
        raise SystemExit("empty token")
    alias = args.alias or PIN_ALIASES[args.pin]
    arm = args.arm or (ARM[args.pin] if args.pin else alias.replace("candidate/", "cand-").replace("/", "-"))
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "X-AIHost-Cache": "bypass",
        "Cache-Control": "no-store",
    }
    base = args.base.rstrip("/")
    skip_fleet = args.skip_fleet_check or bool(args.alias)
    if not skip_fleet:
        _check_lead_rocm_constraint(base, headers, args.allow_digest_divergence, ca=args.ca)
    before = _serving_snapshot(base, headers, alias, ca=args.ca)

    only = args.only.split(",") if args.only else None
    tasks = [t for t in engx.TASKS if not only or any(t["id"].startswith(p) for p in only)]
    corpus = {
        "id": "engx-hard",
        "digest": engx.corpus_digest(engx.TASKS),
        "max_attempts": args.max_attempts,
        "max_tokens": engx.MAX_TOKENS,
        "temperature": 0,
        "task_ids": [t["id"] for t in tasks],
    }
    stamp = args.stamp or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out_dir = Path(args.out) if args.out else REPO / "evaluations" / "nexus_e2e" / "evidence" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    packets_dir = out_dir / "packets" / arm
    packets_dir.mkdir(parents=True, exist_ok=True)

    fleet_path = out_dir / "fleet_identity.json"
    if not skip_fleet and not fleet_path.is_file():
        identity = fleet.build_identity(base, token)
        if not identity["constraints"]["lead_rocm_same_artifact"] and not args.allow_digest_divergence:
            raise SystemExit("lead/rocm digest divergence at fleet capture")
        fleet_path.write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {fleet_path}", flush=True)

    run_id = f"{arm}-{stamp}"
    packets: list[dict] = []
    raw_results: list[dict] = []
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    for rep in range(1, args.reps + 1):
        for task in tasks:
            t0 = time.monotonic()
            rec = engx.run_task(task, base, headers, alias, args.max_attempts)
            rec["rep"] = rep
            raw_results.append(rec)
            after = _serving_snapshot(base, headers, alias, ca=args.ca)
            if after["artifact_digest"] != before["artifact_digest"]:
                raise SystemExit("serving identity changed mid-run; evidence discarded")
            pkt = _packet(arm, run_id, rec, corpus, before, after)
            packets.append(pkt)
            pkt_path = packets_dir / f"{task['id']}-rep{rep}.json"
            pkt_path.write_text(json.dumps(pkt, indent=2) + "\n", encoding="utf-8")
            status = "PASS" if pkt["accepted"] else "FAIL"
            print(
                f"{arm} rep{rep} {task['id']:24s} {status} "
                f"attempts={rec['attempts']} wall={rec['wall_secs']}s tokens={rec['tokens']} "
                f"elapsed={round(time.monotonic() - t0, 1)}s",
                flush=True,
            )
            # Partial archive after every task.
            partial = {
                "label": arm,
                "meta": {**corpus, "partial": True, "alias": alias, "stamp": stamp},
                "packets": packets,
                "results": raw_results,
            }
            (out_dir / f"{arm}.partial.json").write_text(
                json.dumps(partial, indent=2) + "\n", encoding="utf-8"
            )

    after = _serving_snapshot(base, headers, alias, ca=args.ca)
    meta = {
        "arm": arm,
        "alias": alias,
        "stamp": stamp,
        "started_at": started,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "reps": args.reps,
        "tasks": len(tasks),
        "corpus": corpus,
        "serving": {"before": before, "after": after},
        "gateway": base,
    }
    summary = _summarize(packets, meta)
    archive = {"label": arm, "meta": meta, "summary": summary, "packets": packets, "results": raw_results}
    archive_path = out_dir / f"{arm}.json"
    archive_path.write_text(json.dumps(archive, indent=2) + "\n", encoding="utf-8")
    summary_path = out_dir / f"{arm}.summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print("RESULT", arm, json.dumps(summary), flush=True)
    print(f"wrote {archive_path}", flush=True)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pin", choices=sorted(PIN_ALIASES))
    p.add_argument("--alias", default=None, help="Explicit model alias (e.g. candidate/devstral-small2)")
    p.add_argument("--arm", default=None, help="Override arm name in packets/summary")
    p.add_argument("--base", default="https://10.0.8.5:8443")
    p.add_argument("--ca", default=None, help="CA certificate path for TLS verification")
    p.add_argument("--token-file", required=True)
    p.add_argument("--reps", type=int, default=3)
    p.add_argument("--max-attempts", type=int, default=3)
    p.add_argument("--max-tokens", type=int, default=8192)
    p.add_argument("--only", default=None, help="Comma-separated task id prefixes")
    p.add_argument("--stamp", default=None)
    p.add_argument("--out", default=None, help="Evidence directory (default evidence/<stamp>)")
    p.add_argument("--allow-digest-divergence", action="store_true")
    p.add_argument("--skip-fleet-check", action="store_true")
    return run(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
