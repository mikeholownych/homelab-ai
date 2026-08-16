from __future__ import annotations

import fcntl
import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WRAPPER_PATH = REPO_ROOT / "scripts" / "run-ansible-snapshot"
VALIDATION_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "schemas" / "validation.valid.json"
SECRET_SENTINEL = "SENTINEL-DO-NOT-LEAK-7429"


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def make_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def build_fake_tools(bin_dir: Path, log_path: Path) -> None:
    make_executable(
        bin_dir / "git",
        textwrap.dedent(
            f"""\
            #!/usr/bin/env python3
            import os
            import sys
            from pathlib import Path

            log_path = Path({str(log_path)!r})
            argv = sys.argv[1:]
            log_path.write_text(log_path.read_text(encoding="utf-8") + "git " + " ".join(argv) + "\\n" if log_path.exists() else "git " + " ".join(argv) + "\\n", encoding="utf-8")
            banned = {{"fetch", "pull", "checkout", "reset"}}
            if any(arg in banned for arg in argv):
                print("unexpected git mutation or network command", file=sys.stderr)
                sys.exit(97)
            if "rev-parse" in argv and "HEAD" in argv:
                print(os.environ.get("FAKE_GIT_SHA", "0123456789abcdef0123456789abcdef01234567"))
                sys.exit(0)
            if "status" in argv:
                sys.stdout.write(os.environ.get("FAKE_GIT_STATUS", ""))
                sys.exit(0)
            print("unsupported git invocation", file=sys.stderr)
            sys.exit(96)
            """
        ),
    )
    make_executable(
        bin_dir / "ansible-playbook",
        textwrap.dedent(
            f"""\
            #!/usr/bin/env python3
            import json
            import os
            import sys
            from pathlib import Path

            log_path = Path({str(log_path)!r})
            validation_fixture = Path({str(VALIDATION_FIXTURE)!r})
            argv = sys.argv[1:]
            log_path.write_text(log_path.read_text(encoding="utf-8") + "ansible-playbook " + " ".join(argv) + "\\n" if log_path.exists() else "ansible-playbook " + " ".join(argv) + "\\n", encoding="utf-8")
            run_dir = Path(os.environ["LOCAL_AI_EVIDENCE_RUN_DIR"])
            playbook = Path(argv[-1]).name
            if playbook == "validate.yml" and os.environ.get("FAKE_WRITE_VALIDATION") == "1":
                payload = json.loads(validation_fixture.read_text(encoding="utf-8"))
                manifest_payload = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
                payload["git_sha"] = os.environ.get("FAKE_GIT_SHA", "0123456789abcdef0123456789abcdef01234567")
                payload["simulated"] = "--check" in argv
                payload["generated_at"] = manifest_payload["run"]["started_at"]
                if "--limit" in argv:
                    payload["node"]["id"] = argv[argv.index("--limit") + 1]
                if os.environ.get("FAKE_INVALID_VALIDATION") == "1":
                    payload["summary"]["classification"] = os.environ.get("FAKE_SECRET_SENTINEL", "invalid")
                (run_dir / "validation.json").write_text(json.dumps(payload, indent=2) + "\\n", encoding="utf-8")
            command_log = os.environ.get("FAKE_COMMAND_LOG")
            if command_log:
                with Path(command_log).open("a", encoding="utf-8") as handle:
                    handle.write("argv:" + " ".join(argv) + "\\n")
            env_capture = os.environ.get("FAKE_ENV_CAPTURE")
            if env_capture:
                with Path(env_capture).open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({{
                        "ANSIBLE_CONFIG": os.environ.get("ANSIBLE_CONFIG"),
                        "cwd": os.getcwd(),
                        "playbook": playbook,
                    }}) + "\\n")
            artifact_size_mb = int(os.environ.get("FAKE_EXTRA_ARTIFACT_MB", "0"))
            if artifact_size_mb > 0:
                artifact_path = run_dir / "artifact.bin"
                chunk = b"x" * (1024 * 1024)
                with artifact_path.open("wb") as handle:
                    for _ in range(artifact_size_mb):
                        handle.write(chunk)
            if playbook == "validate.yml":
                sys.stdout.write(os.environ.get("FAKE_VALIDATE_STDOUT", os.environ.get("FAKE_ANSIBLE_STDOUT", "")))
                sys.stderr.write(os.environ.get("FAKE_VALIDATE_STDERR", ""))
                sys.exit(int(os.environ.get("FAKE_VALIDATE_EXIT", os.environ.get("FAKE_ANSIBLE_EXIT", "0"))))
            sys.stdout.write(os.environ.get("FAKE_ANSIBLE_STDOUT", ""))
            sys.stderr.write(os.environ.get("FAKE_ANSIBLE_STDERR", ""))
            sys.exit(int(os.environ.get("FAKE_ANSIBLE_EXIT", "0")))
            """
        ),
    )


