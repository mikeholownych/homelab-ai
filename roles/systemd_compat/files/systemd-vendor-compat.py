#!/usr/bin/env python3
"""Regenerate owned XFS unit shadows, removing only ineffective CPUAccounting declarations."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

UNITS = ('xfs_scrub_all.service', 'system-xfs_scrub.slice')
MARKER = b'# Managed by aihost systemd_compat; regenerated from the installed vendor unit.\n'
REMOVED = re.compile(rb'(?m)^[ \t]*CPUAccounting[ \t]*=[^\n]*(?:\n|$)')


def reconcile(source, target, version, check=False):
    plans = []
    for name in UNITS:
        vendor, local = source / name, target / name
        if local.is_symlink():
            raise ValueError('refusing a symlink override: ' + name)
        existing = local.read_bytes() if local.exists() else None
        if existing is not None and not existing.startswith(MARKER):
            raise ValueError('refusing an unmanaged override: ' + name)
        raw = vendor.read_bytes() if vendor.exists() else None
        desired = MARKER + REMOVED.sub(b'', raw) if version >= 258 and raw is not None and REMOVED.search(raw) else None
        if existing != desired:
            plans.append((local, desired))
    # Validate every existing override before publishing any change.
    for path, content in plans:
        if check:
            continue
        if content is None:
            path.unlink()
        else:
            fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=target)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(content)
                    os.fchmod(stream.fileno(), 0o644)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, path)
            finally:
                Path(temporary).unlink(missing_ok=True)
        directory = os.open(target, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    return {'changed': bool(plans), 'check': check, 'systemd_version': version,
            'units': [p.name for p, _ in plans]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    version = int(subprocess.check_output(['systemctl', '--version'], text=True).splitlines()[0].split()[1])
    print(json.dumps(reconcile(Path('/usr/lib/systemd/system'), Path('/etc/systemd/system'), version, args.check)))


if __name__ == '__main__':
    main()
