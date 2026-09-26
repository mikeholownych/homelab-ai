"""Linux Operating-System Execution Containment via Bubblewrap (bwrap)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any


class SandboxViolationError(RuntimeError):
    pass


@dataclass(frozen=True)
class SandboxExecutionResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float


class BwrapSandbox:
    """Hardened execution boundary using Linux namespaces.

    Invariants:
    - Filesystem Containment: System libraries mounted strictly read-only.
      Host sensitive directories (/home, /root, /etc/shadow) completely unmounted.
      Only the authorized disposable worktree is mounted read-write.
    - Network Isolation: Network namespace unshared (--unshare-net); zero network egress.
    - Process Isolation: PID namespace unshared (--unshare-pid); host processes invisible.
    - Environment Sanitization: Clears host environment (--clearenv) to prevent credential leakage.
    - Lifecycle Containment: Child processes killed when parent exits (--die-with-parent).
    """

    BWRAP_PATH = "/usr/bin/bwrap"
    SITE_PACKAGES = "/home/mike/.local/lib/python3.12/site-packages"

    def __init__(self, worktree_dir: Path | str, allow_network: bool = False) -> None:
        self.worktree_dir = Path(worktree_dir).resolve()
        self.allow_network = allow_network
        if not self.is_available():
            raise RuntimeError(f"Bubblewrap binary not found at {self.BWRAP_PATH}")

    @classmethod
    def is_available(cls) -> bool:
        return Path(cls.BWRAP_PATH).exists() and shutil.which("bwrap") is not None

    def execute(
        self,
        command: list[str],
        timeout: float = 30.0,
        extra_env: dict[str, str] | None = None,
    ) -> SandboxExecutionResult:
        import time

        bwrap_args = [
            self.BWRAP_PATH,
            # Read-only mounts for system runtime
            "--ro-bind", "/usr", "/usr",
            "--ro-bind", "/lib", "/lib",
            "--proc", "/proc",
            "--dev", "/dev",
            "--tmpfs", "/tmp",
        ]

        if Path("/lib64").exists():
            bwrap_args.extend(["--ro-bind", "/lib64", "/lib64"])
        if Path("/bin").exists() and not Path("/bin").is_symlink():
            bwrap_args.extend(["--ro-bind", "/bin", "/bin"])
        if Path("/etc/alternatives").exists():
            bwrap_args.extend(["--ro-bind", "/etc/alternatives", "/etc/alternatives"])

        # Read-only bind mount for python site-packages (for pytest, etc.)
        if Path(self.SITE_PACKAGES).exists():
            bwrap_args.extend(["--ro-bind", self.SITE_PACKAGES, "/site-packages"])

        # Read-write mount ONLY on the authorized worktree directory
        self.worktree_dir.mkdir(parents=True, exist_ok=True)
        bwrap_args.extend(["--bind", str(self.worktree_dir), str(self.worktree_dir)])
        bwrap_args.extend(["--chdir", str(self.worktree_dir)])

        # Namespaces
        bwrap_args.extend([
            "--unshare-user",
            "--unshare-ipc",
            "--unshare-pid",
            "--unshare-uts",
            "--unshare-cgroup",
            "--die-with-parent",
        ])

        if not self.allow_network:
            bwrap_args.append("--unshare-net")

        # Environment wiping
        bwrap_args.extend([
            "--clearenv",
            "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin",
            "--setenv", "HOME", "/tmp",
            "--setenv", "PYTHONPATH", f"/site-packages:{self.worktree_dir}",
        ])

        if extra_env:
            for k, v in extra_env.items():
                bwrap_args.extend(["--setenv", k, v])

        # Command to execute
        bwrap_args.extend(["--", *command])

        start_time = time.monotonic()
        try:
            res = subprocess.run(
                bwrap_args,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            duration = time.monotonic() - start_time
            return SandboxExecutionResult(
                command=command,
                returncode=res.returncode,
                stdout=res.stdout,
                stderr=res.stderr,
                duration_seconds=duration,
            )
        except subprocess.TimeoutExpired as exc:
            duration = time.monotonic() - start_time
            return SandboxExecutionResult(
                command=command,
                returncode=124,
                stdout=exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ""),
                stderr=f"Execution deadline exceeded ({timeout}s)",
                duration_seconds=duration,
            )
