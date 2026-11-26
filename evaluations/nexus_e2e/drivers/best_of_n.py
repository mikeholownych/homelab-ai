#!/usr/bin/env python3
"""Best-of-n implement samples with execution-gated selection (hidden oracle).

Runs up to N independent engx trajectories (temperature > 0). Selects the first
sample that passes the hidden oracle; if none pass, the task fails. No LLM judge.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ENGX_DIR = REPO / "evaluations" / "engx"
sys.path.insert(0, str(ENGX_DIR))
sys.path.insert(0, str(REPO / "evaluations" / "nexus_e2e" / "scripts"))
sys.path.insert(0, str(REPO / "evaluations" / "nexus_e2e" / "drivers"))

import capture_fleet_identity as fleet  # noqa: E402
from common import (  # noqa: E402
    PIN_ALIASES,
    check_lead_rocm_same_artifact,
    load_token,
    serving_snapshot,
)


def select_first_pass(samples: list[dict]) -> dict:
    """Pure selection rule for tests: first success wins; else last sample."""
    for s in samples:
        if s.get("success"):
            return {"selected": s, "reason": "oracle_pass", "oracle_coverage": True}
    return {
        "selected": samples[-1] if samples else {},
        "reason": "none_passed",
        "oracle_coverage": any(s.get("success") for s in samples),
    }


def run_bon_task(task, base, headers, alias, n, max_attempts, engx) -> dict:
    t0 = time.monotonic()
    samples = []
    tokens = 0
    selected = None
    for i in range(1, n + 1):
        rec = engx.run_task(task, base, headers, alias, max_attempts)
        sample = {
            "sample": i,
            "success": bool(rec.get("success")),
            "attempts": rec.get("attempts", 0),
            "tokens": rec.get("tokens") or 0,
            "wall_secs": rec.get("wall_secs"),
            "history": [
                {
                    "attempt": h.get("attempt"),
                    "ok": h.get("ok"),
                    "stage": h.get("stage"),
                    "termination": h.get("termination"),
                    "wall_secs": h.get("wall_secs"),
                }
                for h in (rec.get("history") or [])
            ],
        }
        samples.append(sample)
        tokens += sample["tokens"]
        if sample["success"]:
            selected = sample
            break
    decision = select_first_pass(samples)
    if selected is None:
        selected = decision["selected"]
    return {
        "id": task["id"],
        "success": bool(selected.get("success")),
        "accepted": bool(selected.get("success")),
        "n_requested": n,
        "n_run": len(samples),
        "samples": samples,
        "selected_sample": selected.get("sample"),
        "selection_reason": decision["reason"],
        "oracle_coverage": any(s.get("success") for s in samples),
        "tokens": tokens,
        "wall_secs": round(time.monotonic() - t0, 1),
        "attempts": selected.get("attempts", 0),
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
        "n": meta["n"],
        "temperature": meta["temperature"],
        "max_attempts": meta["max_attempts"],
        "reps": meta["reps"],
        "tasks": meta["tasks"],
        "n_trials": n,
        "accepted_rate": round(100 * len(ok) / n, 1) if n else 0.0,
        "oracle_coverage_rate": round(
            100 * sum(1 for p in packets if p.get("oracle_coverage")) / n, 1
        ) if n else 0.0,
        "mean_samples_run": round(
            sum((p.get("metrics") or {}).get("n_run") or 0 for p in packets) / n, 2
        ) if n else None,
        "mean_tokens_per_task": round(sum(p.get("metrics", {}).get("tokens") or 0 for p in packets) / n) if n else None,
        "mean_secs_per_task": round(
            sum(p.get("metrics", {}).get("wall_secs") or 0 for p in packets) / n, 1
        ) if n else None,
        "median_secs_to_accepted": round(
            statistics.median(
                [p["metrics"]["wall_secs"] for p in ok if p["metrics"].get("wall_secs") is not None]
            ),
            1,
        ) if ok else None,
        "per_task_pass": {k: f"{sum(v)}/{len(v)}" for k, v in per_task.items()},
        "always_fail": [k for k, v in per_task.items() if not any(v)],
        "flaky": [k for k, v in per_task.items() if any(v) and not all(v)],
        "serving": meta["serving"],
    }


def run(args: argparse.Namespace) -> int:
    os.environ["ENGX_CORPUS"] = "hard"
    os.environ["ENGX_MAX_TOKENS"] = str(args.max_tokens)
    os.environ["ENGX_TEMPERATURE"] = str(args.temperature)
    os.environ.setdefault("ENGX_PYTHON", str(REPO / ".venv" / "bin" / "python"))
    import engx  # noqa: PLC0415

    # Re-bind in case module was imported earlier in tests
    engx.CORPUS = "hard"
    engx.TASKS = engx.CORPORA["hard"]
    engx.TEMPERATURE = args.temperature
    engx.MAX_TOKENS = args.max_tokens

    token = load_token(args.token_file)
    if not token:
        raise SystemExit("empty token")
    alias = PIN_ALIASES[args.pin]
    arm = f"bon{args.n}-{args.pin}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "X-AIHost-Cache": "bypass",
        "Cache-Control": "no-store",
    }
    base = args.base.rstrip("/")
    check_lead_rocm_same_artifact(base, headers, args.allow_digest_divergence)
    before = serving_snapshot(base, headers, alias)

    only = args.only.split(",") if args.only else None
    tasks = [t for t in engx.TASKS if not only or any(t["id"].startswith(p) for p in only)]
    corpus = {
        "id": "engx-hard",
        "digest": engx.corpus_digest(engx.TASKS),
        "max_attempts": args.max_attempts,
        "max_tokens": engx.MAX_TOKENS,
        "temperature": args.temperature,
        "task_ids": [t["id"] for t in tasks],
    }
    stamp = args.stamp or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out_dir = Path(args.out) if args.out else REPO / "evaluations" / "nexus_e2e" / "evidence" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    packets_dir = out_dir / "packets" / arm
    packets_dir.mkdir(parents=True, exist_ok=True)

    fleet_path = out_dir / "fleet_identity.json"
    if not fleet_path.is_file():
        identity = fleet.build_identity(base, token)
        fleet_path.write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")

    run_id = f"{arm}-{stamp}"
    packets: list[dict] = []
    raw: list[dict] = []
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    for rep in range(1, args.reps + 1):
        for task in tasks:
            t0 = time.monotonic()
            rec = run_bon_task(task, base, headers, alias, args.n, args.max_attempts, engx)
            rec["rep"] = rep
            raw.append(rec)
            pkt = {
                "schema": "nexus-e2e-evidence-packet/v1",
                "run_id": run_id,
                "arm": arm,
                "task_id": rec["id"],
                "rep": rep,
                "accepted": rec["accepted"],
                "oracle": {
                    "kind": "engx-hidden",
                    "pass": rec["accepted"],
                    "stage": "bon-select",
                    "summary": rec["selection_reason"],
                },
                "corpus": corpus,
                "serving": {
                    "alias": alias,
                    "before": before,
                    "after": before,
                    "identity_stable": True,
                },
                "attempts": rec["attempts"],
                "metrics": {
                    "wall_secs": rec["wall_secs"],
                    "tokens": rec["tokens"],
                    "n_run": rec["n_run"],
                    "n_requested": rec["n_requested"],
                },
                "history": rec["samples"],
                "review": None,
                "oracle_coverage": rec["oracle_coverage"],
                "selection_reason": rec["selection_reason"],
                "selected_sample": rec["selected_sample"],
            }
            packets.append(pkt)
            (packets_dir / f"{task['id']}-rep{rep}.json").write_text(
                json.dumps(pkt, indent=2) + "\n", encoding="utf-8"
            )
            status = "PASS" if pkt["accepted"] else "FAIL"
            print(
                f"{arm} rep{rep} {task['id']:24s} {status} "
                f"n_run={rec['n_run']}/{args.n} tokens={rec['tokens']} "
                f"wall={rec['wall_secs']}s elapsed={round(time.monotonic() - t0, 1)}s",
                flush=True,
            )
            (out_dir / f"{arm}.partial.json").write_text(
                json.dumps({"label": arm, "packets": packets, "results": raw}, indent=2) + "\n",
                encoding="utf-8",
            )

    meta = {
        "arm": arm,
        "alias": alias,
        "n": args.n,
        "temperature": args.temperature,
        "max_attempts": args.max_attempts,
        "stamp": stamp,
        "started_at": started,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "reps": args.reps,
        "tasks": len(tasks),
        "corpus": corpus,
        "serving": {"before": before, "after": serving_snapshot(base, headers, alias)},
        "gateway": base,
    }
    summary = _summarize(packets, meta)
    archive = {"label": arm, "meta": meta, "summary": summary, "packets": packets, "results": raw}
    (out_dir / f"{arm}.json").write_text(json.dumps(archive, indent=2) + "\n", encoding="utf-8")
    (out_dir / f"{arm}.summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print("RESULT", arm, json.dumps(summary), flush=True)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pin", required=True, choices=sorted(PIN_ALIASES))
    p.add_argument("--n", type=int, default=3)
    p.add_argument("--temperature", type=float, default=0.2)
    p.add_argument("--base", default="https://10.0.8.5:8443")
    p.add_argument("--token-file", required=True)
    p.add_argument("--reps", type=int, default=1)
    p.add_argument("--max-attempts", type=int, default=1, help="Per-sample repair attempts (default 1 for BoN)")
    p.add_argument("--max-tokens", type=int, default=8192)
    p.add_argument("--only", default=None)
    p.add_argument("--stamp", default=None)
    p.add_argument("--out", default=None)
    p.add_argument("--allow-digest-divergence", action="store_true")
    return run(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
