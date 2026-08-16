from __future__ import annotations

import grp
import os
import pwd
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CURRENT_USER = pwd.getpwuid(os.getuid()).pw_name
CURRENT_GROUP = grp.getgrgid(os.getgid()).gr_name


def ansible_playbook_bin() -> str | None:
    candidate = REPO_ROOT / ".venv" / "bin" / "ansible-playbook"
    if candidate.exists():
        return str(candidate)
    return shutil.which("ansible-playbook")


def run_role_playbook(playbook_path: Path) -> subprocess.CompletedProcess[str]:
    binary = ansible_playbook_bin()
    if binary is None:
        raise unittest.SkipTest("ansible-playbook is not available")
    env = os.environ.copy()
    env.update(
        {
            "ANSIBLE_CONFIG": str(REPO_ROOT / "ansible.cfg"),
            "ANSIBLE_ROLES_PATH": str(REPO_ROOT / "roles"),
        }
    )
    return subprocess.run(
        [
            binary,
            "-i",
            "localhost,",
            str(playbook_path),
            "-e",
            "ansible_connection=local",
            "-e",
            "ansible_python_interpreter=/usr/bin/python3",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


class EvidenceRoleTests(unittest.TestCase):
    def combined_output(self, result: subprocess.CompletedProcess[str]) -> str:
        return f"{result.stdout}\n{result.stderr}"

    def write_playbook(self, directory: Path, vars_block: str) -> Path:
        playbook = directory / "playbook.yml"
        vars_text = textwrap.indent(textwrap.dedent(vars_block).strip() + "\n", " " * 8)
        playbook.write_text(
            "---\n"
            "- hosts: localhost\n"
            "  gather_facts: false\n"
            "  roles:\n"
            "    - role: evidence\n"
            "      vars:\n"
            f"{vars_text}",
            encoding="utf-8",
        )
        return playbook

    def test_role_creates_evidence_target_idempotently_with_local_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            evidence_root = temp_root / "evidence-root"
            playbook = self.write_playbook(
                temp_root,
                f"""
evidence_root: {evidence_root}
evidence_target_name: ai-p620-01
evidence_owner: {CURRENT_USER}
evidence_group: {CURRENT_GROUP}
                """,
            )

            first = run_role_playbook(playbook)
            second = run_role_playbook(playbook)

            self.assertEqual(0, first.returncode, first.stderr)
            self.assertEqual(0, second.returncode, second.stderr)
            self.assertTrue((evidence_root / "ai-p620-01").is_dir())
            self.assertNotIn("role 'evidence' was not found", first.stderr)
            self.assertRegex(second.stdout, r"changed=0\b")

    def test_role_rejects_target_traversal_with_specific_guard_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            playbook = self.write_playbook(
                temp_root,
                f"""
evidence_root: {temp_root / 'evidence'}
evidence_target_name: ../escape
evidence_owner: {CURRENT_USER}
evidence_group: {CURRENT_GROUP}
                """,
            )

            result = run_role_playbook(playbook)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("evidence_target_name must match the safe node identifier pattern", self.combined_output(result))

    def test_role_rejects_symlinked_evidence_root_with_specific_guard_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            real_root = temp_root / "real-root"
            real_root.mkdir()
            link_root = temp_root / "evidence-link"
            link_root.symlink_to(real_root)
            playbook = self.write_playbook(
                temp_root,
                f"""
evidence_root: {link_root}
evidence_target_name: ai-p620-01
evidence_owner: {CURRENT_USER}
evidence_group: {CURRENT_GROUP}
                """,
            )

            result = run_role_playbook(playbook)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("evidence_root must not be a symlink", self.combined_output(result))

    def test_role_rejects_symlinked_target_directory_with_specific_guard_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            evidence_root = temp_root / "evidence"
            evidence_root.mkdir()
            outside_dir = temp_root / "outside"
            outside_dir.mkdir()
            (evidence_root / "ai-p620-01").symlink_to(outside_dir)
            playbook = self.write_playbook(
                temp_root,
                f"""
evidence_root: {evidence_root}
evidence_target_name: ai-p620-01
evidence_owner: {CURRENT_USER}
evidence_group: {CURRENT_GROUP}
                """,
            )

            result = run_role_playbook(playbook)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("evidence host directory must not be a symlink", self.combined_output(result))


if __name__ == "__main__":
    unittest.main()
