from __future__ import annotations

import fcntl
import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
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
                payload["git_sha"] = os.environ.get("FAKE_GIT_SHA", "0123456789abcdef0123456789abcdef01234567")
                if os.environ.get("FAKE_INVALID_VALIDATION") == "1":
                    payload["summary"]["classification"] = os.environ.get("FAKE_SECRET_SENTINEL", "invalid")
                (run_dir / "validation.json").write_text(json.dumps(payload, indent=2) + "\\n", encoding="utf-8")
            command_log = os.environ.get("FAKE_COMMAND_LOG")
            if command_log:
                with Path(command_log).open("a", encoding="utf-8") as handle:
                    handle.write("argv:" + " ".join(argv) + "\\n")
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
    for playbook in ("site.yml", "drift-check.yml", "patch.yml", "validate.yml", "benchmark.yml", "facts-export.yml", "bootstrap.yml"):
        (root / "playbooks" / playbook).write_text("---\n[]\n", encoding="utf-8")
    (root / "inventory" / "production" / "hosts.yml").write_text("all:\n  hosts:\n    ai-p620-01:\n", encoding="utf-8")
    return root


def run_wrapper(
    repo_root: Path,
    evidence_root: Path,
    lock_path: Path,
    *,
    env: dict[str, str] | None = None,
    playbook: str = "site.yml",
    inventory: str = "inventory/production/hosts.yml",
    target: str = "ai-p620-01",
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        str(WRAPPER_PATH),
        "--repo-root",
        str(repo_root),
        "--schema-root",
        str(REPO_ROOT / "schemas"),
        "--inventory",
        inventory,
        "--target",
        target,
        "--playbook",
        playbook,
        "--evidence-root",
        str(evidence_root),
        "--lock-path",
        str(lock_path),
    ]
    if extra_args:
        command.extend(extra_args)
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=merged_env,
    )


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
            }

            result = run_wrapper(
                repo_root,
                evidence_root,
                lock_path,
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


if __name__ == "__main__":
    unittest.main()
