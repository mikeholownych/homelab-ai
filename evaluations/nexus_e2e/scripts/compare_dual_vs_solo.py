#!/usr/bin/env python3
"""Write dual_vs_solo.md comparing dual arms to Stage-1 solo baselines."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_summary(evidence: Path, name: str) -> dict | None:
    p = evidence / f"{name}.summary.json"
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--evidence-dir", required=True, type=Path)
    args = ap.parse_args()
    evid = args.evidence_dir
    solo = {
        "solo-deep": load_summary(evid, "solo-deep"),
        "solo-lead": load_summary(evid, "solo-lead"),
        "solo-rocm": load_summary(evid, "solo-rocm"),
    }
    dual = {
        "dual-deep-lead": load_summary(evid, "dual-deep-lead"),
        "dual-lead-deep": load_summary(evid, "dual-lead-deep"),
    }
    missing_solo = [k for k, v in solo.items() if v is None]
    if missing_solo:
        raise SystemExit(f"missing solo summaries: {missing_solo}")
    best_solo_name = max(
        ((k, v["accepted_rate"]) for k, v in solo.items() if v),
        key=lambda kv: kv[1],
    )[0]
    best_rate = solo[best_solo_name]["accepted_rate"]

    lines = [
        "# Dual vs solo (engx-hard)",
        "",
        f"Evidence: `{evid}`",
        "",
        "## Solo baselines (Stage 1)",
        "",
        "| Arm | Accepted % | Always fail | Flaky | Mean secs |",
        "|-----|------------|-------------|-------|-----------|",
    ]
    for name, s in solo.items():
        mark = " **best**" if name == best_solo_name else ""
        lines.append(
            f"| {name}{mark} | {s['accepted_rate']} | "
            f"{', '.join(s.get('always_fail') or []) or '—'} | "
            f"{', '.join(s.get('flaky') or []) or '—'} | "
            f"{s.get('mean_secs_per_task')} |"
        )

    lines += [
        "",
        "## Dual arms (Stage 2)",
        "",
        "| Arm | Accepted % | Escape % | Regressions | Supported / refuted / dropped | Mean calls | Mean secs |",
        "|-----|------------|----------|-------------|-------------------------------|------------|-----------|",
    ]
    decisions = []
    for name, s in dual.items():
        if s is None:
            lines.append(f"| {name} | _(pending)_ | | | | | |")
            continue
        lines.append(
            f"| {name} | {s['accepted_rate']} | {s.get('escape_rate')} | "
            f"{s.get('regression_count')} | "
            f"{s.get('findings_supported')}/{s.get('findings_refuted')}/{s.get('findings_dropped')} | "
            f"{s.get('mean_worker_calls')} | {s.get('mean_secs_per_task')} |"
        )
        delta = round(s["accepted_rate"] - best_rate, 1)
        same_impl = "solo-deep" if "deep-lead" in name else "solo-lead"
        vs_impl = round(s["accepted_rate"] - solo[same_impl]["accepted_rate"], 1)
        decisions.append(
            f"- **{name}**: Δ vs best solo ({best_solo_name} {best_rate}%) = {delta:+}%; "
            f"Δ vs same-implementer {same_impl} ({solo[same_impl]['accepted_rate']}%) = {vs_impl:+}%; "
            f"escape_rate={s.get('escape_rate')}%; regressions={s.get('regression_count')}."
        )

    lines += ["", "## Decision vs Stage-2 criteria", ""]
    if all(dual[k] is None for k in dual):
        lines.append("_Dual runs not finished yet._")
    else:
        lines.extend(decisions)
        lines += [
            "",
            "Promote dual only if accepted rate improves vs best solo, or escapes drop with "
            "accepted rate ≥ best solo − ε (ε=0). Otherwise document as not worth it and do not "
            "build triple without a new decision.",
            "",
        ]
        finished = [dual[k] for k in dual if dual[k] is not None]
        any_improve = any(s["accepted_rate"] > best_rate for s in finished)
        any_worth = any(
            s["accepted_rate"] > best_rate
            or (s.get("escape_rate", 0) < 0 and s["accepted_rate"] >= best_rate)
            or s["accepted_rate"] >= best_rate
            for s in finished
        )
        # clearer verdict
        beats_best = [k for k, s in dual.items() if s and s["accepted_rate"] > best_rate]
        matches_best = [k for k, s in dual.items() if s and s["accepted_rate"] >= best_rate]
        if beats_best:
            lines.append(f"**Verdict:** dual improves on best solo via {', '.join(beats_best)}.")
        elif matches_best and any((dual[k] or {}).get("escape_rate", 1) == 0 for k in matches_best):
            lines.append(
                f"**Verdict:** dual matches best solo on {', '.join(matches_best)} with zero escapes; "
                "check call/time cost before promoting."
            )
        else:
            lines.append(
                "**Verdict:** dual does **not** beat best solo on accepted rate; "
                "do not build Stage 3 triple unless operator overrides."
            )
            _ = any_improve, any_worth

    dest = evid / "dual_vs_solo.md"
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
