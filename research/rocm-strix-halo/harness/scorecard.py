#!/usr/bin/env python3
"""Weighted scorecard for the Strix Halo deep bake-off (Phase 2c).

Usage: scorecard.py <evidence/<ts>/deep> [-o scorecard.md]

Reads  <deep>/<engine>/<model>/metrics.jsonl  (one JSON object per line, ``kind``
in cold_ttft | batch | warm_ttft | quality | ops | run) and writes a markdown
table of weighted scores.

Axes and normalization (every axis ends up in 0..1, higher is better):

* quality  fraction of quality probes passed (already 0..1).
* ops      ops-checklist items passed / total (already 0..1).
* ttft     geometric mean (seconds) of every cold TTFT point and the warm-prefix
           TTFT, then ``norm_lower_better`` = best / value, where *best* is the
           lowest value among the engines run on the same model.
* tok_s    mean aggregate decode tok/s over the batch levels, then
           ``norm_higher_better`` = value / best among the engines on that model.

Ratio-to-best is used (not min-max) so a two-engine field does not collapse to
1.0 / 0.0. Normalization is per *model*: tok/s and TTFT are not comparable across
different models. A run missing any axis is reported as ``incomplete`` and gets
no score: absent data is never scored as zero.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Mapping, Optional, Sequence

DEFAULT_WEIGHTS: dict[str, float] = {"quality": 0.30, "ttft": 0.30, "tok_s": 0.20, "ops": 0.20}
AXES = tuple(DEFAULT_WEIGHTS)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def norm_lower_better(value: float, best: float) -> float:
    """Ratio-to-best for lower-is-better metrics (latency): best/value in 0..1."""
    if value <= 0:
        return 1.0
    return _clamp01(best / value)


def norm_higher_better(value: float, best: float) -> float:
    """Ratio-to-best for higher-is-better metrics (throughput): value/best in 0..1."""
    if best <= 0:
        return 0.0
    return _clamp01(value / best)


def score(axes: Mapping[str, float], weights: Mapping[str, float]) -> float:
    """Weighted sum of 0..1 axes. Axes are clamped to 0..1; a missing axis raises KeyError."""
    total = sum(weights.values())
    if total <= 0:
        raise ValueError("weights must have a positive sum")
    return sum(_clamp01(axes[name]) * w for name, w in weights.items()) / total


def _geomean(values: Sequence[float]) -> Optional[float]:
    vals = [v for v in values if v and v > 0]
    if not vals:
        return None
    return math.exp(sum(math.log(v) for v in vals) / len(vals))


def summarize_metrics(rows: Sequence[Mapping]) -> dict[str, Optional[float]]:
    """Reduce one run's metric rows to raw axes (quality/ops 0..1; ttft s; tok_s). Missing -> None."""
    quality = [r for r in rows if r.get("kind") == "quality"]
    ttfts = [r.get("ttft_s") for r in rows if r.get("kind") in ("cold_ttft", "warm_ttft")]
    toks = [r["aggregate_tok_s"] for r in rows if r.get("kind") == "batch" and r.get("aggregate_tok_s")]
    ops = [r for r in rows if r.get("kind") == "ops"]
    ops_total = sum(r.get("items_total", 0) for r in ops)
    return {
        "quality": (sum(1 for r in quality if r.get("pass")) / len(quality)) if quality else None,
        "ttft": _geomean([t for t in ttfts if t]),
        "tok_s": (sum(toks) / len(toks)) if toks else None,
        "ops": (sum(r.get("items_pass", 0) for r in ops) / ops_total) if ops_total else None,
    }


def collect_runs(deep_dir: Path) -> list[dict]:
    """Load every <engine>/<model>/metrics.jsonl under deep_dir."""
    runs = []
    for path in sorted(Path(deep_dir).glob("*/*/metrics.jsonl")):
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        runs.append({"engine": path.parent.parent.name, "model": path.parent.name,
                     "raw": summarize_metrics(rows), "rows": rows})
    return runs


def build_scorecard(runs: Sequence[Mapping], weights: Mapping[str, float] = DEFAULT_WEIGHTS) -> list[dict]:
    """Normalize per model and score. Incomplete runs get score None."""
    complete = [r for r in runs if all(r["raw"].get(a) is not None for a in AXES)]
    best: dict[str, dict[str, float]] = {}
    for r in complete:
        b = best.setdefault(r["model"], {"ttft": math.inf, "tok_s": 0.0})
        b["ttft"] = min(b["ttft"], r["raw"]["ttft"])
        b["tok_s"] = max(b["tok_s"], r["raw"]["tok_s"])
    table = []
    for r in runs:
        entry = {"engine": r["engine"], "model": r["model"], "raw": r["raw"], "axes": None, "score": None}
        if r in complete:
            b = best[r["model"]]
            axes = {
                "quality": r["raw"]["quality"],
                "ttft": norm_lower_better(r["raw"]["ttft"], b["ttft"]),
                "tok_s": norm_higher_better(r["raw"]["tok_s"], b["tok_s"]),
                "ops": r["raw"]["ops"],
            }
            entry["axes"] = axes
            entry["score"] = score(axes, weights)
        else:
            entry["missing"] = [a for a in AXES if r["raw"].get(a) is None]
        table.append(entry)
    return table


def _fmt(v, nd=2):
    return "n/a" if v is None else f"{v:.{nd}f}"


def render_markdown(table: Sequence[Mapping], weights: Mapping[str, float] = DEFAULT_WEIGHTS) -> str:
    lines = [
        "# Strix Halo deep bake-off scorecard",
        "",
        "Weights: " + ", ".join(f"{k} {v:.2f}" for k, v in weights.items()) + ".",
        "Axes are 0-1, higher is better; TTFT and tok/s are ratio-to-best **within the same model**",
        "(see `harness/scorecard.py`). Engines run different artifacts of the same model "
        "(llama.cpp GGUF vs vLLM FP8), so this compares engine+artifact pairs, not engines alone.",
        "",
        "| engine | model | score | quality | ttft (norm) | tok/s (norm) | ops | "
        "ttft geomean s | mean agg tok/s |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for e in sorted(table, key=lambda e: (e["model"], -(e["score"] if e["score"] is not None else -1))):
        ax, raw = e["axes"], e["raw"]
        if ax:
            cells = [_fmt(e["score"], 3), _fmt(ax["quality"]), _fmt(ax["ttft"]), _fmt(ax["tok_s"]), _fmt(ax["ops"])]
        else:
            cells = ["incomplete", _fmt(raw["quality"]), "n/a", "n/a", _fmt(raw["ops"])]
        lines.append(f"| {e['engine']} | {e['model']} | " + " | ".join(cells)
                     + f" | {_fmt(raw['ttft'])} | {_fmt(raw['tok_s'], 1)} |")
    inc = [e for e in table if e["score"] is None]
    if inc:
        lines += ["", "Incomplete runs (no score; missing axes): "
                  + "; ".join(f"{e['engine']}/{e['model']} missing {','.join(e.get('missing', []))}" for e in inc)]
    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("deep_dir", type=Path)
    ap.add_argument("-o", "--output", type=Path, default=None, help="default: <deep_dir>/scorecard.md")
    args = ap.parse_args(argv)
    runs = collect_runs(args.deep_dir)
    if not runs:
        print(f"no metrics.jsonl under {args.deep_dir}", file=sys.stderr)
        return 1
    md = render_markdown(build_scorecard(runs))
    (args.output or args.deep_dir / "scorecard.md").write_text(md)
    sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
