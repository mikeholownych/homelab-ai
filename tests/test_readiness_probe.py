from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PROBE = REPO_ROOT / "roles/vllm_xpu/files/vllm-readiness-probe.sh"


def fake_tools(tmp_path: Path, invocation: str | None) -> dict[str, str]:
    bindir = tmp_path / "bin"
    bindir.mkdir(parents=True)
    systemctl = bindir / "systemctl"
    systemctl.write_text(
        "#!/bin/sh\n"
        + (f"printf '%s\\n' '{invocation}'\n" if invocation else "exit 1\n"),
        encoding="utf-8",
    )
    systemctl.chmod(0o755)
    curl = bindir / "curl"
    curl.write_text(
        "#!/bin/sh\n"
        "case \"$*\" in\n"
        "  *-w*) printf '200' ;;\n"
        "  *) printf '{\"data\":[{\"id\":\"model\"}]}' ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    return {"PATH": f"{bindir}:/usr/bin:/bin"}


def run_probe(tmp_path: Path, invocation: str | None) -> tuple[int, dict]:
    record = tmp_path / "readiness.json"
    env = os.environ.copy()
    env.update(fake_tools(tmp_path, invocation))
    env.update({
        "READINESS_RECORD": str(record),
        "EXPECTED_MODEL": "model",
        "VLLM_XPU_EXPECTED_MODEL": "model",
        "VLLM_READINESS_TIMEOUT_SECS": "1",
        "VLLM_READINESS_POLL_SECS": "0",
    })
    result = subprocess.run(
        ["/bin/sh", str(PROBE), "-"], env=env, capture_output=True, text=True, timeout=10,
    )
    return result.returncode, json.loads(record.read_text(encoding="utf-8"))


def test_authoritative_invocation_id_binds_ready_evidence(tmp_path):
    invocation = "d279b0c9757240ac8b89695cbde627a6"
    code, record = run_probe(tmp_path, invocation)
    assert code == 0
    assert record["readiness_state"] == "READY"
    assert record["service_invocation_id"] == invocation
    assert record["boot_id"] != ""


def test_missing_invocation_id_fails_closed(tmp_path):
    code, record = run_probe(tmp_path, None)
    assert code != 0
    assert record["readiness_state"] == "STALLED"
    assert record["service_invocation_id"] == ""
    assert "SERVICE_INVOCATION_ID_UNAVAILABLE" in record["probe_note"]


def test_changed_invocation_id_is_not_reused(tmp_path):
    first = "11111111111111111111111111111111"
    second = "22222222222222222222222222222222"
    _, first_record = run_probe(tmp_path / "first", first)
    _, second_record = run_probe(tmp_path / "second", second)
    assert first_record["service_invocation_id"] == first
    assert second_record["service_invocation_id"] == second
    assert second_record["service_invocation_id"] != first_record["service_invocation_id"]


def test_pid_is_not_used_as_invocation_identity():
    source = PROBE.read_text(encoding="utf-8")
    assert "systemctl show" in source
    assert '${INVOCATION_ID:-' not in source
    assert "$$" not in source
