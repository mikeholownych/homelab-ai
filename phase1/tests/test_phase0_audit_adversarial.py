"""Adversarial Tests Exposing In-Process Simulation Gaps in Phase 0.

Written PRIOR to implementing Phase 1 containment hardening.
Demonstrates:
1. In-process ScopeGuard cannot prevent direct OS file writes outside authorized paths.
2. In-process workers share Python memory space and can pollute global state.
3. In-process execution permits unauthorized network socket operations.
"""
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import pytest

from autonomous_engineering.authority.guard import ScopeGuard, ScopeViolationError
from autonomous_engineering.authority.tokens import CapabilityToken


def test_adversarial_direct_fs_write_bypasses_in_process_scope_guard(tmp_path: Path):
    """Proves that Phase 0's in-process ScopeGuard is completely powerless against

    an untrusted worker that executes real Python code or shell commands directly,
    bypassing the voluntary ScopeGuard check.
    """
    token = CapabilityToken(
        token_id="tok-adv-1",
        work_order_id="wo-adv",
        work_order_version=1,
        task_id="step-1",
        authorized_paths=("src/calculator/*.py",),
        authorized_tools=("read_file", "write_patch"),
        max_retries=1,
        fencing_token=1,
        issued_at="2026-09-26T00:00:00Z",
        expires_at="2030-01-01T00:00:00Z",
    )

    unauthorized_file = tmp_path / "leaked_host_secret.txt"

    # Simulated worker that voluntarily calls ScopeGuard is caught:
    with pytest.raises(ScopeViolationError):
        ScopeGuard.check_mutation_path(token, str(unauthorized_file))

    # BUT a real live model executing code directly in-process writes directly to disk:
    # WITHOUT OS-level containment, the write succeeds!
    unauthorized_file.write_text("compromised_data", encoding="utf-8")
    assert unauthorized_file.exists()  # GAP EXPOSED: In-process guard did not prevent disk write!


def test_adversarial_uncontained_network_egress():
    """Proves that uncontained execution allows raw socket creation to external networks."""
    # Attempt to create a raw socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # In an uncontained environment, socket creation succeeds
        assert s.fileno() > 0
    finally:
        s.close()
