import json
import subprocess
import sys
from pathlib import Path

def test_asgi_worker_drain_authority_and_lifecycle():
    probe = Path(__file__).with_name('asgi_drain_route_probe.py')
    result = subprocess.run([sys.executable, '-B', str(probe), 'candidate'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['checks_passed'] == 13
