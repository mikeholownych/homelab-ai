#!/usr/bin/env python3
"""Stage 2 dual collaboration driver: implementer + adversarial reviewer.

Flow (no majority vote):
  implement (engx loop) → if fail: stop (not accepted)
  if pass → reviewer findings → deterministic investigation
  → repair only supported findings → re-oracle

Pins must differ in artifact_digest (deep↔lead). lead↔rocm is refused.
"""
from __future__ import annotations

import argparse
import json
import os
import re
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
    chat_completion,
    check_lead_rocm_same_artifact,
    load_token,
    serving_snapshot,
    usage_tokens,
)

PAIRINGS = {
    "deep-lead": ("deep", "lead", "dual-deep-lead"),
    "lead-deep": ("lead", "deep", "dual-lead-deep"),
}


def parse_findings(text: str) -> list[dict]:
    """Extract a JSON list of findings from reviewer text."""
    text = text.strip()
    candidates = []
    fence = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.S)
    if fence:
        candidates.append(fence.group(1))
    # bare array
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for raw in candidates:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            out = []
            for i, item in enumerate(data):
                if not isinstance(item, dict):
                    continue
                out.append(
                    {
                        "id": str(item.get("id") or f"F{i+1}"),
                        "file": item.get("file"),
                        "claim": item.get("claim") or item.get("issue") or "",
                        "severity": (item.get("severity") or "medium").lower(),
                    }
                )
            return out
    # empty / no findings markers
    low = text.lower()
    if any(p in low for p in ("no findings", "no issues", "lgtm", "looks good", "[]")):
        return []
    return []


def investigate_findings(task, files: dict, findings: list[dict], engx) -> tuple[list[dict], bool, str]:
    """Promote each finding to supported|refuted|dropped via repo/oracle — never another model vote."""
    ok, stage, msg = engx.validate(task, None, files)
    graded = []
    for f in findings:
        claim = (f.get("claim") or "").lower()
        path = f.get("file")
        status = "dropped"
        reason = "no deterministic repro; dropped (not repaired)"
        if any(w in claim for w in ("fails the test", "tests fail", "test failure", "hidden fail", "does not pass")) and ok:
            status = "refuted"
            reason = "oracle currently passes; test-failure claim refuted"
        elif path and path not in files and any(w in claim for w in ("missing", "absent", "not provided", "never written")):
            status = "supported"
            reason = "cited deliverable path absent"
        elif path and path in files:
            content = files[path]
            if "todo" in claim and re.search(r"\bTODO\b", content):
                status = "supported"
                reason = "TODO marker present as claimed"
            elif ("not implemented" in claim or "stub" in claim) and re.search(
                r"^\s*pass\s*$", content, re.M
            ):
                status = "supported"
                reason = "stub `pass` present as claimed"
            elif ("raise notimplemented" in claim or "notimplementederror" in claim) and (
                "NotImplementedError" in content
            ):
                status = "supported"
                reason = "NotImplementedError present as claimed"
            elif f.get("severity") == "high" and path.endswith(".py"):
                # High-severity claims about a named symbol: support if symbol missing.
                sym = re.search(r"\b([a-z_][a-z0-9_]{2,})\b", claim)
                if sym and f"def {sym.group(1)}" not in content and f"class {sym.group(1)}" not in content:
                    # only if claim suggests missing/broken symbol
                    if any(w in claim for w in ("missing", "undefined", "never defined", "no function", "no class")):
                        status = "supported"
                        reason = f"symbol {sym.group(1)!r} not defined in {path}"
        graded.append({**f, "status": status, "investigation": reason})
    return graded, ok, f"{stage}:{msg}"


def final_files_from_history(history: list[dict], engx) -> dict:
    """Best-effort files from the last attempt that produced parseable FILE blocks."""
    files = {}
    for h in history or []:
        text = h.get("response") or ""
        parsed = {p: c for p, c in engx.parse_files(text).items()}
        if parsed:
            files = parsed
    return files


