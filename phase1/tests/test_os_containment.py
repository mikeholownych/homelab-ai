"""Tests Proving OS-Level Execution Containment via Linux Namespaces (Bubblewrap)."""
from pathlib import Path
import pytest

from autonomous_engineering.containment.bwrap import BwrapSandbox


def test_containment_filesystem_isolation_blocks_home_access(tmp_path: Path):
    """Proves that host /home is completely invisible and inaccessible inside sandbox."""
    worktree = tmp_path / "sandbox_worktree"
    sandbox = BwrapSandbox(worktree)

    # Attempt to list /home
    res = sandbox.execute(["ls", "/home"])
    assert res.returncode != 0
    assert "No such file or directory" in res.stderr


def test_containment_filesystem_read_only_protection(tmp_path: Path):
    """Proves that system paths mounted inside sandbox are strictly read-only."""
    worktree = tmp_path / "sandbox_worktree"
    sandbox = BwrapSandbox(worktree)

    # Attempt to create file in /usr
    res = sandbox.execute(["touch", "/usr/exploit.txt"])
    assert res.returncode != 0
    assert "Read-only file system" in res.stderr


def test_containment_worktree_writable(tmp_path: Path):
    """Proves that the designated worktree is writable and contained."""
    worktree = tmp_path / "sandbox_worktree"
    sandbox = BwrapSandbox(worktree)

    res = sandbox.execute(["python3", "-c", "import pathlib; pathlib.Path('test.txt').write_text('hello')"])
    assert res.returncode == 0
    assert (worktree / "test.txt").read_text() == "hello"


def test_containment_network_isolation_blocks_egress(tmp_path: Path):
    """Proves that network namespace is unshared and socket connection fails."""
    worktree = tmp_path / "sandbox_worktree"
    sandbox = BwrapSandbox(worktree, allow_network=False)

    code = (
        "import socket\n"
        "s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
        "s.settimeout(2.0)\n"
        "s.connect(('1.1.1.1', 80))\n"
    )
    res = sandbox.execute(["python3", "-c", code])
    assert res.returncode != 0
    assert "Network is unreachable" in res.stderr or "OSError" in res.stderr


def test_containment_environment_cleared(tmp_path: Path):
    """Proves that sensitive host environment variables are scrubbed by --clearenv."""
    worktree = tmp_path / "sandbox_worktree"
    sandbox = BwrapSandbox(worktree)

    code = (
        "import os\n"
        "keys = set(os.environ.keys())\n"
        "sensitive = {'ORCHESTRATOR_CLIENT_TOKEN', 'SSH_AUTH_SOCK', 'AWS_SECRET_ACCESS_KEY'}\n"
        "assert not sensitive.intersection(keys), f'Leaked: {sensitive.intersection(keys)}'\n"
    )
    res = sandbox.execute(["python3", "-c", code])
    assert res.returncode == 0


def test_containment_pid_namespace_isolation(tmp_path: Path):
    """Proves that host processes are invisible inside sandbox PID namespace."""
    worktree = tmp_path / "sandbox_worktree"
    sandbox = BwrapSandbox(worktree)

    # In a separate PID namespace, only the sandbox processes exist
    code = (
        "import os\n"
        "# Inside sandbox, current PID should be small (usually 2 or 3)\n"
        "assert os.getpid() < 10, f'Expected container PID, got {os.getpid()}'\n"
    )
    res = sandbox.execute(["python3", "-c", code])
    assert res.returncode == 0
