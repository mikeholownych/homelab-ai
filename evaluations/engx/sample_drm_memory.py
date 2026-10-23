#!/usr/bin/env python3
"""Bounded read-only DRM memory sampling; no command lines or credentials retained.

Per-client resident memory is not whole-device free memory. Shared allocations
can appear in multiple clients. Keep aggregate GPU metrics as a separate source.
"""
import argparse
import json
import time
from pathlib import Path


def kib(value):
    parts = value.split()
    return int(parts[0]) * (1024 if len(parts) > 1 and parts[1] == "KiB" else 1)


def clients(pid):
    found = {}
    try:
        files = (pid / "fdinfo").iterdir()
        for path in files:
            try:
                fields = dict(line.split(":", 1) for line in path.read_text().splitlines()
                              if line.startswith("drm-"))
            except (OSError, ValueError):
                continue
            device = fields.get("drm-pdev", "").strip()
            client = fields.get("drm-client-id", "").strip()
            if not device or not client:
                continue
            resident = {k: kib(v) for k, v in fields.items() if k.startswith("drm-resident-")}
            found[device, client] = {"pid": int(pid.name), "device": device, "client_id": client,
                                     "resident_bytes": resident}
    except OSError:
        pass
    return list(found.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--seconds", type=int, choices=range(1, 1801), default=300)
    parser.add_argument("--interval", type=float, choices=[0.5, 1.0, 5.0], default=0.5)
    parser.add_argument("--stop-file", required=True, type=Path)
    args = parser.parse_args()
    end, refresh, pids = time.monotonic() + args.seconds, 0, []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", buffering=1) as stream:
        while time.monotonic() < end and not args.stop_file.exists():
            start = time.monotonic()
            if start >= refresh:
                pids = [p for p in Path("/proc").iterdir() if p.name.isdigit() and clients(p)]
                refresh = start + 10
            row = {"timestamp": time.time(), "clients": [c for p in pids for c in clients(p)]}
            metrics = Path("/var/lib/local-ai/metrics/gpu.prom")
            try:
                row["aggregate_metric_age_seconds"] = time.time() - metrics.stat().st_mtime
                row["aggregate_metrics"] = [line for line in metrics.read_text().splitlines()
                                             if line.startswith(("aihost_gpu_vram_", "aihost_gpu_temperature_max_",
                                                                 "aihost_gpu_throttle_"))]
            except OSError:
                pass
            stream.write(json.dumps(row) + "\n")
            time.sleep(max(0, args.interval - (time.monotonic() - start)))


if __name__ == "__main__":
    main()