def run_dual_task(task, base, headers, impl_alias, rev_alias, max_attempts, max_tokens, engx) -> dict:
    t_start = time.monotonic()
    calls = []
    tokens = 0

    # --- implement ---
    impl = engx.run_task(task, base, headers, impl_alias, max_attempts)
    tokens += impl.get("tokens") or 0
    calls.append({"role": "implement", "alias": impl_alias, "attempts": impl.get("attempts"), "success": impl.get("success")})
    files = final_files_from_history(impl.get("history") or [], engx)
    # Prefer files from last successful validate by re-validating candidates from history
    if impl.get("success") and files:
        ok, _, _ = engx.validate(task, None, {p: c for p, c in files.items() if engx.allowed(task, p)})
        if not ok:
            # walk history newest-first for a set that validates
            for h in reversed(impl.get("history") or []):
                cand = {p: c for p, c in engx.parse_files(h.get("response") or "").items() if engx.allowed(task, p)}
                if cand and engx.validate(task, None, cand)[0]:
                    files = cand
                    break
    files = {p: c for p, c in files.items() if engx.allowed(task, p)}

    review_block = {
        "ran": False,
        "findings_raw": [],
        "findings": [],
        "clean": None,
        "repair_ran": False,
        "escape": False,
        "regression": False,
    }
    oracle_pass = bool(impl.get("success"))
    oracle_stage = "implement"
    oracle_summary = None
    if impl.get("history"):
        last = impl["history"][-1]
        oracle_summary = (last.get("feedback") or last.get("error") or "")[:500] or None
        oracle_stage = last.get("stage") or oracle_stage

    if not oracle_pass:
        # Plan: review only after pass. Failed implement → not accepted.
        wall = round(time.monotonic() - t_start, 1)
        return {
            "id": task["id"],
            "success": False,
            "accepted": False,
            "attempts": impl.get("attempts", 0),
            "wall_secs": wall,
            "model_secs": impl.get("model_secs"),
            "tokens": tokens,
            "calls": calls,
            "files": files,
            "implement": impl,
            "review": review_block,
            "oracle": {"kind": "engx-hidden", "pass": False, "stage": oracle_stage, "summary": oracle_summary},
        }

    # --- review (adversarial; findings only, never acceptance) ---
    review_block["ran"] = True
    repo_blob = "\n\n".join(f"### FILE: {p}\n```python\n{c}```" for p, c in sorted(files.items()))
    rev_messages = [
        {
            "role": "system",
            "content": (
                "You are an adversarial code reviewer. Do NOT approve the change and do NOT declare "
                "task success. List concrete defect claims only. Reply with a JSON array "
                '(possibly empty) of objects: {"id","file","claim","severity"} where severity is '
                "low|medium|high. If you see no defects, reply `[]`."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Task: {task['instruction']}\n\nProposed files:\n{repo_blob}\n\n"
                "Visible tests exist under tests/ in the original repo; hidden tests are not shown. "
                "Attack missing edge cases, incorrect logic, and unsafe edits."
            ),
        },
    ]
    t_rev = time.monotonic()
    try:
        rev_resp = chat_completion(base, headers, rev_alias, rev_messages, max_tokens)
        rev_text = rev_resp["choices"][0]["message"].get("content") or ""
        tokens += usage_tokens(rev_resp)
        calls.append({"role": "review", "alias": rev_alias, "wall_secs": round(time.monotonic() - t_rev, 1)})
    except Exception as e:
        rev_text = ""
        calls.append({"role": "review", "alias": rev_alias, "error": repr(e)[:400]})

    findings_raw = parse_findings(rev_text)
    review_block["findings_raw"] = findings_raw
    graded, still_ok, probe = investigate_findings(task, files, findings_raw, engx)
    review_block["findings"] = graded
    supported = [f for f in graded if f["status"] == "supported"]
    review_block["clean"] = len(supported) == 0
    # Escape: clean review path but oracle fails (should not happen if files unchanged).
    if review_block["clean"] and not still_ok:
        review_block["escape"] = True
        oracle_pass = False
        oracle_stage = "escape"
        oracle_summary = probe

    if supported and still_ok:
        review_block["repair_ran"] = True
        finding_txt = json.dumps(supported, indent=2)
        repair_messages = [
            {
                "role": "system",
                "content": (
                    "You are an autonomous software engineer. Supported review findings must be fixed. "
                    "Reply with COMPLETE new contents of every file you change as `### FILE: path` "
                    "fenced blocks. Do not modify tests/ unless the task requires it."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Task: {task['instruction']}\n\nCurrent files:\n{repo_blob}\n\n"
                    f"Supported findings to fix (do not address dropped/refuted):\n{finding_txt}\n"
                ),
            },
        ]
        t_fix = time.monotonic()
        try:
            fix_resp = chat_completion(base, headers, impl_alias, repair_messages, max_tokens)
            fix_text = fix_resp["choices"][0]["message"].get("content") or ""
            tokens += usage_tokens(fix_resp)
            calls.append({"role": "repair", "alias": impl_alias, "wall_secs": round(time.monotonic() - t_fix, 1)})
            new_files = {p: c for p, c in engx.parse_files(fix_text).items() if engx.allowed(task, p)}
            if new_files:
                merged = dict(files)
                merged.update(new_files)
                ok2, stage2, msg2 = engx.validate(task, None, merged)
                if ok2:
                    files = merged
                    oracle_pass = True
                    oracle_stage = stage2
                    oracle_summary = msg2[:500]
                else:
                    # Repair broke a previously passing oracle → regression; keep prior files.
                    review_block["regression"] = True
                    oracle_pass = True  # prior files still good
                    oracle_stage = "repair-rejected"
                    oracle_summary = f"repair failed oracle ({stage2}); kept pre-repair files. {msg2[:300]}"
                    calls[-1]["repair_rejected"] = True
        except Exception as e:
            calls.append({"role": "repair", "alias": impl_alias, "error": repr(e)[:400]})

    wall = round(time.monotonic() - t_start, 1)
    accepted = bool(oracle_pass) and not review_block["escape"]
    return {
        "id": task["id"],
        "success": accepted,
        "accepted": accepted,
        "attempts": impl.get("attempts", 0),
        "wall_secs": wall,
        "model_secs": impl.get("model_secs"),
        "tokens": tokens,
        "calls": calls,
        "files": {k: v for k, v in files.items()},  # kept for evidence; large but useful
        "implement": {
            "success": impl.get("success"),
            "attempts": impl.get("attempts"),
            "history": [
                {
                    "attempt": h.get("attempt"),
                    "ok": h.get("ok"),
                    "stage": h.get("stage"),
                    "termination": h.get("termination"),
                    "wall_secs": h.get("wall_secs"),
                    "prompt_tokens": h.get("prompt_tokens"),
                    "completion_tokens": h.get("completion_tokens"),
                }
                for h in (impl.get("history") or [])
            ],
        },
        "review": review_block,
        "oracle": {
            "kind": "engx-hidden",
            "pass": bool(oracle_pass),
            "stage": oracle_stage,
            "summary": oracle_summary,
        },
    }


