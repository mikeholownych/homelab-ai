"""Exercise real Ansible activation/rescue tasks with temporary files and a fake health server.

Systemd actions are substituted with /bin/true. This qualifies file rollback and
identity gating, not real service-manager or appliance failure recovery.
"""
import base64
import copy
import json
from pathlib import Path
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('failure', ['readiness', 'identity', 'restart'])
def test_activation_gate_restores_previous_files(tmp_path, failure):
    unit, env = tmp_path / 'gateway.service', tmp_path / 'gateway.env'
    original_unit, original_env = '# previous verified unit\n', 'ORCHESTRATOR_RELEASE_ID=previous\n'
    unit.write_text(original_unit)
    env.write_text(original_env)

    class Health(BaseHTTPRequestHandler):
        def do_GET(self):
            previous = env.read_text() == original_env
            status = 200 if previous or failure == 'identity' else 503
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'ready': True, 'release_id': 'wrong-identity'}).encode())
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Health)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        role = ROOT / 'roles/orchestrator_gateway'
        tasks = yaml.safe_load((role / 'tasks/main.yml').read_text())
        transaction = copy.deepcopy(next(t for t in tasks if t['name'] == 'Activate and verify the staged gateway with rollback'))
        selected = []
        for task in transaction['block']:
            template = task.get('ansible.builtin.template')
            if template and template['src'] in {'gateway.env.j2', 'orchestrator-gateway.service.j2'}:
                template['src'] = str(role / 'templates' / template['src'])
                template.pop('owner', None)
                template.pop('group', None)
                selected.append(task)
            elif task.get('ansible.builtin.meta') == 'flush_handlers':
                selected.append(task)
            elif task['name'] == 'Verify the activated gateway identity and readiness':
                task['retries'], task['delay'] = 1, 0
                selected.append(task)
        transaction['block'] = selected
        for task in transaction['rescue']:
            if 'ansible.builtin.systemd_service' in task:
                del task['ansible.builtin.systemd_service']
                task['ansible.builtin.command'] = {'argv': ['/bin/true']}
                task['changed_when'] = False
            if 'ansible.builtin.copy' in task:
                task['ansible.builtin.copy'].pop('owner', None)
                task['ansible.builtin.copy'].pop('group', None)
            if 'ansible.builtin.uri' in task:
                task['retries'], task['delay'] = 1, 0
        defaults = yaml.safe_load((role / 'defaults/main.yml').read_text())
        defaults.update({
            'orchestrator_gateway_enabled': True,
            'orchestrator_gateway_host': '127.0.0.1',
            'orchestrator_gateway_port': server.server_port,
            'orchestrator_gateway_release_id': 'new-quality',
            'orchestrator_gateway_service_path': str(unit),
            'orchestrator_gateway_env_file': str(env),
            'orchestrator_gateway_unit': {'changed': True},
            'orchestrator_gateway_removed_dropins': {'changed': False},
            'orchestrator_gateway_previous_activation': {'results': [
                {'item': str(unit), 'content': base64.b64encode(original_unit.encode()).decode()},
                {'item': str(env), 'content': base64.b64encode(original_env.encode()).decode()},
            ]},
        })
        playbook = tmp_path / 'rollback.yml'
        playbook.write_text(yaml.safe_dump([{'hosts': 'localhost', 'gather_facts': False,
                                           'become': False, 'vars': defaults, 'tasks': [transaction],
                                           'handlers': [{'name': 'Restart gateway service',
                                                         'ansible.builtin.command': {'argv': ['/bin/false' if failure == 'restart' else '/bin/true']},
                                                         'changed_when': False}]}]))
        command = Path(sys.executable).parent / 'ansible-playbook'
        result = subprocess.run([str(command), '-i', 'localhost,', '-c', 'local', str(playbook)],
                                cwd=ROOT, text=True, capture_output=True, timeout=45)
        assert result.returncode != 0, result.stdout
        assert 'Gateway activation failed' in result.stdout, result.stdout + result.stderr
        assert unit.read_text() == original_unit
        assert env.read_text() == original_env
    finally:
        server.shutdown()
        thread.join(2)
        server.server_close()
