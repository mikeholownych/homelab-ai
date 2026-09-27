"""Tests for Extended Held-Out Evaluation Fixtures."""
import subprocess
import sys
from pathlib import Path
import pytest


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "heldout"


def test_heldout_defect_01_off_by_one_failing_initially():
    repo_dir = FIXTURES_DIR / "heldout_defect_01_off_by_one_paging"
    # test_paginate_partial_remainder should fail initially due to intentional bug
    cmd = [sys.executable, "-m", "pytest", "tests/test_paginator.py"]
    res = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True)
    assert res.returncode != 0
    assert "FAILED tests/test_paginator.py::test_paginate_partial_remainder" in res.stdout


def test_heldout_multifile_01_rate_limiter_passing():
    repo_dir = FIXTURES_DIR / "heldout_multifile_01_rate_limiter"
    cmd = [sys.executable, "-m", "pytest", "tests/test_rate_limiter.py"]
    res = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True)
    assert res.returncode == 0
    assert "2 passed" in res.stdout


def test_heldout_testdev_01_fencing_invariant_passing():
    repo_dir = FIXTURES_DIR / "heldout_testdev_01_fencing_invariant"
    cmd = [sys.executable, "-m", "pytest", "tests/test_fencing.py"]
    res = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True)
    assert res.returncode == 0
    assert "2 passed" in res.stdout


def test_heldout_maintain_01_decouple_notifier_passing():
    repo_dir = FIXTURES_DIR / "heldout_maintain_01_decouple_notifier"
    cmd = [sys.executable, "-m", "pytest", "tests/test_notifier.py"]
    res = subprocess.run(cmd, cwd=repo_dir, capture_output=True, text=True)
    assert res.returncode == 0
    assert "4 passed" in res.stdout