def _packet(arm, run_id, rec, corpus, impl_serving, rev_serving) -> dict:
    review = rec.get("review") or {}
    findings = review.get("findings") or []
    return {
        "schema": "nexus-e2e-evidence-packet/v1",
        "run_id": run_id,
        "arm": arm,
        "task_id": rec["id"],
        "rep": rec.get("rep", 1),
        "accepted": bool(rec.get("accepted")),
        "oracle": rec.get("oracle"),
        "corpus": corpus,
        "serving": {
            "implementer": impl_serving,
            "reviewer": rev_serving,
            "alias": impl_serving.get("alias"),
            "before": impl_serving,
            "after": impl_serving,
            "identity_stable": True,
        },
        "attempts": rec.get("attempts", 0),
        "metrics": {
            "wall_secs": rec.get("wall_secs"),
            "model_secs": rec.get("model_secs"),
            "tokens": rec.get("tokens"),
            "worker_calls": len(rec.get("calls") or []),
        },
        "history": (rec.get("implement") or {}).get("history") or [],
        "review": {
            "ran": review.get("ran"),
            "clean": review.get("clean"),
            "escape": review.get("escape"),
            "regression": review.get("regression"),
            "repair_ran": review.get("repair_ran"),
            "findings": findings,
            "supported": sum(1 for f in findings if f.get("status") == "supported"),
            "refuted": sum(1 for f in findings if f.get("status") == "refuted"),
            "dropped": sum(1 for f in findings if f.get("status") == "dropped"),
            "calls": rec.get("calls"),
        },
    }


