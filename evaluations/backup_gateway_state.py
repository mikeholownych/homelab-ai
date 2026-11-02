"""Verified controller backup of gateway evidence and non-secret state, retaining whole snapshots.

Credentials, TLS keys and model files are excluded. All snapshot directories are self contained;
retention never deletes individual evidence segments or any live appliance evidence.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from orchestrator_runtime.evidence import verify_file  # noqa: E402

NAME = re.compile(r'^\d{8}T\d{6}Z-[0-9a-f]{12}$')
ALLOWED = re.compile(r'^(snapshot\.json|gateway-state\.json|client-usage\.json|evidence-chain\.jsonl(?:\.sealed-[0-9a-f]{64})?|legacy-evidence-[0-9a-f]{64}\.jsonl)$')


def verify_snapshot(root: Path) -> dict:
    manifest = json.loads((root / 'snapshot.json').read_text())
    for name, expected in manifest['files'].items():
        if not ALLOWED.fullmatch(name) or (root / name).is_symlink():
            raise ValueError('invalid snapshot member')
        digest = hashlib.sha256()
        with (root / name).open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024**2), b''):
                digest.update(chunk)
        if digest.hexdigest() != expected['sha256'] or (root / name).stat().st_size != expected['bytes']:
            raise ValueError('snapshot hash/size mismatch')
    valid, count, head, problems = verify_file(root / 'evidence-chain.jsonl')
    if not valid or count != manifest['evidence_records'] or head != manifest['evidence_head']:
        raise ValueError('snapshot evidence invalid: ' + str(problems[:3]))
    if manifest.get('schema_version', 1) >= 2:
        attached = {a['source_path']: a for a in manifest.get('legacy_attachments', [])}
        for name in manifest['files']:
            if not name.startswith('evidence-chain.jsonl'):
                continue
            with (root / name).open() as stream:
                genesis = json.loads(stream.readline())
            for anchor in genesis.get('sealed_predecessors', []):
                entry = attached.get(anchor.get('path'))
                if not entry or entry['snapshot_file'] not in manifest['files']:
                    raise ValueError('legacy attachment missing')
                actual = manifest['files'][entry['snapshot_file']]['sha256']
                if actual != entry['sha256'] or (anchor.get('sha256') and actual != anchor['sha256']):
                    raise ValueError('legacy attachment differs from genesis anchor')
    return manifest


def extract_snapshot(archive: tarfile.TarFile, destination: Path) -> None:
    total = 0
    seen = set()
    for member in archive:
        if member.isdir() and member.name in ('.', './'):
            continue
        name = member.name.removeprefix('./')
        if not member.isfile() or not ALLOWED.fullmatch(name) or name in seen:
            raise ValueError('unexpected backup archive member')
        total += member.size
        if total > 515 * 1024**2:
            raise ValueError('archive byte budget exceeded')
        seen.add(name)
        source = archive.extractfile(member)
        if source is None:
            raise ValueError('archive member missing')
        with source, (destination / name).open('xb') as target:
            shutil.copyfileobj(source, target, 1024**2)
        (destination / name).chmod(0o600)


def prune(root: Path, keep: int) -> list[str]:
    snapshots = sorted(p for p in root.iterdir() if NAME.fullmatch(p.name) and p.is_dir() and not p.is_symlink())
    deleted = []
    for old in snapshots[:-keep]:
        # Never silently discard a damaged snapshot; investigate it instead.
        verify_snapshot(old)
        shutil.rmtree(old)
        deleted.append(old.name)
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='mike@10.0.8.5')
    parser.add_argument('--backup-root', type=Path, required=True)
    parser.add_argument('--keep', type=int, default=7)
    args = parser.parse_args()
    if not 2 <= args.keep <= 30 or args.host.startswith('-'):
        parser.error('keep must be 2..30; host must not start with a dash')
    root = args.backup_root.resolve()
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    if args.backup_root.is_symlink() or root.stat().st_uid != os.getuid():
        raise ValueError('backup root must be owned by the caller and must not be a symlink')
    root.chmod(0o700)
    ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
           '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=3', args.host]
    def remote(argv: list[str], **kwargs):
        return subprocess.run([*ssh, shlex.join(argv)], check=True, timeout=180, **kwargs)
    with (root / '.backup.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        identity = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:12]
        pending = root / ('.pending-' + identity)
        pending.mkdir(mode=0o700)
        remote_path = '/var/lib/aihost-gateway-deployment/controller-backup-' + identity
        remote_created = False
        try:
            result = remote(['sudo', '-n', 'systemctl', 'show', 'aihost-orchestrator-gateway.service', '-p', 'WorkingDirectory', '--value'], capture_output=True, text=True)
            release = result.stdout.strip()
            if not re.fullmatch(r'/var/lib/aihost/releases/t5820-gateway-[A-Za-z0-9_-]+', release):
                raise ValueError('unexpected gateway release path')
            helper = Path(__file__).with_name('qualify_gateway_restore.py').read_text()
            remote_created = True
            try:
                remote(['sudo', '-n', 'env', 'PYTHONDONTWRITEBYTECODE=1', 'PYTHONPATH=' + release,
                        release + '/venv/bin/python3', '-W', 'error', '-', 'snapshot', '--source',
                        '/var/lib/aihost-gateway', '--target', remote_path], input=helper, text=True, capture_output=True)
            except subprocess.CalledProcessError as error:
                diagnostic = (error.stderr or 'no diagnostic').strip().splitlines()[-1]
                raise RuntimeError('appliance snapshot failed: ' + diagnostic[:300]) from None
            with subprocess.Popen([*ssh, shlex.join(['sudo', '-n', 'tar', '-C', remote_path, '-cf', '-', '.'])],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
                assert process.stdout is not None
                try:
                    with tarfile.open(fileobj=process.stdout, mode='r|') as archive:
                        extract_snapshot(archive, pending)
                    process.stdout.close()
                    process.communicate(timeout=180)
                    if process.returncode:
                        raise RuntimeError('SSH archive transfer failed: ' + str(process.returncode))
                except BaseException:
                    process.kill()
                    process.communicate(timeout=10)
                    raise
            manifest = verify_snapshot(pending)
            (pending / 'backup-receipt.json').write_text(json.dumps({'created_at': datetime.now(timezone.utc).isoformat(),
                'source_host': args.host, 'release_directory': release, 'verified': True,
                'records': manifest['evidence_records'], 'head': manifest['evidence_head'],
                'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}, indent=2) + '\n')
            (pending / 'backup-receipt.json').chmod(0o600)
            pending.rename(root / identity)
            removed = prune(root, args.keep)
            print(json.dumps({'passed': True, 'snapshot': identity, 'records': manifest['evidence_records'],
                              'retained': args.keep, 'pruned_snapshots': removed}))
        finally:
            if remote_created:
                # This exact, generated scratch directory is the only remote deletion target.
                remote(['sudo', '-n', 'rm', '-rf', '--', remote_path], capture_output=True)
            if pending.exists():
                shutil.rmtree(pending)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
