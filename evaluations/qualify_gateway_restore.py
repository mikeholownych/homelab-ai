"""Snapshot hash-policy gateway evidence/state and verify restoration in a separate directory.

Run as root on the appliance with the deployed release on PYTHONPATH. Never modifies live state.
Output directories must be new. No credentials or TLS keys are copied. Snapshot consistency is per
file; this is not a transactionally consistent full host or authentication backup.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import time

from orchestrator_runtime.evidence import EvidenceStore, verify_file

MAX_BYTES = 512 * 1024**2


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(1024**2), b''):
            h.update(data)
    return h.hexdigest()


def copy_prefix(source: Path, target: Path, budget: int, *, trim_partial: bool = True) -> int:
    """Copy an opened inode's initial prefix; omit a partially written final JSONL record."""
    with source.open('rb') as src, target.open('xb') as dst:
        size = os.fstat(src.fileno()).st_size
        if size > budget:
            raise ValueError('snapshot byte budget exceeded')
        remaining = size
        while remaining:
            data = src.read(min(1024**2, remaining))
            if not data:
                raise ValueError('source shrank during snapshot')
            dst.write(data)
            remaining -= len(data)
        dst.flush()
    if not trim_partial:
        return size
    with target.open('r+b') as stream:
        end = stream.seek(0, 2)
        if end:
            stream.seek(max(0, end - 1024**2))
            tail = stream.read()
            if not tail.endswith(b'\n'):
                last = tail.rfind(b'\n')
                if last < 0:
                    raise ValueError('no complete final record within one MiB')
                stream.truncate(max(0, end - 1024**2) + last + 1)
    return size


def snapshot(source: Path, target: Path) -> dict:
    target.mkdir(mode=0o700, parents=False, exist_ok=False)
    active = 'evidence-chain.jsonl'
    used = copy_prefix(source / active, target / active, MAX_BYTES)
    current = target / active
    names = [active]
    while True:
        with current.open() as stream:
            first = json.loads(stream.readline())
        previous = first.get('sealed_predecessor')
        if not previous:
            break
        name = previous.get('file')
        if not name or Path(name).name != name or name in names:
            raise ValueError('invalid predecessor')
        used += copy_prefix(source / name, target / name, MAX_BYTES - used)
        names.append(name)
        current = target / name
    valid, count, head, problems = verify_file(target / active)
    if not valid:
        raise ValueError('snapshot chain invalid: ' + str(problems[:3]))
    # Older genesis records reference immutable archives using a separate legacy format.
    # Preserve them too, without pretending an unreadable-at-genesis file was historically attested.
    attachments = []
    referenced = set()
    for chain_name in list(names):
        with (target / chain_name).open() as stream:
            genesis = json.loads(stream.readline())
        for anchor in genesis.get('sealed_predecessors', []):
            legacy = Path(anchor.get('path', ''))
            if (not legacy.is_absolute() or legacy.is_symlink() or legacy.suffix != '.jsonl'
                    or legacy.resolve().parent not in (source.resolve(), Path('/var/lib/aihost/evidence').resolve())):
                raise ValueError('legacy evidence path outside allowed evidence roots')
            if str(legacy) in referenced:
                continue
            referenced.add(str(legacy))
            name = 'legacy-evidence-' + hashlib.sha256(str(legacy).encode()).hexdigest() + '.jsonl'
            used += copy_prefix(legacy, target / name, MAX_BYTES - used, trim_partial=False)
            actual = digest(target / name)
            if anchor.get('sha256') and actual != anchor['sha256']:
                raise ValueError('legacy evidence differs from genesis anchor')
            names.append(name)
            attachments.append({'source_path': str(legacy), 'snapshot_file': name, 'sha256': actual,
                                'genesis_sha256': anchor.get('sha256'),
                                'genesis_attested': bool(anchor.get('sha256'))})
    # These are non-secret JSON runtime state files, not clients.json or credential files.
    for name in ['gateway-state.json', 'client-usage.json']:
        path = source / name
        if path.exists():
            for attempt in range(3):
                try:
                    raw = path.read_bytes()
                    if len(raw) > 1024**2 or not isinstance(json.loads(raw), dict):
                        raise ValueError('invalid state')
                    break
                except ValueError:
                    if attempt == 2:
                        raise
                    time.sleep(.1)
            (target / name).write_bytes(raw)
            names.append(name)
    manifest = {'schema_version': 2, 'evidence_records': count, 'evidence_head': head,
                'legacy_attachments': attachments,
                'files': {name: {'sha256': digest(target / name), 'bytes': (target / name).stat().st_size} for name in names}}
    (target / 'snapshot.json').write_text(json.dumps(manifest, indent=2) + '\n')
    for path in target.iterdir():
        path.chmod(0o600)
    return manifest


def restore(source: Path, target: Path) -> dict:
    manifest = json.loads((source / 'snapshot.json').read_text())
    target.mkdir(mode=0o700, parents=False, exist_ok=False)
    for name, expected in manifest['files'].items():
        if Path(name).name != name or digest(source / name) != expected['sha256']:
            raise ValueError('backup digest mismatch')
        shutil.copyfile(source / name, target / name)
        (target / name).chmod(0o600)
    valid, count, head, problems = verify_file(target / 'evidence-chain.jsonl')
    assert valid and count == manifest['evidence_records'] and head == manifest['evidence_head'], problems
    store = EvidenceStore(target / 'evidence-chain.jsonl', anchor_stream=io.StringIO())
    assert store.chain_valid and store.head == head
    store.append('qualification_restore_probe', source_head=head)
    valid, restored_count, _, problems = verify_file(target / 'evidence-chain.jsonl')
    assert valid and restored_count == count + 1, problems
    return {'passed': True, 'backup_records': count, 'restored_records': restored_count,
            'continuity_preserved': True,
            'legacy_attachments': len(manifest.get('legacy_attachments', [])),
            'genesis_attested_legacy_attachments': sum(a['genesis_attested'] for a in manifest.get('legacy_attachments', [])),
            'state_json_valid': all(isinstance(json.loads((target / name).read_text()), dict)
                for name in manifest['files'] if name.endswith('.json')),
            'scope': 'evidence chain and per-file non-secret runtime state; no auth/TLS/model/host restore'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['snapshot', 'restore'])
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--target', type=Path, required=True)
    args = parser.parse_args()
    result = (snapshot if args.operation == 'snapshot' else restore)(args.source, args.target)
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
