from __future__ import annotations

import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = REPO_ROOT / "tests" / "fixtures" / "inventory" / "healthy.yml"


def ansible_playbook_bin() -> str | None:
    candidate = REPO_ROOT / ".venv" / "bin" / "ansible-playbook"
    if candidate.exists():
        return str(candidate)
    return shutil.which("ansible-playbook")


def run_role_playbook(playbook_path: Path) -> subprocess.CompletedProcess[str]:
    binary = ansible_playbook_bin()
    if binary is None:
        raise unittest.SkipTest("ansible-playbook is not available")
    return subprocess.run(
        [
            binary,
            "-i",
            str(INVENTORY_PATH),
            str(playbook_path),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={"ANSIBLE_CONFIG": str(REPO_ROOT / "ansible.cfg")},
    )


class EvidenceRoleTests(unittest.TestCase):
    def write_playbook(self, directory: Path, vars_block: str) -> Path:
        playbook = directory / "playbook.yml"
        playbook.write_text(
            textwrap.dedent(
                f"""\
                ---
                - hosts: localhost
                  gather_facts: false
                  roles:
                    - role: evidence
                      vars:
                {textwrap.indent(vars_block, '        ')}
                """
            ),
            encoding="utf-8",
        )
        return playbook

    def test_role_rejects_target_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            playbook = self.write_playbook(
                temp_root,
                textwrap.dedent(
                    f"""\
                    evidence_root: {temp_root / 'evidence'}
                    evidence_target_name: ../escape
                    """
                ),
            )

            result = run_role_playbook(playbook)

            self.assertNotEqual(0, result.returncode)

    def test_role_rejects_symlinked_evidence_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            real_root = temp_root / "real-root"
            real_root.mkdir()
            link_root = temp_root / "evidence-link"
            link_root.symlink_to(real_root)
            playbook = self.write_playbook(
                temp_root,
                textwrap.dedent(
                    f"""\
                    evidence_root: {link_root}
                    evidence_target_name: ai-p620-01
                    """
                ),
            )

            result = run_role_playbook(playbook)

            self.assertNotEqual(0, result.returncode)

    def test_role_rejects_symlinked_target_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_root = Path(tmpdir)
            evidence_root = temp_root / "evidence"
            evidence_root.mkdir()
            outside_dir = temp_root / "outside"
            outside_dir.mkdir()
            (evidence_root / "ai-p620-01").symlink_to(outside_dir)
            playbook = self.write_playbook(
                temp_root,
                textwrap.dedent(
                    f"""\
                    evidence_root: {evidence_root}
                    evidence_target_name: ai-p620-01
                    """
                ),
            )

            result = run_role_playbook(playbook)

            self.assertNotEqual(0, result.returncode)


if __name__ == "__main__":
    unittest.main()
