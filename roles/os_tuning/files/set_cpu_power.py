#!/usr/bin/env python3
"""Idempotently enforce a CPU governor and energy-performance preference.

Writes scaling_governor / energy_performance_preference for every online CPU.
Compares current values first so repeated runs make no changes. Exits 0 when
state matches, 3 when changes were applied, 1 on failure. --validate mode only
reports whether state already matches (exit 0) or not (exit 4).
"""

import argparse
import json
import sys
from pathlib import Path


def online_cpus():
    base = Path("/sys/devices/system/cpu")
    return sorted(path for path in base.glob("cpu[0-9]*") if (path / "cpufreq").is_dir())


def apply_to_cpus(attribute, value, validate_only):
    changed = 0
    mismatched = []
    cpus = online_cpus()
    if not cpus:
        print(json.dumps({"status": "unavailable", "reason": "no cpufreq-capable CPUs found"}))
        return 1
    for cpu in cpus:
        attribute_path = cpu / "cpufreq" / attribute
        try:
            current = attribute_path.read_text().strip()
        except (OSError, PermissionError) as error:
            print(json.dumps({"status": "unavailable", "reason": f"{attribute_path}: {error}"}))
            return 1
        if current == value:
            continue
        mismatched.append({"cpu": cpu.name, "current": current, "expected": value})
        if not validate_only:
            try:
                attribute_path.write_text(f"{value}\n")
                changed += 1
            except (OSError, PermissionError) as error:
                print(json.dumps({"status": "error", "reason": f"{attribute_path}: {error}"}))
                return 1
    result = {
        "status": "matched" if not mismatched else ("validated-mismatch" if validate_only else "applied"),
        "changed": 0 if validate_only else changed,
        "mismatched": mismatched,
        "cpu_count": len(cpus),
    }
    print(json.dumps(result))
    if mismatched and validate_only:
        return 4
    return 0


def main():
    parser = argparse.ArgumentParser(description="Set CPU governor or EPP across all CPUs")
    parser.add_argument("--governor", default=None)
    parser.add_argument("--epp", default=None)
    parser.add_argument("--validate", action="store_true", help="Only verify; change nothing")
    args = parser.parse_args()
    exit_code = 0
    if args.governor:
        exit_code = max(exit_code, apply_to_cpus("scaling_governor", args.governor, args.validate))
    if args.epp:
        epp_code = apply_to_cpus("energy_performance_preference", args.epp, args.validate)
        exit_code = max(exit_code, epp_code if epp_code != 4 else 4)
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
