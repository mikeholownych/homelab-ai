#!/usr/bin/python3
"""Root-owned, durable gateway activation recovery. Never captures credentials or model files.

Only activation files supplied by the trusted deployment are journalled. A prepared transaction
expires quickly; an activated healthy target is adopted. Failed/expired activation restores the
previous files and checks its exact release. Failed recovery is latched for manual attention.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def health(url):
    try:
        with urllib.request.build_opener(NoRedirect).open(url, timeout=2) as response:
            value = json.loads(response.read(1024**2))
            return value if response.status == 200 and isinstance(value, dict) else {}
    except (OSError, ValueError, urllib.error.URLError):
        return {}


def systemctl(*args):
    return subprocess.check_output(['systemctl', *args], text=True, timeout=20).strip()


def atomic_json(path, value):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            json.dump(value, stream, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_dir(path.parent)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def sync_dir(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def copy_atomic(path, data, mode):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_dir(path.parent)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


class Activation:
    def __init__(self, root, *, check_health=health, control=systemctl, clock=time.time):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.root.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError('activation directory must be private and owned by the caller')
        self.pending = self.root / 'pending'
        self.check_health, self.control, self.clock = check_health, control, clock

    @contextmanager
    def locked(self):
        descriptor = os.open(self.root / '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def read(self):
        if self.pending.is_symlink():
            raise ValueError('activation journal may not be a symlink')
        value = json.loads((self.pending / 'metadata.json').read_text())
        if value.get('schema_version') != 1:
            raise ValueError('unsupported activation journal')
        return value

    def write(self, value):
        atomic_json(self.pending / 'metadata.json', value)

    def ready(self, value, release):
        observed = self.check_health(value['health_url'])
        return bool(release and observed.get('ready') is True and observed.get('release_id') == release)

    def begin(self, unit, paths, target, url, prepared_timeout=60, activation_timeout=2100):
        if self.pending.exists():
            raise ValueError('unresolved gateway activation; recover before deploying')
        if not re.fullmatch(r'[A-Za-z0-9_.@:-]+\.service', unit) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', target):
            raise ValueError('invalid unit or release identity')
        parsed = urllib.parse.urlparse(url)
        if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', '::1', 'localhost')
                or parsed.username or parsed.password or parsed.path != '/health' or parsed.query != 'strict=true'):
            raise ValueError('strict health must use a loopback HTTP endpoint')
        if not 1 <= prepared_timeout <= 300 or not 30 <= activation_timeout <= 3600:
            raise ValueError('invalid activation recovery time bounds')
        stage = Path(tempfile.mkdtemp(prefix='.prepare-', dir=self.root))
        try:
            entries = []
            for index, path in enumerate(paths):
                path = Path(path)
                if not path.is_absolute() or path.is_symlink():
                    raise ValueError('activation files must be absolute, regular paths')
                exists = path.exists()
                data = path.read_bytes() if exists else b''
                if len(data) > 1024**2 or (exists and not path.is_file()):
                    raise ValueError('activation file is not a bounded regular file')
                name = 'previous-' + str(index)
                if exists:
                    copy_atomic(stage / name, data, 0o600)
                entries.append({'path': str(path), 'exists': exists, 'file': name,
                                'mode': stat.S_IMODE(path.stat().st_mode) if exists else 0o644,
                                'sha256': hashlib.sha256(data).hexdigest()})
            if entries[0]['exists'] != entries[1]['exists']:
                raise ValueError('previous unit and environment must both exist or both be absent')
            previous = None
            if entries[1]['exists']:
                text = (stage / entries[1]['file']).read_text()
                match = re.search(r'^ORCHESTRATOR_RELEASE_ID=["\x27]?([A-Za-z0-9_.:-]+)', text, re.M)
                if not match:
                    raise ValueError('previous environment has no release identity')
                previous = match.group(1)
            value = {'schema_version': 1, 'id': uuid.uuid4().hex, 'unit': unit, 'files': entries,
                     'target_release': target, 'previous_release': previous, 'health_url': url,
                     'phase': 'prepared', 'created_at': self.clock(),
                     'deadline': self.clock() + prepared_timeout, 'activation_timeout': activation_timeout,
                     'prepared_timeout': prepared_timeout,
                     'previous_invocation': self.control('show', unit, '-p', 'InvocationID', '--value')}
            atomic_json(stage / 'metadata.json', value)
            copy_atomic(stage / 'armed', b'1\n', 0o600)
            sync_dir(stage)
            stage.rename(self.pending)
            sync_dir(self.root)
            return {'status': 'prepared', 'id': value['id']}
        finally:
            if stage.exists():
                shutil.rmtree(stage)

    def arm(self):
        value = self.read()
        if value['phase'] != 'prepared':
            raise ValueError('only a prepared activation can be armed')
        value.update(phase='activating', deadline=self.clock() + value['activation_timeout'],
                     launch_deadline=self.clock() + value['prepared_timeout'],
                     armed_invocation=self.control('show', value['unit'], '-p', 'InvocationID', '--value'),
                     target_files={entry['path']: hashlib.sha256(Path(entry['path']).read_bytes()).hexdigest()
                                   for entry in value['files']})
        self.write(value)
        return {'status': 'activating', 'id': value['id']}

    def finish(self, value, status):
        receipt = {'status': status, 'id': value['id'], 'target_release': value['target_release'],
                   'previous_release': value['previous_release'], 'finished_at': self.clock()}
        atomic_json(self.root / 'last.json', receipt)
        shutil.rmtree(self.pending)
        sync_dir(self.root)
        return receipt

    def target_files_intact(self, value):
        try:
            return all(not Path(path).is_symlink() and hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected
                       for path, expected in value.get('target_files', {}).items()) and bool(value.get('target_files'))
        except OSError:
            return False

    def target_ready(self, value):
        invocation = self.control('show', value['unit'], '-p', 'InvocationID', '--value')
        return bool(invocation and invocation != value.get('armed_invocation', value['previous_invocation'])
                    and self.target_files_intact(value) and self.ready(value, value['target_release']))

    def commit(self, transaction_id=None):
        if not self.pending.exists():
            receipt = json.loads((self.root / 'last.json').read_text())
            if transaction_id and receipt.get('id') == transaction_id and receipt.get('status') == 'accepted':
                return receipt
            raise ValueError('no matching accepted activation')
        value = self.read()
        if transaction_id and transaction_id != value['id']:
            raise ValueError('activation transaction identity mismatch')
        if value['phase'] not in ('prepared', 'activating') or not self.target_ready(value):
            raise ValueError('target release is not strictly ready')
        return self.finish(value, 'accepted')

    def fail(self, value, error):
        value.update(phase='failed', error_type=type(error).__name__)
        self.write(value)
        (self.pending / 'armed').unlink(missing_ok=True)
        sync_dir(self.pending)
        receipt = {'status': 'manual_attention', 'id': value['id'], 'error_type': type(error).__name__,
                   'target_release': value['target_release'], 'previous_release': value['previous_release']}
        atomic_json(self.root / 'last.json', receipt)
        return receipt

    def recover(self, force=False):
        if not self.pending.exists():
            return {'status': 'idle'}
        try:
            value = self.read()
        except Exception as error:
            if self.pending.is_dir() and not self.pending.is_symlink():
                (self.pending / 'armed').unlink(missing_ok=True)
                sync_dir(self.pending)
            receipt = {'status': 'manual_attention', 'error_type': type(error).__name__}
            atomic_json(self.root / 'last.json', receipt)
            return receipt
        last = self.root / 'last.json'
        if last.exists():
            receipt = json.loads(last.read_text())
            if receipt.get('id') == value['id'] and receipt.get('status') in ('accepted', 'restored', 'stopped_first_install'):
                shutil.rmtree(self.pending)
                sync_dir(self.root)
                return receipt
        if value['phase'] == 'failed':
            return {'status': 'manual_attention', 'id': value['id']}
        try:
            if value['phase'] in ('prepared', 'activating'):
                if not force and value['phase'] == 'activating' and self.target_ready(value):
                    return self.finish(value, 'accepted')
                state = self.control('show', value['unit'], '-p', 'ActiveState', '--value')
                invocation = self.control('show', value['unit'], '-p', 'InvocationID', '--value')
                launch_missed = (state == 'active' and invocation == value['previous_invocation']
                                 and self.clock() >= value.get('launch_deadline', value['deadline']))
                failed_start = value['phase'] == 'activating' and (state in ('failed', 'inactive') or launch_missed
                                                                           or not self.target_files_intact(value))
                if not force and not failed_start and self.clock() < value['deadline']:
                    return {'status': 'waiting', 'id': value['id']}
                previous_unit = value['files'][0]
                unit_path = Path(previous_unit['path'])
                current_hash = hashlib.sha256(unit_path.read_bytes()).hexdigest() if unit_path.exists() else None
                old_hash = previous_unit['sha256'] if previous_unit['exists'] else None
                staged_hash = value.get('target_files', {}).get(str(unit_path), old_hash)
                value.update(phase='recovering', step='files', recovery_deadline=self.clock() + value['activation_timeout'],
                             reload_needed=current_hash != old_hash or staged_hash != old_hash)
                self.write(value)
            if value['step'] == 'files':
                # Validate the whole baseline before restoring any of it.
                for entry in value['files']:
                    if entry['exists'] and hashlib.sha256((self.pending / entry['file']).read_bytes()).hexdigest() != entry['sha256']:
                        raise ValueError('activation baseline digest mismatch')
                if not value['files'][0]['exists']:
                    # A first installation has nothing to roll back to. Stop before removing the new unit.
                    loaded = self.control('show', value['unit'], '-p', 'LoadState', '--value')
                    if loaded != 'not-found':
                        self.control('stop', '--no-block', value['unit'])
                        self.control('disable', value['unit'])
                for entry in value['files']:
                    path = Path(entry['path'])
                    if path.is_symlink():
                        raise ValueError('activation target became a symlink')
                    if entry['exists']:
                        data = (self.pending / entry['file']).read_bytes()
                        if hashlib.sha256(data).hexdigest() != entry['sha256']:
                            raise ValueError('activation baseline digest mismatch')
                        copy_atomic(path, data, entry['mode'])
                    else:
                        path.unlink(missing_ok=True)
                        sync_dir(path.parent)
                value['step'] = 'reload'
                self.write(value)
            if value['step'] == 'reload':
                if value['reload_needed']:
                    self.control('daemon-reload')
                value['step'] = 'start'
                self.write(value)
            if value['step'] == 'start':
                if not value['files'][0]['exists']:
                    return self.finish(value, 'stopped_first_install')
                invocation = self.control('show', value['unit'], '-p', 'InvocationID', '--value')
                if not (invocation == value['previous_invocation'] and self.ready(value, value['previous_release'])):
                    self.control('reset-failed', value['unit'])
                    self.control('restart', '--no-block', value['unit'])
                value['step'] = 'verify'
                self.write(value)
            if self.ready(value, value['previous_release']):
                return self.finish(value, 'restored')
            state = self.control('show', value['unit'], '-p', 'ActiveState', '--value')
            if state == 'failed' or self.clock() >= value['recovery_deadline']:
                raise RuntimeError('previous gateway did not recover within its startup bound')
            return {'status': 'recovering', 'id': value['id']}
        except Exception as error:
            return self.fail(value, error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['begin', 'arm', 'commit', 'recover', 'status'])
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--unit', default='aihost-orchestrator-gateway.service')
    parser.add_argument('--unit-file', type=Path)
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--readiness-file', type=Path)
    parser.add_argument('--target-release')
    parser.add_argument('--health-url')
    parser.add_argument('--prepared-timeout', type=int, default=60)
    parser.add_argument('--activation-timeout', type=int, default=2100)
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--transaction-id')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('activation recovery requires root')
    activation = Activation(args.state)
    with activation.locked():
        if args.action == 'begin':
            if not all((args.unit_file, args.env_file, args.readiness_file, args.target_release, args.health_url)):
                parser.error('begin requires all activation paths, release and health URL')
            result = activation.begin(args.unit, [args.unit_file, args.env_file, args.readiness_file],
                                      args.target_release, args.health_url, args.prepared_timeout, args.activation_timeout)
        elif args.action == 'status':
            result = {'status': activation.read()['phase']} if activation.pending.exists() else {'status': 'idle'}
        elif args.action == 'recover':
            result = activation.recover(args.force)
        elif args.action == 'commit':
            result = activation.commit(args.transaction_id)
        else:
            result = activation.arm()
    print(json.dumps(result))
    return 1 if result['status'] == 'manual_attention' else 0


if __name__ == '__main__':
    raise SystemExit(main())
