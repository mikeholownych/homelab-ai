#!/usr/bin/env python3
"""Compute pairwise complementarity (beta = joint all-fail rate) and solved-set overlap across nexus_e2e packet files."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class ArmPackets:
    def __init__(
        self,
        label: str,
        path: Path,
        trials: dict[tuple[str, int], bool],
        per_task: dict[str, list[bool]],
    ) -> None:
        self.label = label
        self.path = path
        self.trials = trials
        self.per_task = per_task

    @property
    def n_trials(self) -> int:
        return len(self.trials)

    @property
    def n_accepted(self) -> int:
        return sum(1 for ok in self.trials.values() if ok)

    @property
    def accepted_rate(self) -> float:
        return round(100.0 * self.n_accepted / self.n_trials, 1) if self.n_trials else 0.0


def load_arm_packets(spec: str) -> ArmPackets:
    if "=" in spec:
        label, raw_path = spec.split("=", 1)
        path = Path(raw_path)
    else:
        path = Path(spec)
        label = path.stem
    payload = json.loads(path.read_text(encoding="utf-8"))
    packets = payload.get("packets")
    if not isinstance(packets, list):
        raise SystemExit(f"{path} has no 'packets' list")
    if "=" not in spec and payload.get("arm"):
        label = str(payload["arm"])
    trials: dict[tuple[str, int], bool] = {}
    per_task: dict[str, list[bool]] = {}
    for pkt in packets:
        task_id = str(pkt["task_id"])
        rep = int(pkt.get("rep", 1))
        ok = bool(pkt.get("accepted"))
        trials[(task_id, rep)] = ok
        per_task.setdefault(task_id, []).append(ok)
    return ArmPackets(label=label, path=path, trials=trials, per_task=per_task)


def pair_trial_metrics(a: ArmPackets, b: ArmPackets) -> dict[str, Any]:
    shared_keys = sorted(set(a.trials) & set(b.trials))
    if not shared_keys:
        return {
            "arm_a": a.label,
            "arm_b": b.label,
            "n_shared": 0,
            "both_pass": 0,
            "only_a": 0,
            "only_b": 0,
            "both_fail": 0,
            "beta": None,
            "union_pass_rate": None,
            "arm_a_shared_rate": None,
            "arm_b_shared_rate": None,
            "only_a_keys": [],
            "only_b_keys": [],
            "both_fail_keys": [],
        }
    both_pass = 0
    only_a_keys: list[str] = []
    only_b_keys: list[str] = []
    both_fail_keys: list[str] = []
    for task_id, rep in shared_keys:
        ok_a = a.trials[(task_id, rep)]
        ok_b = b.trials[(task_id, rep)]
        tag = f"{task_id}#rep{rep}"
        if ok_a and ok_b:
            both_pass += 1
        elif ok_a and not ok_b:
            only_a_keys.append(tag)
        elif ok_b and not ok_a:
            only_b_keys.append(tag)
        else:
            both_fail_keys.append(tag)
    n = len(shared_keys)
    only_a = len(only_a_keys)
    only_b = len(only_b_keys)
    both_fail = len(both_fail_keys)
    return {
        "arm_a": a.label,
        "arm_b": b.label,
        "n_shared": n,
        "both_pass": both_pass,
        "only_a": only_a,
        "only_b": only_b,
        "both_fail": both_fail,
        "beta": round(both_fail / n, 4),
        "union_pass_rate": round(100.0 * (n - both_fail) / n, 1),
        "arm_a_shared_rate": round(100.0 * (both_pass + only_a) / n, 1),
        "arm_b_shared_rate": round(100.0 * (both_pass + only_b) / n, 1),
        "only_a_keys": only_a_keys,
        "only_b_keys": only_b_keys,
        "both_fail_keys": both_fail_keys,
    }


def pair_task_any_metrics(a: ArmPackets, b: ArmPackets) -> dict[str, Any]:
    shared_tasks = sorted(set(a.per_task) & set(b.per_task))
    if not shared_tasks:
        return {
            "arm_a": a.label,
            "arm_b": b.label,
            "n_shared_tasks": 0,
            "both_ever_pass": 0,
            "only_a_ever": [],
            "only_b_ever": [],
            "neither_ever": [],
            "task_beta": None,
            "task_union_rate": None,
        }
    both_ever = 0
    only_a_ever: list[str] = []
    only_b_ever: list[str] = []
    neither_ever: list[str] = []
    for task_id in shared_tasks:
        ok_a = any(a.per_task[task_id])
        ok_b = any(b.per_task[task_id])
        if ok_a and ok_b:
            both_ever += 1
        elif ok_a and not ok_b:
            only_a_ever.append(task_id)
        elif ok_b and not ok_a:
            only_b_ever.append(task_id)
        else:
            neither_ever.append(task_id)
    n = len(shared_tasks)
    return {
        "arm_a": a.label,
        "arm_b": b.label,
        "n_shared_tasks": n,
        "both_ever_pass": both_ever,
        "only_a_ever": only_a_ever,
        "only_b_ever": only_b_ever,
        "neither_ever": neither_ever,
        "task_beta": round(len(neither_ever) / n, 4),
        "task_union_rate": round(100.0 * (n - len(neither_ever)) / n, 1),
    }


def compute_report(arms: list[ArmPackets]) -> dict[str, Any]:
    arm_rows = [
        {
            "arm": arm.label,
            "source": str(arm.path),
            "tasks": len(arm.per_task),
            "n_trials": arm.n_trials,
            "accepted": arm.n_accepted,
            "accepted_rate": arm.accepted_rate,
            "per_task": {
                t: f"{sum(1 for ok in vals if ok)}/{len(vals)}"
                for t, vals in sorted(arm.per_task.items())
            },
        }
        for arm in arms
    ]
    trial_pairs: list[dict[str, Any]] = []
    task_pairs: list[dict[str, Any]] = []
    for i in range(len(arms)):
        for j in range(i + 1, len(arms)):
            trial_pairs.append(pair_trial_metrics(arms[i], arms[j]))
            task_pairs.append(pair_task_any_metrics(arms[i], arms[j]))
    return {
        "schema": "nexus-e2e-complementarity/v1",
        "arms": arm_rows,
        "pairwise_trials": trial_pairs,
        "pairwise_tasks_any_rep": task_pairs,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Pairwise complementarity (β) and solved-set overlap",
        "",
        "Definition: `β = both_fail / n_shared` on paired `(task_id, rep)` trials; `union % = 100 * (1 - β)`.",
        "",
        "## Evaluated arms",
        "",
        "| Arm | Tasks | Trials | Accepted | Accepted % |",
        "|-----|-------|--------|----------|------------|",
    ]
    for row in report["arms"]:
        lines.append(
            f"| {row['arm']} | {row['tasks']} | {row['n_trials']} | {row['accepted']} | {row['accepted_rate']} |"
        )

    lines += [
        "",
        "## Pairwise trial overlap (paired `(task_id, rep)`)",
        "",
        "| Pair (A vs B) | Shared | A % | B % | Both pass | Only A | Only B | Both fail | β (all-fail) | Union % |",
        "|---------------|--------|-----|-----|-----------|--------|--------|-----------|--------------|---------|",
    ]
    for pair in report["pairwise_trials"]:
        if pair["n_shared"] == 0:
            continue
        lines.append(
            f"| {pair['arm_a']} vs {pair['arm_b']} | {pair['n_shared']} | "
            f"{pair['arm_a_shared_rate']} | {pair['arm_b_shared_rate']} | "
            f"{pair['both_pass']} | {pair['only_a']} | {pair['only_b']} | "
            f"{pair['both_fail']} | {pair['beta']:.4f} | {pair['union_pass_rate']} |"
        )

    lines += [
        "",
        "### Unique solves by trial",
        "",
    ]
    for pair in report["pairwise_trials"]:
        if pair["n_shared"] == 0:
            continue
        only_a_str = ", ".join(pair["only_a_keys"]) or "—"
        only_b_str = ", ".join(pair["only_b_keys"]) or "—"
        both_fail_str = ", ".join(pair["both_fail_keys"]) or "—"
        lines.append(
            f"- **{pair['arm_a']} vs {pair['arm_b']}** (n={pair['n_shared']}): "
            f"only `{pair['arm_a']}`=[{only_a_str}]; only `{pair['arm_b']}`=[{only_b_str}]; "
            f"both fail=[{both_fail_str}]"
        )

    lines += [
        "",
        "## Task-level ever-solved overlap (across all reps per arm)",
        "",
        "| Pair (A vs B) | Shared tasks | Both ever | Only A ever | Only B ever | Neither ever | Task β | Task union % |",
        "|---------------|--------------|-----------|-------------|-------------|--------------|--------|--------------|",
    ]
    for pair in report["pairwise_tasks_any_rep"]:
        if pair["n_shared_tasks"] == 0:
            continue
        lines.append(
            f"| {pair['arm_a']} vs {pair['arm_b']} | {pair['n_shared_tasks']} | "
            f"{pair['both_ever_pass']} | {', '.join(pair['only_a_ever']) or '—'} | "
            f"{', '.join(pair['only_b_ever']) or '—'} | {', '.join(pair['neither_ever']) or '—'} | "
            f"{pair['task_beta']:.4f} | {pair['task_union_rate']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--arm",
        action="append",
        required=True,
        help="Arm packet file as label=path/to/arm.json or path/to/arm.json",
    )
    ap.add_argument("--out-dir", required=True, type=Path)
    args = ap.parse_args()
    arms = [load_arm_packets(spec) for spec in args.arm]
    report = compute_report(arms)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_dest = args.out_dir / "complementarity.json"
    md_dest = args.out_dir / "complementarity.md"
    json_dest.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md_dest.write_text(render_markdown(report), encoding="utf-8")
    print(f"wrote {json_dest} and {md_dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
