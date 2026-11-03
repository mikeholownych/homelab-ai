import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("starlette")


def test_asgi_worker_drain_authority_and_lifecycle():
    probe = Path(__file__).with_name('asgi_drain_route_probe.py')
    # The probe runs as a script (sys.path[0] is tests/), so give it the repository root explicitly rather than relying on
    # the caller's PYTHONPATH, which only scripts/check-gateway-quality sets.
    env = {**os.environ, 'PYTHONPATH': os.pathsep.join(filter(None, [str(probe.parents[1]), os.environ.get('PYTHONPATH')]))}
    result = subprocess.run([sys.executable, '-B', str(probe), 'candidate'], capture_output=True, text=True, env=env)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['checks_passed'] == 13
