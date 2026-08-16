#!/usr/bin/env python3
from __future__ import annotations

import argparse
import atexit
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE_PATH = REPO_ROOT / "tests" / "integration" / "Dockerfile.baseline"
PINNED_BASE_IMAGE = "ubuntu@sha256:561618e2c15bf2397621dd04f96926663a3b5616c189cf7e38db7e82f5c538ea"
HARNESS_IMAGE = "aihost-baseline-harness:ubuntu24.04-sha561618e2"
BUILD_TIMEOUT_SECONDS = 300
RUN_TIMEOUT_SECONDS = 300
CLEANUP_TIMEOUT_SECONDS = 30


class HarnessError(RuntimeError):
    pass


class DockerBaselineHarness:
    def __init__(self, timeout_seconds: int) -> None:
        self.deadline = time.monotonic() + timeout_seconds
        self.container_name = f"aihost-baseline-{uuid.uuid4().hex[:12]}"
        self.cleaned = False
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._handle_signal)
        atexit.register(self.cleanup)

    def _handle_signal(self, signum: int, _frame: object) -> None:
        self.cleanup()
        raise SystemExit(128 + signum)

    def cleanup(self) -> None:
        if self.cleaned:
            return
        self.cleaned = True
        subprocess.run(
            ["docker", "rm", "-f", self.container_name],
            check=False,
            capture_output=True,
            text=True,
            timeout=CLEANUP_TIMEOUT_SECONDS,
        )
        inspect_result = subprocess.run(
            ["docker", "inspect", self.container_name],
            check=False,
            capture_output=True,
            text=True,
            timeout=CLEANUP_TIMEOUT_SECONDS,
        )
        if inspect_result.returncode == 0:
            raise HarnessError(f"Expected harness container {self.container_name} to be deleted during cleanup.")

    def remaining_seconds(self) -> int:
        remaining = int(self.deadline - time.monotonic())
        if remaining <= 0:
            raise HarnessError("Harness timeout exceeded before completion.")
        return remaining

    def run(
        self,
        argv: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        check: bool = True,
        timeout_override: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        timeout = timeout_override if timeout_override is not None else self.remaining_seconds()
        completed = subprocess.run(
            argv,
            cwd=str(cwd) if cwd else None,
            env=env,
            check=False,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        if check and completed.returncode != 0:
            raise HarnessError(
                f"Command failed ({completed.returncode}): {format_argv(argv)}\n"
                f"{completed.stdout}{completed.stderr}"
            )
        return completed

    def require_docker(self) -> None:
        docker_path = shutil.which("docker")
        if docker_path is None:
            raise HarnessError("Docker is required for baseline container idempotency tests but was not found in PATH.")
        version = self.run(["docker", "version", "--format", "{{.Server.Version}}"]).stdout.strip()
        print(f"Using Docker server {version}")
        print(f"Using pinned base image {PINNED_BASE_IMAGE}")

    def build_image(self) -> None:
        print("Building pinned Ubuntu baseline harness image...")
        completed = self.run(
            [
                "docker",
                "build",
                "--file",
                str(DOCKERFILE_PATH),
                "--tag",
                HARNESS_IMAGE,
                str(REPO_ROOT),
            ],
            timeout_override=min(BUILD_TIMEOUT_SECONDS, self.remaining_seconds()),
        )
        sys.stdout.write(completed.stdout)
        sys.stderr.write(completed.stderr)

    def start_container(self) -> None:
        print(f"Starting privileged harness container {self.container_name}...")
        print("Running privileged because UFW, mount, and related kernel-facing probes require container capabilities.")
        completed = self.run(
            [
                "docker",
                "run",
                "--detach",
                "--privileged",
                "--network",
                "none",
                "--name",
                self.container_name,
                "--hostname",
                "aihost-baseline",
                "--volume",
                f"{REPO_ROOT}:/src:ro",
                HARNESS_IMAGE,
                "sleep",
                "infinity",
            ]
        )
        print(completed.stdout.strip())

    def exec(self, argv: list[str], *, workdir: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        docker_argv = ["docker", "exec"]
        if workdir:
            docker_argv.extend(["--workdir", workdir])
        docker_argv.append(self.container_name)
        docker_argv.extend(argv)
        return self.run(docker_argv, check=check)

    def exec_bash(self, script: str, *, workdir: str | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
        return self.exec(["bash", "-lc", script], workdir=workdir, check=check)

    def prepare_workspace(self) -> None:
        print("Copying repository into container workspace...")
        completed = self.exec_bash(
            "mkdir -p /workspace/repo && rsync -a --delete --exclude .git --exclude .venv --exclude .ansible /src/ /workspace/repo/",
            check=True,
        )
        sys.stdout.write(completed.stdout)
        sys.stderr.write(completed.stderr)

    def run_playbook(self, playbook: str, extra_vars: dict[str, object]) -> tuple[str, int]:
        completed = self.run(
            [
                "docker",
                "exec",
                "--workdir",
                "/workspace/repo",
                self.container_name,
                "env",
                "ANSIBLE_CONFIG=ansible.cfg",
                "ansible-playbook",
                "-i",
                "localhost,",
                "-c",
                "local",
                playbook,
                "-e",
                json.dumps(extra_vars),
            ],
            timeout_override=min(RUN_TIMEOUT_SECONDS, self.remaining_seconds()),
        )
        output = completed.stdout + completed.stderr
        changed = parse_changed_count(output)
        return output, changed

    def read_text(self, path: str) -> str:
        return self.exec(["cat", path]).stdout

    def path_exists(self, path: str) -> bool:
        return self.exec(["test", "-e", path], check=False).returncode == 0

    def command_stdout(self, argv: list[str]) -> str:
        return self.exec(argv).stdout.strip()

    def command_stdout_bash(self, script: str) -> str:
        return self.exec_bash(script).stdout.strip()


def format_argv(argv: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in argv)


def parse_changed_count(output: str) -> int:
    matches = re.findall(r"localhost\s*:.*changed=(\d+)", output)
    if not matches:
        raise HarnessError(f"Unable to parse Ansible recap from output:\n{output}")
    return int(matches[-1])


def require(condition: bool, message: str) -> None:
    if not condition:
        raise HarnessError(message)


def assert_playbook_change(label: str, changed: int, *, expected_zero: bool) -> None:
    if expected_zero:
        require(changed == 0, f"{label} expected changed=0 but observed changed={changed}.")
    else:
        require(changed > 0, f"{label} expected changes but observed changed={changed}.")


def assert_group_membership(harness: DockerBaselineHarness, user: str, expected_groups: set[str]) -> None:
    actual_groups = set(harness.command_stdout(["id", "-nG", user]).split())
    require(
        actual_groups == expected_groups,
        f"{user} groups mismatch: expected {sorted(expected_groups)}, observed {sorted(actual_groups)}.",
    )


def assert_file_contains_exact_key(harness: DockerBaselineHarness, path: str, expected_key: str) -> None:
    content = harness.read_text(path).strip()
    require(content == expected_key, f"{path} did not contain the expected authoritative key set.\nObserved:\n{content}")


def assert_json_state(harness: DockerBaselineHarness, path: str, expected: dict[str, object]) -> None:
    observed = json.loads(harness.read_text(path))
    require(observed == expected, f"{path} mismatch.\nExpected: {expected}\nObserved: {observed}")


def assert_initial_full_state(harness: DockerBaselineHarness) -> None:
    assert_group_membership(harness, "ops", {"ops", "sudo"})
    assert_group_membership(harness, "local-ai", {"local-ai", "render", "video"})
    assert_file_contains_exact_key(
        harness,
        "/home/ops/.ssh/authorized_keys",
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIJXH3onYv0WQGFFS0XUQ0K3Mx3P4W+H6Ww2x8a6l0g2m baseline-initial@example",
    )
    ssh_effective = harness.command_stdout(["/usr/sbin/sshd", "-T", "-f", "/etc/ssh/sshd_config"])
    for expected_line in (
        "passwordauthentication no",
        "permitrootlogin no",
        "kbdinteractiveauthentication no",
        "allowtcpforwarding yes",
        "allowagentforwarding no",
        "x11forwarding no",
    ):
        require(expected_line in ssh_effective.lower(), f"Missing SSH effective setting: {expected_line}")
    ufw_status = harness.command_stdout(["ufw", "status", "numbered"])
    require("10.10.0.0/24" in ufw_status, f"Expected management CIDR in UFW status.\n{ufw_status}")
    require("192.0.2.0/24" in ufw_status, f"Expected inference CIDR in UFW status.\n{ufw_status}")
    require("8080/tcp" in ufw_status or "8080" in ufw_status, f"Expected inference port in UFW status.\n{ufw_status}")
    require(
        "hold" in harness.command_stdout(["dpkg", "--get-selections", "sudo"]),
        "Expected sudo to be held after initial package-policy convergence.",
    )
    require(
        harness.path_exists("/etc/apt/preferences.d/90-aihost-managed.pref"),
        "Expected managed apt preferences file to exist after initial convergence.",
    )
    assert_json_state(
        harness,
        "/var/lib/aihost/base-os-package-policy-state.json",
        {"holds": ["sudo"], "pin_packages": ["sudo"]},
    )
    assert_json_state(
        harness,
        "/var/lib/aihost/security-ufw-state.json",
        {
            "enabled": True,
            "rules": [
                {
                    "scope": "management",
                    "src": "10.10.0.0/24",
                    "port": "22",
                    "proto": "tcp",
                    "comment": "Managed SSH access",
                },
                {
                    "scope": "inference",
                    "src": "192.0.2.0/24",
                    "port": "8080",
                    "proto": "tcp",
                    "comment": "Managed inference API access",
                },
            ],
        },
    )
    require(
        harness.path_exists("/etc/netplan/60-aihost.yaml"),
        "Expected managed netplan file to exist after convergence.",
    )
    require(
        " /mnt/aihost-cache " in harness.command_stdout_bash("mount | grep ' /mnt/aihost-cache '"),
        "Expected tmpfs storage mount to be active.",
    )
    require(
        harness.path_exists("/etc/chrony/sources.d/60-aihost.sources"),
        "Expected chrony source configuration to exist in the initial phase.",
    )
    require(
        not harness.path_exists("/etc/systemd/timesyncd.conf.d/60-aihost.conf"),
        "Expected timesyncd configuration to be absent in the initial chrony phase.",
    )


def assert_transition_full_state(harness: DockerBaselineHarness) -> None:
    assert_group_membership(harness, "ops", {"ops"})
    assert_group_membership(harness, "local-ai", {"local-ai"})
    assert_file_contains_exact_key(
        harness,
        "/home/ops/.ssh/authorized_keys",
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILW2Wl9JY+v7k2Qw4VgU4t4M1Lh8mK5A2n5s7a1Qd1Yw baseline-transition@example",
    )
    ufw_status = harness.command_stdout(["ufw", "status"])
    require("inactive" in ufw_status.lower(), f"Expected UFW to be inactive after transition.\n{ufw_status}")
    require(
        "hold" not in harness.command_stdout(["dpkg", "--get-selections", "sudo"]),
        "Expected sudo hold to be removed after transition.",
    )
    require(
        not harness.path_exists("/etc/apt/preferences.d/90-aihost-managed.pref"),
        "Expected managed apt preferences file to be removed after transition.",
    )
    assert_json_state(
        harness,
        "/var/lib/aihost/base-os-package-policy-state.json",
        {"holds": [], "pin_packages": []},
    )
    assert_json_state(
        harness,
        "/var/lib/aihost/security-ufw-state.json",
        {"enabled": False, "rules": []},
    )
    require(
        harness.path_exists("/etc/systemd/timesyncd.conf.d/60-aihost.conf"),
        "Expected timesyncd configuration to exist after transition.",
    )
    require(
        not harness.path_exists("/etc/chrony/sources.d/60-aihost.sources"),
        "Expected chrony configuration to be removed after transition.",
    )


def run_users_groups_transition(harness: DockerBaselineHarness) -> None:
    output, changed = harness.run_playbook(
        "tests/integration/baseline_container_users_transition.yml",
        {"users_transition_phase": False},
    )
    print("=== users transition initial convergence ===")
    print(output)
    assert_playbook_change("users transition initial convergence", changed, expected_zero=False)
    assert_group_membership(harness, "ops", {"ops", "sudo"})
    assert_group_membership(harness, "local-ai", {"local-ai", "render", "video"})

    output, changed = harness.run_playbook(
        "tests/integration/baseline_container_users_transition.yml",
        {"users_transition_phase": True},
    )
    print("=== users transition removal convergence ===")
    print(output)
    assert_playbook_change("users transition removal convergence", changed, expected_zero=False)
    assert_group_membership(harness, "ops", {"ops"})
    assert_group_membership(harness, "local-ai", {"local-ai"})

    output, changed = harness.run_playbook(
        "tests/integration/baseline_container_users_transition.yml",
        {"users_transition_phase": True},
    )
    print("=== users transition idempotency rerun ===")
    print(output)
    assert_playbook_change("users transition idempotency rerun", changed, expected_zero=True)


def run_full_idempotency(harness: DockerBaselineHarness) -> None:
    output, changed = harness.run_playbook(
        "tests/integration/baseline_container.yml",
        {"baseline_transition_phase": False},
    )
    print("=== initial convergence ===")
    print(output)
    assert_playbook_change("initial convergence", changed, expected_zero=False)

    output, changed = harness.run_playbook(
        "tests/integration/baseline_container.yml",
        {"baseline_transition_phase": False},
    )
    print("=== initial idempotency rerun ===")
    print(output)
    assert_playbook_change("initial idempotency rerun", changed, expected_zero=True)
    assert_initial_full_state(harness)

    output, changed = harness.run_playbook(
        "tests/integration/baseline_container.yml",
        {"baseline_transition_phase": True},
    )
    print("=== transition convergence ===")
    print(output)
    assert_playbook_change("transition convergence", changed, expected_zero=False)

    output, changed = harness.run_playbook(
        "tests/integration/baseline_container.yml",
        {"baseline_transition_phase": True},
    )
    print("=== transition idempotency rerun ===")
    print(output)
    assert_playbook_change("transition idempotency rerun", changed, expected_zero=True)
    assert_transition_full_state(harness)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run baseline convergence probes inside a pinned Ubuntu Docker container.")
    parser.add_argument(
        "--mode",
        choices=("idempotency", "users-groups-transition"),
        default="idempotency",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Overall timeout budget in seconds for build, execution, and cleanup.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    harness = DockerBaselineHarness(timeout_seconds=args.timeout)
    try:
        harness.require_docker()
        harness.build_image()
        harness.start_container()
        harness.prepare_workspace()
        if args.mode == "users-groups-transition":
            run_users_groups_transition(harness)
        else:
            run_full_idempotency(harness)
    except subprocess.TimeoutExpired as exc:
        raise HarnessError(f"Command timed out after {exc.timeout} seconds: {format_argv(exc.cmd)}") from exc
    except HarnessError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        harness.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
