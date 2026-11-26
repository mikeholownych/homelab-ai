#!/usr/bin/env python3
"""Aggregate solo-deep / solo-lead / solo-rocm summaries into solo_baselines.json."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ARMS = ("solo-deep", "solo-lead", "solo-rocm")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--evidence-dir", required=True, type=Path)
    args = p.parse_args()
    arms = {}
    missing = []
    for arm in ARMS:
        path = args.evidence_dir / f"{arm}.summary.json"
        if not path.is_file():
            missing.append(arm)
            continue
        arms[arm] = json.loads(path.read_text(encoding="utf-8"))
    if missing:
        raise SystemExit(f"missing summaries: {missing}")
    ranked = sorted(arms.items(), key=lambda kv: (-kv[1]["accepted_rate"], kv[0]))
    best_arm, best = ranked[0]
    out = {
        "schema": "nexus-e2e-solo-baselines/v1",
        "evidence_dir": str(args.evidence_dir),
        "arms": arms,
        "best_solo": {
            "arm": best_arm,
            "accepted_rate": best["accepted_rate"],
            "note": "Accuracy first; wall time / tokens are secondary.",
        },
        "ranking": [{"arm": a, "accepted_rate": s["accepted_rate"]} for a, s in ranked],
    }
    dest = args.evidence_dir / "solo_baselines.json"
    dest.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {dest}")
    print("best_solo", best_arm, best["accepted_rate"])
    for row in out["ranking"]:
        print(f"  {row['arm']}: {row['accepted_rate']}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
