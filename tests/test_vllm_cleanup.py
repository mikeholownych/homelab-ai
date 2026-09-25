from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "roles/vllm_xpu/files/vllm-xpu-cleanup.sh"


def make_fake_podman(bin_dir: Path, log: Path, exit_code: int = 0) -> None:
    podman = bin_dir / "podman"
    podman.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$@\" > {str(log)!r}\n"
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    podman.chmod(podman.stat().st_mode | stat.S_IXUSR)


def run_cleanup(tmp_path: Path, *, exit_code: int = 0) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "podman.args"
    make_fake_podman(bin_dir, log, exit_code)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return subprocess.run(
        [str(SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_cleanup_removes_only_the_service_owned_container(tmp_path: Path) -> None:
    result = run_cleanup(tmp_path)

    assert result.returncode == 0
    assert (tmp_path / "podman.args").read_text().splitlines() == [
        "rm",
        "--force",
        "--ignore",
        "--time",
        "30",
        "vllm-xpu",
    ]


def test_cleanup_is_successful_when_container_already_disappeared(tmp_path: Path) -> None:
    result = run_cleanup(tmp_path, exit_code=125)

    assert result.returncode == 0


def test_cleanup_is_wired_to_systemd_stop_and_uses_cgroup_kill() -> None:
    template = (REPO_ROOT / "roles/vllm_xpu/templates/vllm.service.j2").read_text()

    assert "KillMode=control-group" in template
    assert "SendSIGKILL=yes" in template
    assert "ExecStopPost=" in template
    assert "vllm-xpu-cleanup" in template


def test_cleanup_applies_to_startup_timeout_and_partial_load_failures() -> None:
    template = (REPO_ROOT / "roles/vllm_xpu/templates/vllm.service.j2").read_text()

    assert "TimeoutStartSec=" in template
    assert "TimeoutStopSec=" in template
    assert "ExecStopPost=" in template


def test_launcher_reaps_readiness_child_and_stops_it_after_container_exit() -> None:
    launcher = (REPO_ROOT / "roles/vllm_xpu/files/vllm-xpu-runner.sh").read_text()

    assert "trap reap_readiness CHLD" in launcher
    assert '"$RUNTIME_BIN" run \\' in launcher
    assert "CONTAINER_PID=\"$!\"" in launcher
    assert "wait \"$CONTAINER_PID\"" in launcher
    assert 'kill "$READINESS_PID"' in launcher


def test_launcher_and_cleanup_share_an_explicit_runtime_and_container_identity() -> None:
    launcher = (REPO_ROOT / "roles/vllm_xpu/files/vllm-xpu-runner.sh").read_text()
    cleanup = SCRIPT.read_text()

    assert 'VLLM_RUNTIME_BIN:-' in launcher
    assert 'VLLM_RUNTIME_BIN:-podman' in cleanup
    assert 'VLLM_CONTAINER_NAME:-vllm-xpu' in launcher
    assert 'VLLM_CONTAINER_NAME:-vllm-xpu' in cleanup
    assert "Environment=VLLM_RUNTIME_BIN=podman" in (REPO_ROOT / "roles/vllm_xpu/templates/vllm.service.j2").read_text()
