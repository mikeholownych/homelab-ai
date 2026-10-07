#!/usr/bin/env python3
"""Phase A/B report: per-run serving evidence, condition comparison and failure classification.

usage: report.py <run.json> [<run.json> ...]     (each file's meta.condition, or --condition label=COND, names its condition)

Classification of every failed attempt (and of each failed task-run by its final attempt):
  MODEL_CAPABILITY               the model emitted a valid final answer that the validators rejected, or finished normally
                                 (finish=stop) without a usable answer (did not follow the output contract)
  REASONING_BUDGET_EXHAUSTION    bounded condition: the reasoning budget was reached and no valid final answer followed
  SERVING_CONFIGURATION_FAILURE  generation was cut by a serving ceiling (finish=length: output/context limit) before a valid
                                 answer, or the request failed (context limit, timeout, HTTP error)
Fields the run did not record (runs made before the 2026-10-07 instrumentation) are shown as "n/r", never estimated."""
import json
import statistics
import sys
from collections import Counter

MC, RBE, SCF = "MODEL_CAPABILITY", "REASONING_BUDGET_EXHAUSTION", "SERVING_CONFIGURATION_FAILURE"


def attempt_class(h, bounded):
    if "error" in h:
        return SCF
    valid = h.get("valid_final_answer", h.get("stage") != "format")
    if valid:
        return None if h.get("ok") else MC
    if bounded and h.get("budget_reached"):
        return RBE
    if h.get("finish") == "length" or h.get("termination") == "output_limit":
        return SCF
    return MC


def fmt(v, unit=""):
    if v is None:
        return "n/r"
    return f"{v:.0f}{unit}" if isinstance(v, float) else f"{v}{unit}"


def med(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def load(path, override):
    d = json.load(open(path))
    cond = override.get(d["label"]) or d.get("meta", {}).get("condition") or "UNLABELLED"
    return d, cond


def run_section(d, cond):
    bounded = cond.startswith("THINKING_ON_BOUNDED")
    res = d["results"]
    lines = [f"### {d['label']} - {cond}" + (" (PARTIAL)" if d.get("meta", {}).get("partial") else ""),
             f"model `{d.get('meta', {}).get('model')}`, max_tokens {d.get('meta', {}).get('max_tokens')}, "
             f"reasoning_budget {d.get('meta', {}).get('reasoning_budget')}, task-runs {len(res)}",
             "",
             "| task | rep | pass | attempts | wall s | TTFT ms (med) | reasoning tok (max) | answer tok (max) | budget reached | "
             "valid answer | validator (last) | termination (last) | failure class |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    terminal, per_attempt = Counter(), Counter()
    for r in res:
        hs = r["history"]
        classes = [attempt_class(h, bounded) for h in hs]
        for c in classes:
            if c:
                per_attempt[c] += 1
        last = hs[-1] if hs else {}
        tclass = "" if r["success"] else (classes[-1] if classes else SCF)
        if tclass:
            terminal[tclass] += 1
        rt = [h.get("reasoning_tokens") for h in hs]
        at = [h.get("answer_tokens") for h in hs]
        br = [h.get("budget_reached") for h in hs if "budget_reached" in h]
        lines.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
            r["id"], r.get("rep"), "PASS" if r["success"] else "FAIL", r["attempts"], fmt(r.get("wall_secs")),
            fmt(med([h.get("ttft_ms_est") for h in hs])),
            fmt(max([x for x in rt if x is not None], default=None)), fmt(max([x for x in at if x is not None], default=None)),
            ("yes" if any(br) else "no") if br and None not in br else "n/r",
            "yes" if any(h.get("valid_final_answer", h.get("stage") != "format") for h in hs if "error" not in h) else "no",
            last.get("stage", "error"), last.get("termination") or last.get("finish") or last.get("error", "")[:30], tclass or "-"))
    n = len(res)
    passed = sum(r["success"] for r in res)
    lines += ["", f"validated {passed}/{n} ({100 * passed / n:.1f}%); failed task-runs by terminal class: {dict(terminal)}; "
              f"failed attempts by class: {dict(per_attempt)}", ""]
    return lines, {"label": d["label"], "cond": cond, "passed": passed, "n": n, "terminal": terminal,
                   "reasoning": [h.get("reasoning_tokens") for r in res for h in r["history"] if h.get("reasoning_tokens") is not None],
                   "budget_hits": sum(1 for r in res for h in r["history"] if h.get("budget_reached")),
                   "attempts": sum(len(r["history"]) for r in res),
                   "wall_med": med([r.get("wall_secs") for r in res])}


def main(argv):
    override, paths = {}, []
    i = 0
    while i < len(argv):
        if argv[i] == "--condition":
            k, v = argv[i + 1].split("=", 1)
            override[k] = v
            i += 2
        else:
            paths.append(argv[i])
            i += 1
    out, summ = ["# engx Phase A/B report", ""], []
    for p in paths:
        d, cond = load(p, override)
        lines, s = run_section(d, cond)
        out += lines
        summ.append(s)
    out += ["## Condition comparison (never pooled)", "",
            "| run | condition | validated | median wall s/task-run | attempts | budget hits | reasoning tok p50 / p90 / max | "
            "failed: MODEL_CAPABILITY / REASONING_BUDGET_EXHAUSTION / SERVING_CONFIGURATION_FAILURE |",
            "|---|---|---|---|---|---|---|---|"]
    for s in summ:
        rs = sorted(s["reasoning"])
        dist = f"{rs[len(rs) // 2]} / {rs[int(len(rs) * 0.9)]} / {rs[-1]}" if rs else "n/r"
        t = s["terminal"]
        out.append(f"| {s['label']} | {s['cond']} | {s['passed']}/{s['n']} ({100 * s['passed'] / s['n']:.1f}%) | {fmt(s['wall_med'])} | "
                   f"{s['attempts']} | {s['budget_hits']} | {dist} | {t.get(MC, 0)} / {t.get(RBE, 0)} / {t.get(SCF, 0)} |")
    print("\n".join(out))


if __name__ == "__main__":
    main(sys.argv[1:])