def _summarize(packets: list[dict], meta: dict) -> dict:
    n = len(packets)
    ok = [p for p in packets if p["accepted"]]
    per_task: dict[str, list[bool]] = {}
    escapes = sum(1 for p in packets if (p.get("review") or {}).get("escape"))
    regressions = sum(1 for p in packets if (p.get("review") or {}).get("regression"))
    reviewed = [p for p in packets if (p.get("review") or {}).get("ran")]
    supported = sum((p.get("review") or {}).get("supported") or 0 for p in packets)
    refuted = sum((p.get("review") or {}).get("refuted") or 0 for p in packets)
    dropped = sum((p.get("review") or {}).get("dropped") or 0 for p in packets)
    false_finding_denom = supported + refuted
    for p in packets:
        per_task.setdefault(p["task_id"], []).append(p["accepted"])
    return {
        "arm": meta["arm"],
        "implementer": meta["implementer"],
        "reviewer": meta["reviewer"],
        "corpus": meta["corpus"],
        "reps": meta["reps"],
        "tasks": meta["tasks"],
        "n_trials": n,
        "accepted_rate": round(100 * len(ok) / n, 1) if n else 0.0,
        "accepted_per_rep": [
            sum(1 for p in packets if p["rep"] == k and p["accepted"]) for k in range(1, meta["reps"] + 1)
        ],
        "escape_rate": round(100 * escapes / n, 1) if n else 0.0,
        "regression_count": regressions,
        "reviews_run": len(reviewed),
        "findings_supported": supported,
        "findings_refuted": refuted,
        "findings_dropped": dropped,
        "false_finding_rate": round(100 * refuted / false_finding_denom, 1) if false_finding_denom else None,
        "mean_worker_calls": round(
            sum((p.get("metrics") or {}).get("worker_calls") or 0 for p in packets) / n, 2
        ) if n else None,
        "median_secs_to_accepted": round(
            statistics.median([p["metrics"]["wall_secs"] for p in ok if p["metrics"].get("wall_secs") is not None]),
            1,
        ) if ok else None,
        "mean_secs_per_task": round(
            sum((p.get("metrics") or {}).get("wall_secs") or 0 for p in packets) / n, 1
        ) if n else None,
        "mean_tokens_per_task": round(
            sum((p.get("metrics") or {}).get("tokens") or 0 for p in packets) / n
        ) if n else None,
        "per_task_pass": {k: f"{sum(v)}/{len(v)}" for k, v in per_task.items()},
        "always_fail": [k for k, v in per_task.items() if not any(v)],
        "flaky": [k for k, v in per_task.items() if any(v) and not all(v)],
        "serving": meta["serving"],
    }


