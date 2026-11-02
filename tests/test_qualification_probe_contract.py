import fcntl
import subprocess
import sys
from pathlib import Path

import yaml


def test_probe_requires_reconciliation_exclusion_before_mutation(tmp_path):
    root = Path(__file__).parents[1]
    play = yaml.safe_load((root / "playbooks/qualification_probe.yml").read_text())[0]
    task = play["tasks"][0]
    script = task["ansible.builtin.command"]["argv"][-1]
    lock_path = tmp_path / "qualification.lock"
    lock_path.touch()
    script = script.replace('/home/mike/.local/share/aihost/reconcile/lock/ansible-snapshot.lock', str(lock_path))
    free = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
    assert free.returncode != 0 and 'reconciliation is not excluded' in free.stderr
    with lock_path.open('r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        owned = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
        assert owned.returncode == 0
    wrapper = yaml.safe_load((root / "playbooks/controller_qualification_probe.yml").read_text())[0]
    assert wrapper['tasks'][0]['ansible.builtin.command']['argv'][0] == 'flock'
