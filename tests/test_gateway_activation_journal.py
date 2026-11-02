"""Persistent activation decisions, including interruption and same-release config updates."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('gateway_activation_journal', ROOT / 'roles/orchestrator_gateway/files/gateway-activation.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Fixture:
    def __init__(self, root):
        self.paths = [root / 'gateway.service', root / 'gateway.env', root / 'readiness.py']
        self.original = [b'[Service]\nExecStart=/old\n', b'ORCHESTRATOR_RELEASE_ID=old\n', b'# previous readiness\n']
        for p, data, mode in zip(self.paths, self.original, [0o644, 0o640, 0o755]):
            p.write_bytes(data)
            p.chmod(mode)
        self.now = 100
        self.invocation = 'first'
        self.release = 'old'
        self.state = 'active'
        self.calls = []
        self.delay_restart = False
        self.fail_restart = False
        self.journal = module.Activation(root / 'journal', check_health=self.health, control=self.control, clock=lambda: self.now)

    def health(self, _):
        return {'ready': True, 'release_id': self.release} if self.state == 'active' else {}

    def control(self, *args):
        self.calls.append(args)
        if args[0] == 'show':
            return self.invocation if 'InvocationID' in args else self.state if 'ActiveState' in args else 'loaded'
        if args[0] == 'restart':
            self.invocation += '-restarted'
            self.release = self.paths[1].read_text().split('=', 1)[1].strip()
            self.state = 'failed' if self.fail_restart else 'activating' if self.delay_restart else 'active'
        return ''

    def begin(self, target='new'):
        return self.journal.begin('gateway.service', self.paths, target, 'http://127.0.0.1:8010/health?strict=true', 5, 30)

    def write_target(self, release='new'):
        self.paths[0].write_text('[Service]\nExecStart=/new\n')
        self.paths[1].write_text('ORCHESTRATOR_RELEASE_ID=' + release + '\n')
        self.paths[2].write_text('# new readiness\n')

    def assert_restored(self):
        assert [p.read_bytes() for p in self.paths] == self.original
        assert [p.stat().st_mode & 0o777 for p in self.paths] == [0o644, 0o640, 0o755]


def test_prepared_controller_loss_restores_files_without_restarting_old_process(tmp_path):
    f = Fixture(tmp_path)
    f.begin(); f.write_target()
    assert f.journal.recover()['status'] == 'waiting'
    f.now += 6
    assert f.journal.recover()['status'] == 'restored'
    f.assert_restored()
    assert sum(c[0] == 'daemon-reload' for c in f.calls) == 1
    assert not any(c[0] == 'restart' for c in f.calls)
    assert f.journal.recover()['status'] == 'idle'


def test_failed_new_start_recovers_previous_identity(tmp_path):
    f = Fixture(tmp_path)
    f.begin(); f.write_target(); f.journal.arm()
    f.invocation = 'failed-new'; f.state = 'failed'
    assert f.journal.recover()['status'] == 'restored'
    f.assert_restored()
    assert f.release == 'old'
    assert sum(c[0] == 'restart' for c in f.calls) == 1


def test_recovery_wait_does_not_repeat_reload_or_restart(tmp_path):
    f = Fixture(tmp_path)
    f.begin(); f.write_target(); f.journal.arm()
    f.invocation = 'new'; f.release = 'new'
    f.delay_restart = True
    assert f.journal.recover(force=True)['status'] == 'recovering'
    for _ in range(4):
        assert f.journal.recover()['status'] == 'recovering'
    assert sum(c[0] == 'daemon-reload' for c in f.calls) == 1
    assert sum(c[0] == 'restart' for c in f.calls) == 1
    f.state = 'active'
    assert f.journal.recover()['status'] == 'restored'


def test_healthy_target_after_controller_loss_is_adopted_and_commit_is_idempotent(tmp_path):
    f = Fixture(tmp_path)
    tx = f.begin(); f.write_target(); f.journal.arm()
    f.invocation = 'new'; f.release = 'new'
    assert f.journal.recover()['status'] == 'accepted'
    assert f.journal.commit(tx['id'])['status'] == 'accepted'
    assert not any(c[0] in ('daemon-reload', 'restart') for c in f.calls)


def test_same_release_config_change_requires_a_new_invocation_after_arm(tmp_path):
    f = Fixture(tmp_path)
    f.begin(target='old'); f.write_target(release='old'); f.journal.arm()
    with pytest.raises(ValueError, match='not strictly ready'):
        f.journal.commit()
    f.invocation = 'new-config'
    assert f.journal.commit()['status'] == 'accepted'


def test_unlaunched_armed_deployment_rolls_back_after_short_launch_timeout(tmp_path):
    f = Fixture(tmp_path)
    f.begin(); f.write_target(); f.journal.arm()
    f.now += 6
    assert f.journal.recover()['status'] == 'restored'
    f.assert_restored()


def test_changed_target_files_cannot_be_adopted(tmp_path):
    f = Fixture(tmp_path)
    f.begin(); f.write_target(); f.journal.arm()
    f.invocation = 'new'; f.release = 'new'
    f.paths[0].write_text('unexpected drift')
    assert f.journal.recover()['status'] == 'restored'
    f.assert_restored()


def test_corrupt_baseline_is_latched_before_any_activation_file_is_restored(tmp_path):
    f = Fixture(tmp_path)
    f.begin(); f.write_target(); f.journal.arm()
    (f.journal.pending / 'previous-1').write_text('corrupt')
    before = [p.read_bytes() for p in f.paths]
    assert f.journal.recover(force=True)['status'] == 'manual_attention'
    assert [p.read_bytes() for p in f.paths] == before
    assert not (f.journal.pending / 'armed').exists()
    count = len(f.calls)
    assert f.journal.recover()['status'] == 'manual_attention'
    assert len(f.calls) == count


def test_failed_recovery_is_latched_and_does_not_restart_forever(tmp_path):
    f = Fixture(tmp_path)
    f.begin(); f.write_target(); f.journal.arm()
    f.invocation = 'new'; f.release = 'new'; f.fail_restart = True
    assert f.journal.recover(force=True)['status'] == 'manual_attention'
    assert not (f.journal.pending / 'armed').exists()
    before = list(f.calls)
    f.journal.recover()
    assert f.calls == before


def test_unreadable_journal_is_latched_without_writing_activation_files(tmp_path):
    f = Fixture(tmp_path)
    f.begin()
    (f.journal.pending / 'metadata.json').write_text('incomplete JSON')
    assert f.journal.recover()['status'] == 'manual_attention'
    assert not (f.journal.pending / 'armed').exists()
    f.assert_restored()


def test_committed_receipt_survives_interrupted_pending_cleanup(tmp_path, monkeypatch):
    f = Fixture(tmp_path)
    tx = f.begin(); f.write_target(); f.journal.arm()
    f.release = 'new'; f.invocation = 'new'
    original = module.shutil.rmtree
    monkeypatch.setattr(module.shutil, 'rmtree', lambda _: (_ for _ in ()).throw(OSError('interrupted cleanup')))
    with pytest.raises(OSError):
        f.journal.commit()
    monkeypatch.setattr(module.shutil, 'rmtree', original)
    assert f.journal.recover()['status'] == 'accepted'
    assert not f.journal.pending.exists()
    assert json.loads((f.journal.root / 'last.json').read_text())['id'] == tx['id']


def test_role_journals_before_mutation_arms_before_start_and_commits_after_health():
    import yaml
    tasks = yaml.safe_load((ROOT / 'roles/orchestrator_gateway/tasks/main.yml').read_text())
    names = [t['name'] for t in tasks]
    assert names.index('Recover any earlier interrupted gateway activation before deploying') < names.index('Read prior gateway activation files for rollback')
    block = next(t['block'] for t in tasks if t['name'] == 'Activate and verify the staged gateway with rollback')
    names = [t['name'] for t in block]
    assert names.index('Journal the previous gateway before changing activation files') < names.index('Render gateway non-secret environment')
    assert names.index('Arm recovery before requesting gateway activation') < names.index('Establish persistent gateway state')
    assert names.index('Verify the activated gateway identity and readiness') < names.index('Commit the strictly verified activation journal')


def test_prepared_environment_only_loss_needs_no_daemon_reload(tmp_path):
    f = Fixture(tmp_path)
    f.begin(); f.paths[1].write_text('ORCHESTRATOR_RELEASE_ID=new\n')
    f.now += 6
    assert f.journal.recover()['status'] == 'restored'
    f.assert_restored()
    assert not any(c[0] in ('daemon-reload', 'restart') for c in f.calls)


def test_real_ansible_template_comparison_recognizes_an_unchanged_activation(tmp_path):
    import base64
    import copy
    import shutil
    import subprocess
    import sys
    import yaml
    source_role = ROOT / 'roles/orchestrator_gateway'
    role = tmp_path / 'roles/render_gateway'
    for name in ['tasks', 'defaults', 'files', 'templates']:(role / name).mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_role / 'templates', role / 'templates', dirs_exist_ok=True)
    shutil.copyfile(source_role / 'defaults/main.yml', role / 'defaults/main.yml')
    shutil.copyfile(source_role / 'files/gateway-readiness.py', role / 'files/gateway-readiness.py')
    all_tasks = yaml.safe_load((source_role / 'tasks/main.yml').read_text())
    block = next(t['block'] for t in all_tasks if t['name'] == 'Activate and verify the staged gateway with rollback')
    compare = copy.deepcopy(block[0]);compare['no_log'] = False
    expected = {'results': [
        {'content': "{{ lookup('ansible.builtin.template', 'orchestrator-gateway.service.j2') | b64encode }}"},
        {'content': "{{ lookup('ansible.builtin.template', 'gateway.env.j2') | b64encode }}"},
        {'content': "{{ lookup('ansible.builtin.file', role_path ~ '/files/gateway-readiness.py') | b64encode }}"},
    ]}
    tasks = [compare, {'ansible.builtin.assert': {'that': ['orchestrator_gateway_activation_required | bool']}},
             {'ansible.builtin.set_fact': {'orchestrator_gateway_previous_activation': expected}}, compare,
             {'ansible.builtin.assert': {'that': ['not (orchestrator_gateway_activation_required | bool)']}}]
    (role / 'tasks/main.yml').write_text(yaml.safe_dump(tasks))
    variables = yaml.safe_load((ROOT / 'inventory/production/host_vars/ai-5820-01.yml').read_text())
    variables['orchestrator_gateway_previous_activation'] = {'results': [{'content': base64.b64encode(b'old').decode()} for _ in range(3)]}
    play = tmp_path / 'render.yml'
    play.write_text(yaml.safe_dump([{'hosts': 'localhost', 'gather_facts': False, 'become': False,
        'vars': variables, 'roles': ['render_gateway']}]))
    result = subprocess.run([str(Path(sys.executable).parent / 'ansible-playbook'), '-i', 'localhost,', '-c', 'local', str(play)],
                            cwd=ROOT, text=True, capture_output=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