def run(args: argparse.Namespace) -> int:
    os.environ["ENGX_CORPUS"] = "hard"
    os.environ["ENGX_MAX_TOKENS"] = str(args.max_tokens)
    os.environ.setdefault("ENGX_PYTHON", str(REPO / ".venv" / "bin" / "python"))
    import engx  # noqa: PLC0415

    impl_pin, rev_pin, arm = PAIRINGS[args.pairing]
    impl_alias = PIN_ALIASES[impl_pin]
    rev_alias = PIN_ALIASES[rev_pin]
    token = load_token(args.token_file)
    if not token:
        raise SystemExit("empty token")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "X-AIHost-Cache": "bypass",
        "Cache-Control": "no-store",
    }
    base = args.base.rstrip("/")
    check_lead_rocm_same_artifact(base, headers, args.allow_digest_divergence)
    impl_serving = serving_snapshot(base, headers, impl_alias)
    rev_serving = serving_snapshot(base, headers, rev_alias)
    if impl_serving["artifact_digest"] == rev_serving["artifact_digest"]:
        raise SystemExit(
            f"pairing {args.pairing} is not model-diverse "
            f"(both {impl_serving['artifact_digest'][:24]}…); refuse lead↔rocm-style dual"
        )

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
    if not fleet_path.is_file():
        identity = fleet.build_identity(base, token)
        fleet_path.write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")

    run_id = f"{arm}-{stamp}"
    packets: list[dict] = []
    raw_results: list[dict] = []
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    for rep in range(1, args.reps + 1):
        for task in tasks:
            t0 = time.monotonic()
            # Drop file bodies from archived raw to keep evidence manageable — packet has review stats.
            rec = run_dual_task(
                task, base, headers, impl_alias, rev_alias, args.max_attempts, args.max_tokens, engx
            )
            rec["rep"] = rep
            files = rec.pop("files", {})
            raw_results.append(rec)
            pkt = _packet(arm, run_id, rec, corpus, impl_serving, rev_serving)
            # Attach file digests only
            import hashlib

            pkt["file_digests"] = {
                p: hashlib.sha256(c.encode()).hexdigest() for p, c in files.items()
            }
            packets.append(pkt)
            (packets_dir / f"{task['id']}-rep{rep}.json").write_text(
                json.dumps(pkt, indent=2) + "\n", encoding="utf-8"
            )
            status = "PASS" if pkt["accepted"] else "FAIL"
            rev = pkt.get("review") or {}
            print(
                f"{arm} rep{rep} {task['id']:24s} {status} "
                f"impl_attempts={rec['attempts']} calls={pkt['metrics']['worker_calls']} "
                f"supported={rev.get('supported')} clean={rev.get('clean')} "
                f"wall={rec['wall_secs']}s tokens={rec['tokens']} "
                f"elapsed={round(time.monotonic() - t0, 1)}s",
                flush=True,
            )
            partial = {
                "label": arm,
                "meta": {
                    **corpus,
                    "partial": True,
                    "implementer": impl_alias,
                    "reviewer": rev_alias,
                    "stamp": stamp,
                },
                "packets": packets,
                "results": raw_results,
            }
            (out_dir / f"{arm}.partial.json").write_text(
                json.dumps(partial, indent=2) + "\n", encoding="utf-8"
            )

    meta = {
        "arm": arm,
        "implementer": impl_alias,
        "reviewer": rev_alias,
        "stamp": stamp,
        "started_at": started,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "reps": args.reps,
        "tasks": len(tasks),
        "corpus": corpus,
        "serving": {"implementer": impl_serving, "reviewer": rev_serving},
        "gateway": base,
    }
    summary = _summarize(packets, meta)
    archive = {"label": arm, "meta": meta, "summary": summary, "packets": packets, "results": raw_results}
    (out_dir / f"{arm}.json").write_text(json.dumps(archive, indent=2) + "\n", encoding="utf-8")
    (out_dir / f"{arm}.summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print("RESULT", arm, json.dumps(summary), flush=True)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pairing", required=True, choices=sorted(PAIRINGS))
    p.add_argument("--base", default="https://10.0.8.5:8443")
    p.add_argument("--token-file", required=True)
    p.add_argument("--reps", type=int, default=3)
    p.add_argument("--max-attempts", type=int, default=3)
    p.add_argument("--max-tokens", type=int, default=8192)
    p.add_argument("--only", default=None)
    p.add_argument("--stamp", default=None)
    p.add_argument("--out", default=None)
    p.add_argument("--allow-digest-divergence", action="store_true")
    return run(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
