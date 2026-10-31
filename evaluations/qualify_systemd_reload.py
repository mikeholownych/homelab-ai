"""Read-only, complete-journal reload acceptance. Run as root; never initiates a reload."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess

OBSOLETE = re.compile(r'deprecat|support for option .+ has been removed|lacks a native systemd unit file|please update package to include a native systemd unit|unknown (?:key|lvalue)', re.I)


def assess(records, expected_reloads=0):
    warnings, requests, completions = [], [], []
    for row in records:
        message = str(row.get('MESSAGE', ''))
        identifier = row.get('SYSLOG_IDENTIFIER', '')
        if identifier == 'sudo' or row.get('_TRANSPORT') == 'audit':
            continue  # Audit command text is not an emitted runtime diagnostic.
        brief = {k: row[k] for k in ('__REALTIME_TIMESTAMP', '_TRANSPORT', 'SYSLOG_IDENTIFIER', '_COMM', '_PID') if k in row}
        brief['message'] = message
        if OBSOLETE.search(message):
            warnings.append(brief)
        if str(row.get('_PID')) == '1' and message.startswith('Reload requested from client PID'):
            requests.append(brief)
        if str(row.get('_PID')) == '1' and message.startswith('Reloading finished'):
            completions.append(brief)
    return {'expected_reloads': expected_reloads, 'reload_requests': requests, 'reload_completions': completions,
            'obsolete_diagnostics': warnings, 'records_examined': len(records),
            'passed': bool(records) and not warnings and len(requests) == expected_reloads and len(completions) == expected_reloads}


def window(since, until):
    start, end = (datetime.fromisoformat(value.replace('Z', '+00:00')) for value in (since, until))
    if start.tzinfo is None or end.tzinfo is None or not 0 < (end - start).total_seconds() <= 3600:
        raise ValueError('An explicit timezone and a positive window no longer than one hour are required')
    return [value.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f UTC') for value in (start, end)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--since', required=True)
    parser.add_argument('--until', required=True)
    parser.add_argument('--expected-reloads', type=int, choices=range(0, 11), default=0)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Root is required so kernel/system records cannot be silently omitted')
    since, until = window(args.since, args.until)
    journal = subprocess.run(['journalctl', '--utc', '--since', since, '--until', until, '--no-pager', '--output=json'], text=True, capture_output=True, check=True)
    if journal.stderr:
        raise RuntimeError('Journal read emitted diagnostics; complete evidence is not established')
    raw = journal.stdout
    records = [json.loads(line) for line in raw.splitlines() if line]
    result = assess(records, args.expected_reloads)
    result.update(since=args.since, until=args.until, scope='complete journal, all transports; no PID filter')
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'passed': result['passed'], 'reload_requests': len(result['reload_requests']),
                      'reload_completions': len(result['reload_completions']), 'obsolete_diagnostics': len(result['obsolete_diagnostics'])}))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
