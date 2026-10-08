"""Root pytest configuration and physical environment prerequisite guards."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent

# Ensure REPO_ROOT is in sys.path
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PROTECTED_PROCESS_TEST_NAMES = {
    "test_gate10_campaign_process_isolation",
    "test_gate8_campaign_process_isolation",
    "test_gate_g10_protected_service_isolation",
    "test_gate_g13_protected_services_non_interference",
    "test_adversarial_16_protected_services_non_interference",
}

TOKEN_DEPENDENT_TEST_NAMES = {
    "test_gate_g14_physical_inference_end_to_end_execution",
    "test_gate_g14_real_inference_comparative_campaign",
    "test_gate_g12_protected_service_non_interference",
    "test_endpoint_health",
    "test_live_adapter_contract_and_model_completion",
    "test_controlled_live_execution_e2e",
    "test_live_endpoint_qualification_check",
}


def _has_protected_processes() -> bool:
    if os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("CI") == "true":
        return False
    try:
        res = subprocess.run(
            ["ps", "-p", "986,3130937,2093382", "-o", "pid="],
            capture_output=True,
            text=True,
            check=False,
        )
        pids = set(res.stdout.strip().split())
        return {"986", "3130937", "2093382"}.issubset(pids)
    except Exception:
        return False


def _has_bwrap() -> bool:
    return Path("/usr/bin/bwrap").exists() and shutil.which("bwrap") is not None


def _has_client_token() -> bool:
    return Path("/home/mike/.config/opencode/t5820-client-token").exists()


def pytest_runtest_setup(item: pytest.Item) -> None:
    # 1. Bubblewrap OS containment tests
    if "test_os_containment.py" in str(item.fspath):
        if not _has_bwrap():
            pytest.skip("Bubblewrap binary (/usr/bin/bwrap) not available on this host (physical qualification test)")

    # 2. Protected campaign processes non-interference tests (PID 986, 3130937, 2093382)
    if item.name in PROTECTED_PROCESS_TEST_NAMES:
        if not _has_protected_processes():
            pytest.skip("Protected host processes (PID 986, 3130937, 2093382) not running on this host (physical qualification test)")

    # 3. Physical live endpoint token dependent tests
    if item.name in TOKEN_DEPENDENT_TEST_NAMES:
        if not os.environ.get("AIHOST_RUN_LIVE_TESTS"):
            # Live tests send real work, which must come from a remote client through the gateway. Sealed phase
            # baselines (phase1, phase4) keep their historical endpoint and are not edited to follow the cutover.
            pytest.skip("Live endpoint tests run only when AIHOST_RUN_LIVE_TESTS=1")
        if not _has_client_token():
            pytest.skip("Physical client token (/home/mike/.config/opencode/t5820-client-token) not present on this host (physical qualification test)")
