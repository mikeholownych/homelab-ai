#!/usr/bin/env python3
"""Worker busy-watchdog executor (controller side). See docs/design/WORKER-BUSY-WATCHDOG.md.

Reads `aihost_engine_stalled_seconds` from the gateway, runs the pure ladder in orchestrator_runtime/watchdog.py, and performs the rungs:
drain (gateway admin API), graceful stop, forced kill, restart (systemd over SSH), readiness check (gateway's own view), undrain.
It never sends workload requests to a worker. DRY-RUN by default: it logs what it would do; pass --apply to act.
The gateway admin token is read from --token-file and is never printed. Every rung is appended to --evidence as one JSON line.

  worker_watchdog.py --base https://10.0.8.5:8443 --ca ~/.config/nexus/t5820-gateway-ca.crt --token-file ~/.config/aihost/watchdog.token \\
      --host 10.0.8.5 --unit worker1=aihost-llama-worker1.service --unit worker2=aihost-llama-worker2.service [--apply] [--once]
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from orchestrator_runtime.watchdog import Action, Ladder, Policy  # noqa: E402

_STALLED = re.compile(r'^aihost_engine_stalled_seconds\{[^}]*worker_id="([^"]+)"[^}]*\}\s+([-+0-9.eE]+)', re.M)
READY_WAIT_S = 300.0


def parse_stalled(text: str) -> dict[str, float]:
    return {m.group(1): float(m.group(2)) for m in _STALLED.finditer(text)}


class Gateway:
    def __init__(self, base: str, ca: str, token: str, timeout: float = 10.0) -> None:
        if not base.startswith("https://"):
            raise ValueError("an authenticated TLS gateway is required")
        self.base, self.timeout = base.rstrip("/"), timeout
        self.context = ssl.create_default_context(cafile=ca)
        self.headers = {"Authorization": "Bearer " + token}

    def _call(self, path: str, method: str = "GET") -> bytes:
        req = urllib.request.Request(self.base + path, headers=self.headers, method=method, data=b"" if method == "POST" else None)
        with urllib.request.urlopen(req, context=self.context, timeout=self.timeout) as r:
            return r.read()

    def stalled(self) -> dict[str, float]:
        return parse_stalled(self._call("/metrics").decode("utf-8", "replace"))

    def drain(self, worker: str) -> bool:
        return json.loads(self._call(f"/admin/workers/{worker}/drain", "POST")).get("status") == "drained"

    def undrain(self, worker: str) -> bool:
        return json.loads(self._call(f"/admin/workers/{worker}/undrain", "POST")).get("status") == "active"

    def ready(self, worker: str) -> bool:
        detail = (json.loads(self._call("/admin/workers")).get("workers") or {}).get(worker) or {}
        return bool(detail.get("capacity")) and not detail.get("blocked_reason")


class Systemd:
    """systemctl on the inference host over SSH (key auth, passwordless sudo for systemctl on the worker units)."""

    def __init__(self, host: str, timeout: float = 90.0) -> None:
        self.host, self.timeout = host, timeout

    def _run(self, *args: str) -> bool:
        try:
            r = subprocess.run(["ssh", "-o", "BatchMode=yes", self.host, "sudo", "-n", "systemctl", *args],
                               capture_output=True, timeout=self.timeout)
            return r.returncode == 0
        except subprocess.TimeoutExpired:
            return False

    def stop(self, unit: str) -> bool:
        return self._run("stop", unit)

    def kill(self, unit: str) -> bool:
        return self._run("kill", "-s", "SIGKILL", unit)

    def restart(self, unit: str) -> bool:
        return self._run("restart", unit)


def run_once(gw, sd, ladder: Ladder, units: dict[str, str], now: float, *, apply: bool, evidence, verify_started: dict[str, float]) -> list[dict]:
    """One pass over every worker: ask the ladder, perform (or just log) the action, report back. Returns the evidence records."""
    stalled = gw.stalled()
    records = []
    for worker, unit in units.items():
        value = stalled.get(worker, 0.0)
        for _ in range(6):  # the rungs after a drain follow each other without waiting for the next poll
            action = ladder.decide(worker, value, now)
            if action is None:
                break
            if action is Action.UNDRAIN and ladder.phase(worker) == "verifying":
                verify_started.setdefault(worker, now)
                # Ready only when the gateway shows a FRESH reading of exactly 0 stalled seconds (a restarted engine answering /metrics
                # again, idle) and its own readiness view agrees. Found in the live rehearsal: right after the restart the gateway still
                # showed the old worker as ready, so readiness alone readmitted it before it was back.
                if apply and not (stalled.get(worker) == 0.0 and gw.ready(worker)):
                    if now - verify_started[worker] > READY_WAIT_S:
                        ladder.abandon(worker, now)
                        records.append({"worker": worker, "action": "abandon", "reason": "never became ready", "ts": now})
                    break
            record = {"worker": worker, "action": action.value, "stalled_s": value, "unit": unit, "applied": apply, "ts": now}
            if not apply:
                records.append(record)
                break  # a dry run reports the next rung only: later rungs depend on this one's outcome
            ok = True
            if action is Action.DRAIN:
                ok = gw.drain(worker)
            elif action is Action.STOP:
                ok = sd.stop(unit)
            elif action is Action.KILL:
                ok = sd.kill(unit)
            elif action is Action.RESTART:
                ok = sd.restart(unit)
                verify_started[worker] = now
            elif action is Action.UNDRAIN:
                ok = gw.undrain(worker)
                value = 0.0
            record["ok"] = ok
            records.append(record)
            ladder.performed(worker, action, now, ok)
            if action in (Action.UNDRAIN, Action.ALERT):
                break
    for r in records:
        evidence(r)
    return records


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True)
    ap.add_argument("--ca", required=True)
    ap.add_argument("--token-file", required=True, type=Path)
    ap.add_argument("--host", required=True, help="inference host for systemctl over SSH")
    ap.add_argument("--unit", action="append", required=True, metavar="WORKER_ID=UNIT")
    ap.add_argument("--stuck-after", type=float, default=120.0)
    ap.add_argument("--drain-wait", type=float, default=30.0)
    ap.add_argument("--max-restarts-per-hour", type=int, default=3)
    ap.add_argument("--interval", type=float, default=15.0)
    ap.add_argument("--evidence", type=Path, default=Path("worker-watchdog-evidence.jsonl"))
    ap.add_argument("--apply", action="store_true", help="act; without it the watchdog only logs the next rung")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--show", action="store_true", help="print the stalled-seconds reading per worker and exit (read-only)")
    args = ap.parse_args()
    units = dict(u.split("=", 1) for u in args.unit)
    gw = Gateway(args.base, args.ca, args.token_file.read_text().strip())
    if args.show:
        print(json.dumps({"stalled_seconds": gw.stalled()}))
        return 0
    sd, verify = Systemd(args.host), {}
    ladder = Ladder(Policy(args.stuck_after, args.drain_wait, args.max_restarts_per_hour))

    def evidence(record: dict) -> None:
        with args.evidence.open("a") as f:
            f.write(json.dumps(record) + "\n")
        print(json.dumps(record), flush=True)

    while True:
        try:
            run_once(gw, sd, ladder, units, time.monotonic(), apply=args.apply, evidence=evidence, verify_started=verify)
        except Exception as error:  # the watchdog must not die on a transient gateway error
            print(json.dumps({"error": type(error).__name__}), flush=True)
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
