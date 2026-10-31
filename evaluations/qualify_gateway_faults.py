"""Explicit single-worker outage drill, with an appliance-side restart watchdog.

Run on the controller after workload probes stop. Credentials on stdin, never saved.
This stops only worker2, restores it in finally, and preserves controller timer state.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

from qualify_single_host import Probe, payload, save

WORKER = 'aihost-llama-worker2.service'
UNITS = ['aihost-orchestrator-gateway.service', 'aihost-llama-worker1.service', WORKER]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ca', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--expected-release', required=True)
    args = parser.parse_args()
    probe = Probe('https://10.0.8.5:8443', args.ca, json.load(sys.stdin), 'mike@10.0.8.5')
    def remote(command: list[str], timeout: int = 30) -> str:
        return subprocess.check_output(['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                                        probe.host, *command], text=True, timeout=timeout)
    def units() -> str:
        return remote(['sudo', '-n', 'systemctl', 'show', *UNITS, '-p', 'Id,MainPID,ActiveEnterTimestamp'])
    def pids(text: str) -> dict[str, str]:
        return {values['Id']: values['MainPID'] for block in text.strip().split('\n\n')
                if (values := dict(line.split('=', 1) for line in block.splitlines()))}
    initial = probe.request('/health?strict=true', 'ansible-admin')
    health = initial.get('body', {})
    assert initial['status'] == 200 and health.get('release_id') == args.expected_release
    assert health['scheduler']['active_work'] == 0 and health['scheduler']['queued_work'] == 0, 'work in flight; drill not started'
    timer_active = subprocess.run(['systemctl', '--user', 'is-active', '--quiet', 'aihost-reconcile.timer']).returncode == 0
    state = subprocess.check_output(['systemctl', '--user', 'show', 'aihost-reconcile.service', '-p', 'ActiveState', '--value'], text=True).strip()
    assert state == 'inactive', 'reconciliation running; drill not started'
    record = {'started_at': datetime.now(timezone.utc).isoformat(), 'release_id': args.expected_release,
              'baseline_units': units(), 'checks': {}, 'passed': False, 'controller_timer_was_active': timer_active}
    watch = 'aihost-qualification-restore-worker2-' + str(int(time.time()))
    watchdog_armed = False
    worker_stopped = False
    restored = False
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        if timer_active:
            subprocess.run(['systemctl', '--user', 'stop', 'aihost-reconcile.timer'], check=True)
        # Check again after disabling new timer starts; never interrupt an existing reconcile.
        assert subprocess.check_output(['systemctl', '--user', 'show', 'aihost-reconcile.service', '-p', 'ActiveState', '--value'], text=True).strip() == 'inactive'
        remote(['sudo', '-n', 'systemd-run', '--unit=' + watch, '--on-active=180s', '/usr/bin/systemctl', 'start', WORKER])
        watchdog_armed = True
        record['watchdog'] = watch
        save(args.output, record)
        worker_stopped = True  # Set before attempting the stop so any uncertain result triggers restoration.
        remote(['sudo', '-n', 'systemctl', 'stop', WORKER], timeout=60)
        started = time.monotonic()
        while time.monotonic() - started < 35:
            current = probe.request('/health?strict=true', 'ansible-admin')
            if current.get('body', {}).get('status') == 'degraded':
                break
            time.sleep(.5)
        h = current.get('body', {})
        record['checks']['degradation'] = {'status': current['status'], 'overall': h.get('status'),
            'ready': h.get('ready'), 'available_workers': h.get('scheduler', {}).get('available_workers'),
            'detection_seconds': time.monotonic() - started}
        assert current['status'] == 503 and h['status'] == 'degraded' and h['ready'] and h['scheduler']['available_workers'] == 1
        normal = probe.request('/health', 'ansible-admin')
        assert normal['status'] == 200
        lead = probe.request('/v1/chat/completions', body=payload('engineering/lead', 'Reply with one word READY.'))
        record['checks']['unaffected_alias'] = {'status': lead['status'], 'seconds': lead['seconds']}
        assert lead['status'] == 200 and lead.get('body', {}).get('choices')
        deep = probe.request('/v1/chat/completions', body=payload('engineering/deep', 'Reply with one word READY.'))
        record['checks']['failed_alias'] = {'status': deep['status'], 'seconds': deep['seconds']}
        assert deep['status'] in (404, 409, 422, 503, 504) and not deep.get('body', {}).get('choices')
        assert deep['seconds'] < 35
    except Exception as error:
        record['error_type'] = type(error).__name__
        raise
    finally:
        try:
            if worker_stopped:
                started = time.monotonic()
                remote(['sudo', '-n', 'systemctl', 'start', WORKER], timeout=30)
                while time.monotonic() - started < 240:
                    current = probe.request('/health?strict=true', 'ansible-admin')
                    if current['status'] == 200 and current.get('body', {}).get('ready'):
                        restored = True
                        break
                    time.sleep(1)
                record['checks']['restoration'] = {'ready': restored, 'seconds': time.monotonic() - started}
                if restored:
                    deep = probe.request('/v1/chat/completions', body=payload('engineering/deep', 'Reply with one word READY.'))
                    restored = deep['status'] == 200 and bool(deep.get('body', {}).get('choices'))
                    record['checks']['restored_alias'] = {'status': deep['status'], 'passed': restored}
                record['final_units'] = units()
                before, after = pids(record['baseline_units']), pids(record['final_units'])
                record['checks']['unaffected_pids_preserved'] = len(before) == len(after) == 3 and all(before[name] == after[name] for name in UNITS[:2])
            if watchdog_armed and restored:
                remote(['sudo', '-n', 'systemctl', 'stop', watch + '.timer'])
        finally:
            if timer_active:
                subprocess.run(['systemctl', '--user', 'start', 'aihost-reconcile.timer'], check=True)
            record['finished_at'] = datetime.now(timezone.utc).isoformat()
            record['passed'] = (restored and 'error_type' not in record
                                and record['checks'].get('unaffected_pids_preserved') is True)
            save(args.output, record)
    print(json.dumps({'passed': record['passed'], 'checks': record['checks']}))
    return 0 if record['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