def create_repo(root: Path) -> Path:
    (root / "playbooks").mkdir(parents=True, exist_ok=True)
    (root / "inventory" / "production").mkdir(parents=True, exist_ok=True)
    (root / "evidence").mkdir(parents=True, exist_ok=True)
    (root / ".pytest_cache").mkdir(parents=True, exist_ok=True)
    (root / "ansible.cfg").write_text("[defaults]\nstdout_callback = yaml\n", encoding="utf-8")
    for playbook in ("site.yml", "drift-check.yml", "patch.yml", "validate.yml", "benchmark.yml", "facts-export.yml", "bootstrap.yml"):
        (root / "playbooks" / playbook).write_text("---\n[]\n", encoding="utf-8")
    (root / "inventory" / "production" / "hosts.yml").write_text("all:\n  hosts:\n    ai-p620-01:\n", encoding="utf-8")
    return root


def run_wrapper(
    repo_root: Path,
    evidence_root: Path,
    lock_root: Path,
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    schema_root: Path | None = None,
    playbook: str = "site.yml",
    inventory: str = "inventory/production/hosts.yml",
    target: str = "ai-p620-01",
    extra_args: list[str] | None = None,
    umask_value: int | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        str(WRAPPER_PATH),
        "--repo-root",
        str(repo_root),
        "--schema-root",
        str(schema_root if schema_root is not None else (REPO_ROOT / "schemas")),
        "--inventory",
        inventory,
        "--target",
        target,
        "--playbook",
        playbook,
        "--evidence-root",
        str(evidence_root),
        "--lock-root",
        str(lock_root),
    ]
    if extra_args:
        command.extend(extra_args)
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        command,
        cwd=cwd if cwd is not None else REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=merged_env,
        preexec_fn=(lambda: os.umask(umask_value)) if umask_value is not None else None,
    )


def start_wrapper(
    repo_root: Path,
    evidence_root: Path,
    lock_root: Path,
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    schema_root: Path | None = None,
    playbook: str = "site.yml",
    inventory: str = "inventory/production/hosts.yml",
    target: str = "ai-p620-01",
    extra_args: list[str] | None = None,
    umask_value: int | None = None,
) -> subprocess.Popen[str]:
    command = [
        str(WRAPPER_PATH),
        "--repo-root",
        str(repo_root),
        "--schema-root",
        str(schema_root if schema_root is not None else (REPO_ROOT / "schemas")),
        "--inventory",
        inventory,
        "--target",
        target,
        "--playbook",
        playbook,
        "--evidence-root",
        str(evidence_root),
        "--lock-root",
        str(lock_root),
    ]
    if extra_args:
        command.extend(extra_args)
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.Popen(
        command,
        cwd=cwd if cwd is not None else REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=merged_env,
        preexec_fn=(lambda: os.umask(umask_value)) if umask_value is not None else None,
    )


def find_descendant_pid_with_needle(root_pid: int, needle: str) -> int | None:
    ps_result = subprocess.run(
        ["ps", "-eo", "pid=,ppid=,args="],
        check=False,
        capture_output=True,
        text=True,
    )
    process_rows: dict[int, tuple[int, str]] = {}
    for line in ps_result.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid_text, ppid_text, args = stripped.split(None, 2)
        process_rows[int(pid_text)] = (int(ppid_text), args)

    descendants = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, (ppid, _args) in process_rows.items():
            if pid in descendants:
                continue
            if ppid in descendants:
                descendants.add(pid)
                changed = True

    for pid in sorted(descendants):
        if pid == root_pid:
            continue
        args = process_rows[pid][1]
        if needle in args:
            return pid
    return None


