from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_ROOT_FILES = (
    ".ansible-lint",
    ".yamllint",
    "Makefile",
    "ansible.cfg",
    "requirements.txt",
    "requirements.yml",
)

REQUIRED_PLAYBOOKS = (
    "baseline.yml",
    "benchmark.yml",
    "bootstrap.yml",
    "drift-check.yml",
    "facts-export.yml",
    "patch.yml",
    "site.yml",
    "upgrade.yml",
    "validate.yml",
)

REQUIRED_ROLE_NAMES = (
    "base_os",
    "security",
    "users",
    "ssh",
    "time_sync",
    "storage",
    "networking",
    "hardware_inventory",
    "hardware_validation",
    "intel_gpu",
    "container_runtime",
    "pytorch_xpu",
    "vllm_xpu",
    "llama_cpp_sycl",
    "monitoring",
    "scheduled_ansible",
    "vault_integration",
    "validation",
    "benchmarking",
    "cmdb_export",
    "itsm_hooks",
)

ROLE_SUBFILES = (
    "defaults/main.yml",
    "tasks/main.yml",
    "handlers/main.yml",
    "meta/main.yml",
)

WORKFLOW_PATH = Path(".github/workflows/quality.yml")
FIXTURE_PATH = Path("tests/fixtures/inventory/healthy.yml")
EVIDENCE_DIR = Path("evidence")
EVIDENCE_KEEP = EVIDENCE_DIR / ".gitkeep"


class RepositoryContractTests(unittest.TestCase):
    def test_required_repository_files_exist(self) -> None:
        required_paths = [Path(name) for name in REQUIRED_ROOT_FILES]
        required_paths.extend(Path(name) for name in REQUIRED_PLAYBOOKS)
        required_paths.extend(
            Path("roles") / role_name / subfile
            for role_name in REQUIRED_ROLE_NAMES
            for subfile in ROLE_SUBFILES
        )
        required_paths.extend((WORKFLOW_PATH, FIXTURE_PATH, EVIDENCE_KEEP))

        missing = sorted(
            str(path) for path in required_paths if not (REPO_ROOT / path).exists()
        )

        self.assertEqual([], missing, f"Missing required repository paths: {missing}")

    def test_evidence_artifacts_are_ignored_except_gitkeep(self) -> None:
        gitignore_path = REPO_ROOT / ".gitignore"
        self.assertTrue(gitignore_path.exists(), "Expected .gitignore to exist")

        gitignore_lines = {
            line.strip()
            for line in gitignore_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        }

        self.assertIn("evidence/*", gitignore_lines)
        self.assertIn("!evidence/.gitkeep", gitignore_lines)


if __name__ == "__main__":
    unittest.main()
