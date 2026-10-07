#!/usr/bin/env python3
"""Per-attempt serving statistics for instrumented runs, and a per-task pass matrix across two conditions.
usage: servestats.py <results dir>"""
import json
import os
import statistics as st
import sys

OUT = sys.argv[1] if len(sys.argv) > 1 else "results"
RUNS = {"THINKING_OFF": ["deep-q35-27b-q4km-nothink", "c-q38-27b-q4km", "c-q36-35b-a3b-q4km", "c-flashnext-gsq-1gpu"],
        "BOUNDED_4096": ["b-q35-27b-q4km", "b-q38-27b-q4km", "b-q36-35b-a3b-q4km", "b-flashnext-gsq-64k"]}
NAMES = ["Qwen3.5-27B", "Qwen3.8-27B", "Qwen3.6-35B-A3B", "Flash-Next GSQ"]


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(st.median(xs), 1) if xs else None


def load(label):
    return json.load(open(os.path.join(OUT, f"eng-hard-{label}.json")))


print("| run | attempts | TTFT ms (med) | attempt wall s (med) | reasoning tok (med) | answer tok (med) | budget reached | "
      "valid final answer | output-limit stops | errors | decode tok/s (med) |")
print("|---|---|---|---|---|---|---|---|---|---|---|")
for label in RUNS["BOUNDED_4096"]:
    d = load(label)
    hs = [h for r in d["results"] for h in r["history"]]
    tps = [h["predicted_n"] / (h["predicted_ms"] / 1000) for h in hs if h.get("predicted_ms")]
    print(f"| {label} | {len(hs)} | {med([h.get('ttft_ms_est') for h in hs])} | {med([h.get('wall_secs') for h in hs])} | "
          f"{med([h.get('reasoning_tokens') for h in hs])} | {med([h.get('answer_tokens') for h in hs])} | "
          f"{sum(bool(h.get('budget_reached')) for h in hs)}/{len(hs)} | {sum(bool(h.get('valid_final_answer')) for h in hs)}/{len(hs)} | "
          f"{sum(h.get('termination') == 'output_limit' for h in hs)} | {sum('error' in h for h in hs)} | {med(tps)} |")

print()
print("| task | " + " | ".join(f"{n} OFF / B4096" for n in NAMES) + " |")
print("|---|" + "---|" * len(NAMES))
tab = {}
for cond, labels in RUNS.items():
    for name, label in zip(NAMES, labels):
        for task, v in load(label)["summary"]["per_task_pass"].items():
            tab[(task[:3], name, cond)] = v
for i in range(1, 11):
    t = f"H{i:02d}"
    print(f"| {t} | " + " | ".join(f"{tab.get((t, n, 'THINKING_OFF'), '-')} / {tab.get((t, n, 'BOUNDED_4096'), '-')}" for n in NAMES) + " |")
