#!/usr/bin/env python3
"""Fail-closed preflight for the T5820 replacement-worker experiment.

This command only inspects state. It never stops B0, starts a worker, or removes
a container. The experiment runner must call it before and after every state
transition and refuse to continue on a failed report.
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable


def run_command(argv: list[str]) -> tuple[int, str]:
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    return result.returncode, result.stdout.strip()


def check_memory(available_bytes: int, reserve_bytes: int) -> tuple[bool, str]:
    if available_bytes < reserve_bytes:
        return False, f"MemAvailable {available_bytes} is below reserve {reserve_bytes}"
    return True, "host memory reserve satisfied"


def check_worker_paths(paths: list[Path], service_user: str) -> list[str]:
    failures: list[str] = []
    try:
        uid = pwd.getpwnam(service_user).pw_uid
    except KeyError:
        return [f"service user does not exist: {service_user}"]
    for path in paths:
        if not path.exists():
            failures.append(f"missing path: {path}")
            continue
        stat = path.stat()
        if stat.st_uid != uid:
            failures.append(f"path owner is not {service_user}: {path}")
        if path.is_dir() and not (stat.st_mode & 0o200):
            failures.append(f"path is not owner-writable: {path}")
    return failures


def inspect(phase: str, *, b0_unit: str, service_user: str, paths: list[Path], reserve_bytes: int, command: Callable[[list[str]], tuple[int, str]] = run_command) -> dict:
    failures = check_worker_paths(paths, service_user)
    active_rc, active = command(["systemctl", "is-active", b0_unit])
    if phase == "before" and (active_rc != 0 or active != "active"):
        failures.append("B0 is not active during before-stop preflight")
    if phase in {"after-stop", "final"} and active == "active":
        failures.append("B0 is still active during stop/final preflight")

    meminfo = Path("/proc/meminfo").read_text(encoding="utf-8")
    match = re.search(r"^MemAvailable:\s+(\d+) kB$", meminfo, re.MULTILINE)
    available = int(match.group(1)) * 1024 if match else 0
    if phase in {"after-stop", "final"}:
        ok, reason = check_memory(available, reserve_bytes)
        if not ok:
            failures.append(reason)

        process_rc, processes = command(["pgrep", "-af", "(?:vllm|conmon|podman|t5820-worker)"])
        if process_rc == 0 and processes:
            failures.append(f"inference process descendants remain: {processes}")
        gpu_rc, gpu = command(["xpu-smi", "discovery"])
        if gpu_rc != 0 or not gpu:
            failures.append("GPU discovery failed")

    return {
        "phase": phase,
        "b0_active": active == "active",
        "mem_available_bytes": available,
        "reserve_bytes": reserve_bytes,
        "failures": failures,
        "passed": not failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("before", "after-stop", "final"), required=True)
    parser.add_argument("--b0-unit", default="vllm.service")
    parser.add_argument("--service-user", default="aihost-runtime")
    parser.add_argument("--reserve-gib", type=int, default=32)
    parser.add_argument("--path", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = inspect(
        args.phase,
        b0_unit=args.b0_unit,
        service_user=args.service_user,
        paths=args.path,
        reserve_bytes=args.reserve_gib * 1024**3,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
