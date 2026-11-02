"""Root-only controller-loss drill against disposable systemd services, never the live gateway.

Uses the real activation helper and recovery service confinement. The HTTP fixture has no model,
credentials or GPU; the test watchdog uses a two-second monotonic cadence, without external alerts.
The controller is a real Ansible process killed with its process group after a durable barrier.
This qualifies controller-process loss; it does not qualify an appliance power cycle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import time
import urllib.request
import uuid

import yaml
from jinja2 import Environment, FileSystemLoader


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('run as root on the controller; never on the inference appliance')
    source = args.source.resolve()
    helper_source = source / 'roles/orchestrator_gateway/files/gateway-activation.py'
    base = Path('/var/lib/aihost-gateway-qualification') / ('interruption-' + uuid.uuid4().hex[:12])
    base.mkdir(parents=True, mode=0o755)
    base.chmod(0o755)
    helper = base / 'gateway-activation'
    shutil.copyfile(helper_source, helper); helper.chmod(0o755)
    fixture = base / 'fixture.py'
    fixture.write_text('''import json,os
from http.server import BaseHTTPRequestHandler,HTTPServer
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  data=json.dumps({'ready':True,'release_id':os.environ['ORCHESTRATOR_RELEASE_ID'],'gateway':{'pid':os.getpid()}}).encode()
  self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def log_message(self,*args):pass
HTTPServer(('127.0.0.1',int(os.environ['PORT'])),Handler).serve_forever()
'''); fixture.chmod(0o644)
    env = Environment(loader=FileSystemLoader(str(source / 'roles/orchestrator_gateway/templates')))
    env.filters['dirname'] = lambda value: str(Path(value).parent)
    record = {'profile': __doc__, 'helper_sha256': hashlib.sha256(helper.read_bytes()).hexdigest(), 'cases': []}
    installed = []
    def ctl(*values, check=True):
        return subprocess.run(['systemctl', *values], capture_output=True, text=True, timeout=30, check=check).stdout.strip()
    def invoke(case, action, *extra):
        return json.loads(subprocess.check_output([str(helper), action, '--state', str(case / 'journal'), *extra], text=True, timeout=30))
    def observe(url):
        try:
            with urllib.request.urlopen(url, timeout=2) as response:return json.load(response)
        except (OSError, ValueError):return {}
    try:
        for kind in ['prepared_half_write', 'failed_new_service', 'healthy_target_adoption']:
            case = base / kind; case.mkdir(mode=0o755)
            (case / 'journal').mkdir(mode=0o700)
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
            unit = 'aihost-activation-qualification-' + base.name[-12:] + '-' + kind.replace('_', '-')
            unit_path = Path('/run/systemd/system') / (unit + '.service')
            recovery_name = unit + '-recover'
            recovery_path = unit_path.with_name(recovery_name + '.service')
            timer_path = unit_path.with_name(recovery_name + '.timer')
            environment = case / 'gateway.env'; readiness = case / 'readiness'
            original_env = 'ORCHESTRATOR_RELEASE_ID=old\nPORT=' + str(port) + '\n'
            environment.write_text(original_env); environment.chmod(0o600)
            readiness.write_text('#!/bin/sh\nexit 0\n'); readiness.chmod(0o755)
            original_unit = ('[Unit]\nStartLimitBurst=20\n[Service]\nType=simple\nDynamicUser=yes\n'
                'EnvironmentFile=' + str(environment) + '\nExecStartPre=' + str(readiness) + '\n'
                'ExecStart=/usr/bin/python3 ' + str(fixture) + '\nRestart=no\n[Install]\nWantedBy=multi-user.target\n')
            unit_path.write_text(original_unit)
            variables = {'orchestrator_gateway_activation_state_dir': str(case / 'journal'),
                'orchestrator_gateway_activation_helper_path': str(helper), 'orchestrator_gateway_service_path': str(unit_path),
                'orchestrator_gateway_env_file': str(environment), 'orchestrator_gateway_readiness_path': str(readiness)}
            recovery = env.get_template('gateway-activation-recovery.service.j2').render(**variables)
            recovery = '\n'.join(line for line in recovery.splitlines() if not line.startswith('OnFailure=')) + '\n'
            recovery_path.write_text(recovery)
            timer_path.write_text('[Timer]\nOnActiveSec=2s\nOnUnitActiveSec=2s\nUnit=' + recovery_name + '.service\n')
            installed += [unit_path, recovery_path, timer_path]
            ctl('daemon-reload'); ctl('start', unit + '.service')
            url = 'http://127.0.0.1:' + str(port) + '/health?strict=true'
            for _ in range(100):
                if observe(url).get('release_id') == 'old':break
                time.sleep(.1)
            assert observe(url).get('release_id') == 'old'
            previous_pid = ctl('show', unit + '.service', '-p', 'MainPID', '--value')
            barrier = case / 'controller-barrier'
            begin = [str(helper), 'begin', '--state', str(case / 'journal'), '--unit', unit + '.service',
                '--unit-file', str(unit_path), '--env-file', str(environment), '--readiness-file', str(readiness),
                '--target-release', 'new', '--health-url', url, '--prepared-timeout', '12', '--activation-timeout', '30']
            tasks = [{'name': 'Journal before mutation', 'ansible.builtin.command': {'argv': begin}, 'changed_when': True},
                     {'name': 'Write target environment', 'ansible.builtin.copy': {'dest': str(environment),
                        'content': original_env.replace('=old', '=new'), 'mode': '0600'}}]
            if kind == 'failed_new_service':
                tasks.append({'name': 'Inject an invalid new executable', 'ansible.builtin.copy': {'dest': str(unit_path),
                    'content': original_unit.replace('ExecStart=/usr/bin/python3 ' + str(fixture), 'ExecStart=/bin/false'), 'mode': '0644'}})
            if kind != 'prepared_half_write':
                tasks += [{'name': 'Arm activation', 'ansible.builtin.command': {'argv': [str(helper), 'arm', '--state', str(case / 'journal')]}, 'changed_when': True},
                          {'name': 'Reload the test unit', 'ansible.builtin.command': {'argv': ['systemctl', 'daemon-reload']}, 'changed_when': True},
                          {'name': 'Request test restart', 'ansible.builtin.command': {'argv': ['systemctl', 'restart', '--no-block', unit + '.service']}, 'changed_when': True}]
            tasks += [{'name': 'Record controller interruption barrier', 'ansible.builtin.file': {'path': str(barrier), 'state': 'touch', 'mode': '0600'}},
                      {'name': 'Hold controller before commit', 'ansible.builtin.command': {'argv': ['/bin/sleep', '120']}, 'changed_when': False}]
            play = case / 'controller.yml'; play.write_text(yaml.safe_dump([{'hosts': 'localhost', 'gather_facts': False, 'become': False, 'tasks': tasks}]))
            command = ['/home/mike/Projects/aihost/.venv/bin/ansible-playbook', '-i', 'localhost,', '-c', 'local', str(play)]
            with (case / 'controller.log').open('w') as log:
                process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, cwd=source)
                try:
                    for _ in range(600):
                        if barrier.exists():break
                        if process.poll() is not None:raise RuntimeError('controller exited before the barrier; inspect private fixture log')
                        time.sleep(.1)
                    assert barrier.exists(), 'controller did not reach durable mutation barrier'
                    # Starting the independent watchdog immediately before killing its controller removes a timing race.
                    ctl('start', recovery_name + '.timer')
                    killed_at = time.time(); os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=10)
                finally:
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=10)
            receipt_path = case / 'journal/last.json'
            for _ in range(750):
                if receipt_path.exists():break
                time.sleep(.1)
            assert receipt_path.exists(), 'independent watchdog did not finish'
            receipt = json.loads(receipt_path.read_text())
            expected = 'accepted' if kind == 'healthy_target_adoption' else 'restored'
            assert receipt['status'] == expected and receipt['finished_at'] >= killed_at, receipt
            expected_release = 'new' if expected == 'accepted' else 'old'
            observed = observe(url); assert observed.get('ready') and observed.get('release_id') == expected_release
            pid = ctl('show', unit + '.service', '-p', 'MainPID', '--value')
            if kind == 'prepared_half_write':
                assert unit_path.read_text() == original_unit and environment.read_text() == original_env and pid == previous_pid
            if expected == 'accepted':assert invoke(case, 'commit', '--transaction-id', receipt['id'])['status'] == 'accepted'
            assert not (case / 'journal/pending').exists()
            record['cases'].append({'case': kind, 'controller_killed': True, 'recovered_by_independent_systemd': True,
                'recovery_seconds_after_kill': receipt['finished_at'] - killed_at, 'receipt': receipt,
                'release_id': observed['release_id'], 'old_pid_preserved': pid == previous_pid, 'passed': True})
            ctl('stop', recovery_name + '.timer'); ctl('stop', unit + '.service')
        record['passed'] = len(record['cases']) == 3
    finally:
        for path in installed:
            ctl('stop', path.name, check=False)
            path.unlink(missing_ok=True)
        ctl('daemon-reload')
        record.setdefault('passed', False)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))
    return 0 if record['passed'] else 1


if __name__ == '__main__':raise SystemExit(main())