class RunWrapperTests(unittest.TestCase):
    def test_wrapper_creates_host_timestamp_run_and_records_successful_site_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            repo_root = create_repo(temp_root / "repo")
            evidence_root = temp_root / "evidence-root"
            evidence_root.mkdir()
            lock_path = temp_root / "ansible.lock"
            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            tool_log = temp_root / "tool.log"
            build_fake_tools(bin_dir, tool_log)
            env_capture = temp_root / "ansible-env.log"

            env = {
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "FAKE_GIT_STATUS": "?? evidence/dev-note.txt\n?? .pytest_cache/state\n",
                "FAKE_ANSIBLE_STDOUT": textwrap.dedent(
                    """\
                    PLAY RECAP *********************************************************************
                    ai-p620-01 : ok=12 changed=3 unreachable=0 failed=0 skipped=1 rescued=0 ignored=0
                    """
                ),
                "FAKE_WRITE_VALIDATION": "1",
                "FAKE_VALIDATE_STDOUT": textwrap.dedent(
                    """\
                    PLAY RECAP *********************************************************************
                    ai-p620-01 : ok=2 changed=0 unreachable=0 failed=0 skipped=0 rescued=0 ignored=0
                    """
                ),
                "LOCAL_AI_DEPLOYED_ROOT": str(temp_root),
                "FAKE_COMMAND_LOG": str(temp_root / "commands.log"),
                "FAKE_ENV_CAPTURE": str(env_capture),
                "ANSIBLE_CONFIG": "/tmp/hostile-ansible.cfg",
            }

            result = run_wrapper(
                repo_root,
                evidence_root,
                lock_path,
                cwd=temp_root,
                env=env,
                playbook="site.yml",
                extra_args=["--validate-after-site", "--simulate"],
            )

            self.assertEqual(0, result.returncode, result.stderr)
            host_dir = evidence_root / "ai-p620-01"
            runs = list(host_dir.iterdir())
            self.assertEqual(1, len(runs))
            run_dir = runs[0]
            self.assertRegex(run_dir.name, r"^\d{4}-\d{2}-\d{2}T\d{6}Z$")
            manifest = load_json(run_dir / "manifest.json")
            self.assertEqual("complete", manifest["finalization"]["state"])
            self.assertEqual("captured", manifest["status"])
            self.assertEqual("site.yml", manifest["run"]["playbook"])
            self.assertEqual("inventory/production/hosts.yml", manifest["run"]["inventory"])
            self.assertEqual("ai-p620-01", manifest["collection_target"]["node_id"])
            self.assertEqual(True, manifest["simulated"])
            self.assertRegex(manifest["git_sha"], r"^[0-9a-f]{40}$")
            self.assertEqual(0, manifest["run"]["ansible"]["exit_code"])
            self.assertEqual(14, manifest["run"]["ansible"]["recap"]["totals"]["ok"])
            self.assertEqual(3, manifest["run"]["ansible"]["recap"]["totals"]["changed"])
            self.assertEqual("PASS", manifest["run"]["validation"]["status"])
            self.assertEqual("healthy", manifest["run"]["validation"]["classification"])
            self.assertEqual(True, manifest["run"]["repository"]["clean"])
            self.assertIn("evidence/", manifest["run"]["repository"]["allowlist"])
            self.assertIn("ansible-run.json", (run_dir / "SHA256SUMS").read_text(encoding="utf-8"))
            tool_log_text = tool_log.read_text(encoding="utf-8")
            self.assertNotIn("fetch", tool_log_text)
            self.assertNotIn("pull", tool_log_text)
            self.assertNotIn("checkout", tool_log_text)
            self.assertNotIn("reset", tool_log_text)
            self.assertIn("--check", Path(env["FAKE_COMMAND_LOG"]).read_text(encoding="utf-8"))
            env_lines = env_capture.read_text(encoding="utf-8").splitlines()
            self.assertEqual(2, len(env_lines))
            for line in env_lines:
                invocation = json.loads(line)
                self.assertEqual(str(repo_root / "ansible.cfg"), invocation["ANSIBLE_CONFIG"])
                self.assertEqual(str(repo_root), invocation["cwd"])

    def test_wrapper_finalizes_and_returns_primary_ansible_exit_code_when_validation_is_malformed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            repo_root = create_repo(temp_root / "repo")
            evidence_root = temp_root / "evidence-root"
            evidence_root.mkdir()
            lock_path = temp_root / "ansible.lock"
            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            tool_log = temp_root / "tool.log"
            build_fake_tools(bin_dir, tool_log)

            env = {
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "FAKE_ANSIBLE_EXIT": "42",
                "FAKE_ANSIBLE_STDOUT": textwrap.dedent(
                    """\
                    PLAY RECAP *********************************************************************
                    ai-p620-01 : ok=4 changed=1 unreachable=0 failed=1 skipped=0 rescued=0 ignored=0
                    """
                ),
                "FAKE_VALIDATE_STDOUT": textwrap.dedent(
                    """\
                    PLAY RECAP *********************************************************************
                    ai-p620-01 : ok=1 changed=0 unreachable=0 failed=0 skipped=0 rescued=0 ignored=0
                    """
                ),
                "FAKE_WRITE_VALIDATION": "1",
                "FAKE_INVALID_VALIDATION": "1",
                "FAKE_SECRET_SENTINEL": SECRET_SENTINEL,
                "LOCAL_AI_DEPLOYED_ROOT": str(temp_root),
            }

            result = run_wrapper(
                repo_root,
                evidence_root,
                lock_path,
                env=env,
                playbook="site.yml",
                extra_args=["--validate-after-site"],
            )

            self.assertEqual(42, result.returncode)
            run_dir = next((evidence_root / "ai-p620-01").iterdir())
            manifest = load_json(run_dir / "manifest.json")
            self.assertEqual("incomplete", manifest["finalization"]["state"])
            self.assertEqual(42, manifest["run"]["ansible"]["exit_code"])
            self.assertEqual(1, manifest["run"]["ansible"]["recap"]["totals"]["failed"])
            self.assertTrue((run_dir / "SHA256SUMS").exists())
            self.assertNotIn(SECRET_SENTINEL, manifest["finalization"]["reason"])
            self.assertNotIn(SECRET_SENTINEL, result.stderr)

    def test_wrapper_exit_zero_without_required_validation_returns_distinct_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            repo_root = create_repo(temp_root / "repo")
            evidence_root = temp_root / "evidence-root"
            evidence_root.mkdir()
            lock_path = temp_root / "ansible.lock"
            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            tool_log = temp_root / "tool.log"
            build_fake_tools(bin_dir, tool_log)

            env = {
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "FAKE_ANSIBLE_STDOUT": textwrap.dedent(
                    """\
                    PLAY RECAP *********************************************************************
                    ai-p620-01 : ok=3 changed=1 unreachable=0 failed=0 skipped=0 rescued=0 ignored=0
                    """
                ),
                "LOCAL_AI_DEPLOYED_ROOT": str(temp_root),
            }

            result = run_wrapper(
                repo_root,
                evidence_root,
                lock_path,
                env=env,
                playbook="site.yml",
                extra_args=["--validate-after-site"],
            )

            self.assertNotEqual(0, result.returncode)
            run_dir = next((evidence_root / "ai-p620-01").iterdir())
            manifest = load_json(run_dir / "manifest.json")
            self.assertEqual("incomplete", manifest["finalization"]["state"])
            self.assertIn("validation", manifest["finalization"]["reason"].lower())
            self.assertTrue((run_dir / "SHA256SUMS").exists())

    def test_wrapper_exit_zero_with_malformed_validation_returns_distinct_failure_and_keeps_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            repo_root = create_repo(temp_root / "repo")
            evidence_root = temp_root / "evidence-root"
            evidence_root.mkdir()
            lock_path = temp_root / "ansible.lock"
            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            tool_log = temp_root / "tool.log"
            build_fake_tools(bin_dir, tool_log)

            env = {
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "FAKE_ANSIBLE_STDOUT": textwrap.dedent(
                    """\
                    PLAY RECAP *********************************************************************
                    ai-p620-01 : ok=3 changed=1 unreachable=0 failed=0 skipped=0 rescued=0 ignored=0
                    """
                ),
                "FAKE_VALIDATE_STDOUT": textwrap.dedent(
                    """\
                    PLAY RECAP *********************************************************************
                    ai-p620-01 : ok=1 changed=0 unreachable=0 failed=0 skipped=0 rescued=0 ignored=0
                    """
                ),
                "FAKE_WRITE_VALIDATION": "1",
                "FAKE_INVALID_VALIDATION": "1",
                "FAKE_SECRET_SENTINEL": SECRET_SENTINEL,
                "LOCAL_AI_DEPLOYED_ROOT": str(temp_root),
            }

            result = run_wrapper(
                repo_root,
                evidence_root,
                lock_path,
                env=env,
                playbook="site.yml",
                extra_args=["--validate-after-site"],
            )

            self.assertEqual(66, result.returncode)
            run_dir = next((evidence_root / "ai-p620-01").iterdir())
            manifest = load_json(run_dir / "manifest.json")
            self.assertEqual("incomplete", manifest["finalization"]["state"])
            self.assertTrue((run_dir / "ansible.log").exists())
            self.assertTrue((run_dir / "SHA256SUMS").exists())
            self.assertNotIn(SECRET_SENTINEL, manifest["finalization"]["reason"])
            self.assertNotIn("Traceback", result.stderr)

    def test_wrapper_returns_validation_exit_when_site_succeeds_and_post_validation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            repo_root = create_repo(temp_root / "repo")
            evidence_root = temp_root / "evidence-root"
            evidence_root.mkdir()
            lock_root = temp_root / "locks"
            lock_root.mkdir()
            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            tool_log = temp_root / "tool.log"
            build_fake_tools(bin_dir, tool_log)

            env = {
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "FAKE_ANSIBLE_STDOUT": textwrap.dedent(
                    """\
                    PLAY RECAP *********************************************************************
                    ai-p620-01 : ok=3 changed=1 unreachable=0 failed=0 skipped=0 rescued=0 ignored=0
                    """
                ),
                "FAKE_VALIDATE_STDOUT": textwrap.dedent(
                    """\
                    PLAY RECAP *********************************************************************
                    ai-p620-01 : ok=1 changed=0 unreachable=0 failed=1 skipped=0 rescued=0 ignored=0
                    """
                ),
                "FAKE_WRITE_VALIDATION": "1",
                "FAKE_VALIDATE_EXIT": "23",
                "LOCAL_AI_DEPLOYED_ROOT": str(temp_root),
            }

            result = run_wrapper(
                repo_root,
                evidence_root,
                lock_root,
                env=env,
                playbook="site.yml",
                extra_args=["--validate-after-site"],
            )

            self.assertEqual(23, result.returncode)
            run_dir = next((evidence_root / "ai-p620-01").iterdir())
            manifest = load_json(run_dir / "manifest.json")
            ansible_run = load_json(run_dir / "ansible-run.json")
            self.assertEqual("incomplete", manifest["finalization"]["state"])
            self.assertEqual(23, manifest["run"]["ansible"]["exit_code"])
            self.assertEqual(23, ansible_run["exit_code"])
            self.assertTrue((run_dir / "SHA256SUMS").exists())

    def test_wrapper_rejects_missing_recap_without_zero_filling_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            repo_root = create_repo(temp_root / "repo")
            evidence_root = temp_root / "evidence-root"
            evidence_root.mkdir()
            lock_path = temp_root / "ansible.lock"
            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            tool_log = temp_root / "tool.log"
            build_fake_tools(bin_dir, tool_log)

            env = {
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "FAKE_ANSIBLE_STDOUT": "No recap available\n",
                "LOCAL_AI_DEPLOYED_ROOT": str(temp_root),
            }

            result = run_wrapper(repo_root, evidence_root, lock_path, env=env, playbook="validate.yml")

            self.assertNotEqual(0, result.returncode)
            run_dir = next((evidence_root / "ai-p620-01").iterdir())
            manifest = load_json(run_dir / "manifest.json")
            self.assertEqual("incomplete", manifest["finalization"]["state"])
            self.assertEqual("incomplete", manifest["status"])
            self.assertIsNone(manifest["run"]["ansible"]["recap"])
            self.assertIn("recap", manifest["finalization"]["reason"].lower())
            self.assertTrue((run_dir / "SHA256SUMS").exists())

    def test_wrapper_rejects_tracked_dirty_tree_before_ansible_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            repo_root = create_repo(temp_root / "repo")
            evidence_root = temp_root / "evidence-root"
            evidence_root.mkdir()
            lock_path = temp_root / "ansible.lock"
            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            tool_log = temp_root / "tool.log"
            build_fake_tools(bin_dir, tool_log)

            env = {
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "FAKE_GIT_STATUS": " M tracked.yml\n",
                "LOCAL_AI_DEPLOYED_ROOT": str(temp_root),
            }

            result = run_wrapper(repo_root, evidence_root, lock_path, env=env, playbook="validate.yml")

            self.assertNotEqual(0, result.returncode)
            self.assertFalse((evidence_root / "ai-p620-01").exists())
            self.assertNotIn("ansible-playbook", tool_log.read_text(encoding="utf-8"))

    def test_wrapper_rejects_untracked_dirty_tree_before_ansible_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            repo_root = create_repo(temp_root / "repo")
            evidence_root = temp_root / "evidence-root"
            evidence_root.mkdir()
            lock_path = temp_root / "ansible.lock"
            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            tool_log = temp_root / "tool.log"
            build_fake_tools(bin_dir, tool_log)

            env = {
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "FAKE_GIT_STATUS": "?? scratch.txt\n",
                "LOCAL_AI_DEPLOYED_ROOT": str(temp_root),
            }

            result = run_wrapper(repo_root, evidence_root, lock_path, env=env, playbook="validate.yml")

            self.assertNotEqual(0, result.returncode)
            self.assertFalse((evidence_root / "ai-p620-01").exists())
            self.assertNotIn("ansible-playbook", tool_log.read_text(encoding="utf-8"))

    def test_wrapper_accepts_exact_playbook_allowlist_and_rejects_others(self) -> None:
        allowed = ["site.yml", "drift-check.yml", "patch.yml", "validate.yml", "benchmark.yml", "facts-export.yml"]
        for playbook in allowed:
            with self.subTest(playbook=playbook):
                with tempfile.TemporaryDirectory() as tmpdir:
                    temp_root = Path(tmpdir)
                    repo_root = create_repo(temp_root / "repo")
                    evidence_root = temp_root / "evidence-root"
                    evidence_root.mkdir()
                    lock_path = temp_root / "ansible.lock"
                    bin_dir = temp_root / "bin"
                    bin_dir.mkdir()
                    tool_log = temp_root / "tool.log"
                    build_fake_tools(bin_dir, tool_log)

                    env = {
                        "PATH": f"{bin_dir}:{os.environ['PATH']}",
                        "FAKE_ANSIBLE_STDOUT": textwrap.dedent(
                            """\
                            PLAY RECAP *********************************************************************
                            ai-p620-01 : ok=1 changed=0 unreachable=0 failed=0 skipped=0 rescued=0 ignored=0
                            """
                        ),
                        "LOCAL_AI_DEPLOYED_ROOT": str(temp_root),
                    }
                    if playbook == "validate.yml":
                        env["FAKE_WRITE_VALIDATION"] = "1"

                    result = run_wrapper(repo_root, evidence_root, lock_path, env=env, playbook=playbook)
                    self.assertEqual(0, result.returncode, result.stderr)

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            repo_root = create_repo(temp_root / "repo")
            evidence_root = temp_root / "evidence-root"
            evidence_root.mkdir()
            lock_path = temp_root / "ansible.lock"
            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            tool_log = temp_root / "tool.log"
            build_fake_tools(bin_dir, tool_log)
            env = {
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "LOCAL_AI_DEPLOYED_ROOT": str(temp_root),
            }

            disallowed = run_wrapper(repo_root, evidence_root, lock_path, env=env, playbook="bootstrap.yml")
            self.assertNotEqual(0, disallowed.returncode)
            self.assertIn("allowlist", disallowed.stderr.lower())

    def test_wrapper_rejects_target_traversal_and_unsafe_target_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            repo_root = create_repo(temp_root / "repo")
            evidence_root = temp_root / "evidence-root"
            evidence_root.mkdir()
            lock_path = temp_root / "ansible.lock"
            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            tool_log = temp_root / "tool.log"
            build_fake_tools(bin_dir, tool_log)
            env = {
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "LOCAL_AI_DEPLOYED_ROOT": str(temp_root),
            }

            for target in ("../escape", "..", "/", "a/b", "."):
                with self.subTest(target=target):
                    result = run_wrapper(repo_root, evidence_root, lock_path, env=env, playbook="validate.yml", target=target)
                    self.assertNotEqual(0, result.returncode)
            self.assertEqual([], list(evidence_root.iterdir()))

    def test_wrapper_rejects_inventory_traversal_and_symlink_outside_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            repo_root = create_repo(temp_root / "repo")
            evidence_root = temp_root / "evidence-root"
            evidence_root.mkdir()
            lock_path = temp_root / "ansible.lock"
            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            tool_log = temp_root / "tool.log"
            build_fake_tools(bin_dir, tool_log)
            env = {
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "LOCAL_AI_DEPLOYED_ROOT": str(temp_root),
            }

            traversal = run_wrapper(repo_root, evidence_root, lock_path, env=env, playbook="validate.yml", inventory="../hosts.yml")
            self.assertNotEqual(0, traversal.returncode)

            outside_inventory = temp_root / "outside-hosts.yml"
            outside_inventory.write_text("all:\n  hosts:\n    outside:\n", encoding="utf-8")
            (repo_root / "inventory" / "production" / "linked.yml").symlink_to(outside_inventory)
            symlinked = run_wrapper(
                repo_root,
                evidence_root,
                lock_path,
                env=env,
                playbook="validate.yml",
                inventory="inventory/production/linked.yml",
            )
            self.assertNotEqual(0, symlinked.returncode)

    def test_wrapper_rejects_playbook_symlink_outside_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            repo_root = create_repo(temp_root / "repo")
            evidence_root = temp_root / "evidence-root"
            evidence_root.mkdir()
            lock_path = temp_root / "ansible.lock"
            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            tool_log = temp_root / "tool.log"
            build_fake_tools(bin_dir, tool_log)
            env = {
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "LOCAL_AI_DEPLOYED_ROOT": str(temp_root),
            }

            outside_playbook = temp_root / "outside.yml"
            outside_playbook.write_text("---\n[]\n", encoding="utf-8")
            (repo_root / "playbooks" / "site.yml").unlink()
            (repo_root / "playbooks" / "site.yml").symlink_to(outside_playbook)

            result = run_wrapper(repo_root, evidence_root, lock_path, env=env, playbook="site.yml")
            self.assertNotEqual(0, result.returncode)

    def test_wrapper_rejects_symlinked_ansible_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            repo_root = create_repo(temp_root / "repo")
            outside_config = temp_root / "outside-ansible.cfg"
            outside_config.write_text("[defaults]\nstdout_callback = yaml\n", encoding="utf-8")
            (repo_root / "ansible.cfg").unlink()
            (repo_root / "ansible.cfg").symlink_to(outside_config)
            evidence_root = temp_root / "evidence-root"
            evidence_root.mkdir()
            lock_root = temp_root / "locks"
            lock_root.mkdir()
            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            tool_log = temp_root / "tool.log"
            build_fake_tools(bin_dir, tool_log)
            env = {
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "LOCAL_AI_DEPLOYED_ROOT": str(temp_root),
            }

            result = run_wrapper(repo_root, evidence_root, lock_root, env=env, playbook="validate.yml")

            self.assertNotEqual(0, result.returncode)
            self.assertFalse((evidence_root / "ai-p620-01").exists())

    def test_wrapper_rejects_symlinked_schema_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            repo_root = create_repo(temp_root / "repo")
            evidence_root = temp_root / "evidence-root"
            evidence_root.mkdir()
            lock_root = temp_root / "locks"
            lock_root.mkdir()
            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            tool_log = temp_root / "tool.log"
            build_fake_tools(bin_dir, tool_log)
            real_schemas = temp_root / "outside-schemas"
            real_schemas.mkdir()
            for schema_file in (REPO_ROOT / "schemas").glob("*.json"):
                (real_schemas / schema_file.name).write_text(schema_file.read_text(encoding="utf-8"), encoding="utf-8")
            schema_link = temp_root / "schemas-link"
            schema_link.symlink_to(real_schemas)
            env = {
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "LOCAL_AI_DEPLOYED_ROOT": str(temp_root),
            }

            result = run_wrapper(
                repo_root,
                evidence_root,
                lock_root,
                env=env,
                schema_root=schema_link,
                playbook="validate.yml",
            )

            self.assertNotEqual(0, result.returncode)
            self.assertFalse((evidence_root / "ai-p620-01").exists())

    def test_wrapper_lock_symlink_cannot_truncate_victim(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            repo_root = create_repo(temp_root / "repo")
            evidence_root = temp_root / "evidence-root"
            evidence_root.mkdir()
            lock_root = temp_root / "locks"
            lock_root.mkdir()
            victim = temp_root / "victim.txt"
            victim.write_text("do not truncate\n", encoding="utf-8")
            (lock_root / "ansible-snapshot.lock").symlink_to(victim)
            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            tool_log = temp_root / "tool.log"
            build_fake_tools(bin_dir, tool_log)
            env = {
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "LOCAL_AI_DEPLOYED_ROOT": str(temp_root),
            }

            result = run_wrapper(repo_root, evidence_root, lock_root, env=env, playbook="validate.yml")

            self.assertNotEqual(0, result.returncode)
            self.assertEqual("do not truncate\n", victim.read_text(encoding="utf-8"))
            self.assertFalse((evidence_root / "ai-p620-01").exists())

    def test_wrapper_forces_restrictive_permissions_even_under_hostile_umask(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            repo_root = create_repo(temp_root / "repo")
            evidence_root = temp_root / "evidence-root"
            evidence_root.mkdir()
            lock_root = temp_root / "locks"
            lock_root.mkdir()
            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            tool_log = temp_root / "tool.log"
            build_fake_tools(bin_dir, tool_log)

            env = {
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "FAKE_ANSIBLE_STDOUT": textwrap.dedent(
                    """\
                    PLAY RECAP *********************************************************************
                    ai-p620-01 : ok=1 changed=0 unreachable=0 failed=0 skipped=0 rescued=0 ignored=0
                    """
                ),
                "FAKE_WRITE_VALIDATION": "1",
                "LOCAL_AI_DEPLOYED_ROOT": str(temp_root),
            }

            result = run_wrapper(
                repo_root,
                evidence_root,
                lock_root,
                env=env,
                playbook="validate.yml",
                umask_value=0,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            run_dir = next((evidence_root / "ai-p620-01").iterdir())
            paths = [
                evidence_root / "ai-p620-01",
                run_dir,
                run_dir / "manifest.json",
                run_dir / "ansible-run.json",
                run_dir / "ansible.log",
                run_dir / "validation.json",
                run_dir / "SHA256SUMS",
                lock_root / "ansible-snapshot.lock",
            ]
            for path in paths:
                mode = path.stat().st_mode
                self.assertEqual(0, mode & stat.S_IWGRP, f"group-write bit set on {path}")
                self.assertEqual(0, mode & stat.S_IRWXO, f"world bits set on {path}")

    def test_wrapper_does_not_import_malicious_caller_cwd_scripts_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            repo_root = create_repo(temp_root / "repo")
            evidence_root = temp_root / "evidence-root"
            evidence_root.mkdir()
            lock_path = temp_root / "ansible.lock"
            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            tool_log = temp_root / "tool.log"
            build_fake_tools(bin_dir, tool_log)
            hostile_cwd = temp_root / "hostile-cwd"
            (hostile_cwd / "scripts").mkdir(parents=True)
            sentinel_path = hostile_cwd / "shadowed.txt"
            (hostile_cwd / "scripts" / "__init__.py").write_text("", encoding="utf-8")
            (hostile_cwd / "scripts" / "finalize_evidence.py").write_text(
                textwrap.dedent(
                    f"""\
                    from pathlib import Path
                    Path({str(sentinel_path)!r}).write_text("shadowed\\n", encoding="utf-8")
                    raise SystemExit("malicious import should never run")
                    """
                ),
                encoding="utf-8",
            )

            env = {
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "FAKE_ANSIBLE_STDOUT": textwrap.dedent(
                    """\
                    PLAY RECAP *********************************************************************
                    ai-p620-01 : ok=1 changed=0 unreachable=0 failed=0 skipped=0 rescued=0 ignored=0
                    """
                ),
                "FAKE_WRITE_VALIDATION": "1",
                "LOCAL_AI_DEPLOYED_ROOT": str(temp_root),
            }

            result = run_wrapper(
                repo_root,
                evidence_root,
                lock_path,
                cwd=hostile_cwd,
                env=env,
                playbook="validate.yml",
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse(sentinel_path.exists())
            run_dir = next((evidence_root / "ai-p620-01").iterdir())
            self.assertTrue((run_dir / "manifest.json").exists())
            self.assertTrue((run_dir / "SHA256SUMS").exists())

    def test_wrapper_rejects_missing_repo_ansible_config_before_creating_run_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            repo_root = create_repo(temp_root / "repo")
            (repo_root / "ansible.cfg").unlink()
            evidence_root = temp_root / "evidence-root"
            evidence_root.mkdir()
            lock_path = temp_root / "ansible.lock"
            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            tool_log = temp_root / "tool.log"
            build_fake_tools(bin_dir, tool_log)
            hostile_cwd = temp_root / "hostile-cwd"
            (hostile_cwd / "scripts").mkdir(parents=True)
            sentinel_path = hostile_cwd / "shadowed.txt"
            (hostile_cwd / "scripts" / "__init__.py").write_text("", encoding="utf-8")
            (hostile_cwd / "scripts" / "finalize_evidence.py").write_text(
                textwrap.dedent(
                    f"""\
                    from pathlib import Path
                    Path({str(sentinel_path)!r}).write_text("shadowed\\n", encoding="utf-8")
                    raise SystemExit("malicious import should never run")
                    """
                ),
                encoding="utf-8",
            )

            env = {
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "LOCAL_AI_DEPLOYED_ROOT": str(temp_root),
            }

            result = run_wrapper(
                repo_root,
                evidence_root,
                lock_path,
                cwd=hostile_cwd,
                env=env,
                playbook="validate.yml",
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("ansible.cfg", result.stderr)
            self.assertEqual([], list(evidence_root.iterdir()))
            self.assertFalse(sentinel_path.exists())

    def test_wrapper_source_contains_no_git_mutation_or_network_commands(self) -> None:
        wrapper_text = WRAPPER_PATH.read_text(encoding="utf-8")
        self.assertNotIn("git fetch", wrapper_text)
        self.assertNotIn("git pull", wrapper_text)
        self.assertNotIn("git checkout", wrapper_text)
        self.assertNotIn("git reset", wrapper_text)

    def test_wrapper_uses_nonblocking_flock_and_reports_lock_contention_without_run_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            repo_root = create_repo(temp_root / "repo")
            evidence_root = temp_root / "evidence-root"
            evidence_root.mkdir()
            lock_path = temp_root / "ansible.lock"
            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            tool_log = temp_root / "tool.log"
            build_fake_tools(bin_dir, tool_log)

            env = {
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "LOCAL_AI_DEPLOYED_ROOT": str(temp_root),
            }

            with lock_path.open("w", encoding="utf-8") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = run_wrapper(repo_root, evidence_root, lock_path, env=env, playbook="validate.yml")

            self.assertEqual(73, result.returncode)
            self.assertFalse((evidence_root / "ai-p620-01").exists())

    def test_wrapper_holds_lock_through_finalization_checksums_and_mode_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            repo_root = create_repo(temp_root / "repo")
            evidence_root = temp_root / "evidence-root"
            evidence_root.mkdir()
            lock_root = temp_root / "locks"
            lock_root.mkdir()
            bin_dir = temp_root / "bin"
            bin_dir.mkdir()
            tool_log = temp_root / "tool.log"
            build_fake_tools(bin_dir, tool_log)

            env = {
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "FAKE_ANSIBLE_STDOUT": textwrap.dedent(
                    """\
                    PLAY RECAP *********************************************************************
                    ai-p620-01 : ok=1 changed=0 unreachable=0 failed=0 skipped=0 rescued=0 ignored=0
                    """
                ),
                "FAKE_WRITE_VALIDATION": "1",
                "FAKE_EXTRA_ARTIFACT_MB": "256",
                "LOCAL_AI_DEPLOYED_ROOT": str(temp_root),
            }

            first = start_wrapper(
                repo_root,
                evidence_root,
                lock_root,
                env=env,
                playbook="validate.yml",
            )
            try:
                deadline = time.time() + 10
                run_dir: Path | None = None
                while True:
                    if first.poll() is not None:
                        stdout, stderr = first.communicate(timeout=1)
                        self.fail(f"first wrapper exited before finalizer observation\nstdout={stdout}\nstderr={stderr}")
                    if time.time() >= deadline:
                        first.kill()
                        stdout, stderr = first.communicate(timeout=1)
                        self.fail(f"timed out waiting for finalizer observation\nstdout={stdout}\nstderr={stderr}")
                    host_runs = list((evidence_root / "ai-p620-01").iterdir()) if (evidence_root / "ai-p620-01").exists() else []
                    if len(host_runs) == 1:
                        run_dir = host_runs[0]
                    tool_log_text = tool_log.read_text(encoding="utf-8") if tool_log.exists() else ""
                    ansible_child_pid = find_descendant_pid_with_needle(first.pid, "ansible-playbook")
                    if (
                        run_dir is not None
                        and "ansible-playbook" in tool_log_text
                        and ansible_child_pid is None
                        and not (run_dir / "SHA256SUMS").exists()
                    ):
                        break
                    time.sleep(0.01)

                assert run_dir is not None
                self.assertTrue((run_dir / "manifest.json").exists())
                self.assertFalse((run_dir / "SHA256SUMS").exists())

                second = run_wrapper(repo_root, evidence_root, lock_root, env=env, playbook="validate.yml")
                self.assertEqual(73, second.returncode, second.stderr)
                self.assertEqual([run_dir], list((evidence_root / "ai-p620-01").iterdir()))
            finally:
                stdout, stderr = first.communicate(timeout=10)
                self.assertEqual(0, first.returncode, f"stdout={stdout}\nstderr={stderr}")
                if (evidence_root / "ai-p620-01").exists():
                    run_dir = next((evidence_root / "ai-p620-01").iterdir())
                    self.assertTrue((run_dir / "SHA256SUMS").exists())
                    self.assertEqual(0, (run_dir / "SHA256SUMS").stat().st_mode & stat.S_IWGRP)
                    self.assertEqual(0, (run_dir / "SHA256SUMS").stat().st_mode & stat.S_IRWXO)
                    self.assertEqual(0, (run_dir / "manifest.json").stat().st_mode & stat.S_IWGRP)
                    self.assertEqual(0, (run_dir / "manifest.json").stat().st_mode & stat.S_IRWXO)


if __name__ == "__main__":
    unittest.main()
