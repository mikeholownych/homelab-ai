from __future__ import annotations

import configparser
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_ROOT_FILES = (
    ".ansible-lint",
    ".yamllint",
    "Makefile",
    "ansible.cfg",
    "requirements.in",
    "requirements.txt",
    "requirements.yml",
)

REQUIRED_PLAYBOOKS = (
    "playbooks/baseline.yml",
    "playbooks/benchmark.yml",
    "playbooks/bootstrap.yml",
    "playbooks/drift-check.yml",
    "playbooks/facts-export.yml",
    "playbooks/patch.yml",
    "playbooks/site.yml",
    "playbooks/upgrade.yml",
    "playbooks/validate.yml",
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
    "evidence",
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
FINALIZE_EVIDENCE_SCRIPT = Path("scripts/finalize-evidence.py")
FINALIZE_EVIDENCE_MODULE = Path("scripts/finalize_evidence.py")
RUN_WRAPPER_SCRIPT = Path("scripts/run-ansible-snapshot")
MANIFEST_SCHEMA_PATH = Path("schemas/manifest.schema.json")


class RepositoryContractTests(unittest.TestCase):
    def test_required_repository_files_exist(self) -> None:
        required_paths = [Path(name) for name in REQUIRED_ROOT_FILES]
        required_paths.extend(Path(name) for name in REQUIRED_PLAYBOOKS)
        required_paths.extend(
            Path("roles") / role_name / subfile
            for role_name in REQUIRED_ROLE_NAMES
            for subfile in ROLE_SUBFILES
        )
        required_paths.extend(
            (
                WORKFLOW_PATH,
                FIXTURE_PATH,
                EVIDENCE_KEEP,
                FINALIZE_EVIDENCE_SCRIPT,
                FINALIZE_EVIDENCE_MODULE,
                RUN_WRAPPER_SCRIPT,
                MANIFEST_SCHEMA_PATH,
            )
        )

        missing = sorted(
            str(path) for path in required_paths if not (REPO_ROOT / path).exists()
        )

        self.assertEqual([], missing, f"Missing required repository paths: {missing}")

    def test_playbooks_live_under_playbooks_directory(self) -> None:
        misplaced = sorted(
            path.name for path in REPO_ROOT.glob("*.yml") if path.name in {p.split("/")[-1] for p in REQUIRED_PLAYBOOKS}
        )

        self.assertEqual(
            [],
            misplaced,
            f"Playbooks must live under playbooks/: {misplaced}",
        )

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

    def test_privilege_escalation_defaults_are_active_via_dedicated_section(self) -> None:
        parser = configparser.ConfigParser()
        parser.read(REPO_ROOT / "ansible.cfg", encoding="utf-8")

        self.assertIn("privilege_escalation", parser.sections())
        self.assertEqual("true", parser["privilege_escalation"].get("become"))
        self.assertEqual("sudo", parser["privilege_escalation"].get("become_method"))
        self.assertEqual("root", parser["privilege_escalation"].get("become_user"))
        self.assertNotIn("become", parser["defaults"])
        self.assertNotIn("become_method", parser["defaults"])
        self.assertNotIn("become_user", parser["defaults"])

    def test_python_lockfile_and_install_commands_use_hash_enforcement(self) -> None:
        requirements_in = (REPO_ROOT / "requirements.in").read_text(encoding="utf-8")
        requirements_txt = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
        makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        workflow = (REPO_ROOT / WORKFLOW_PATH).read_text(encoding="utf-8")

        self.assertIn("ansible-core==2.21.3", requirements_in)
        self.assertIn("--hash=sha256:", requirements_txt)
        self.assertIn("install --require-hashes -r requirements.txt", makefile)
        self.assertIn("install --require-hashes -r requirements.txt", workflow)

    def test_ci_workflow_uses_read_only_permissions_and_non_persistent_checkout(self) -> None:
        workflow_data = yaml.safe_load((REPO_ROOT / WORKFLOW_PATH).read_text(encoding="utf-8"))

        self.assertEqual({"contents": "read"}, workflow_data.get("permissions"))
        checkout_steps = [
            step
            for step in workflow_data["jobs"]["quality"]["steps"]
            if step.get("uses", "").startswith("actions/checkout@")
        ]
        self.assertEqual(1, len(checkout_steps))
        self.assertEqual(False, checkout_steps[0].get("with", {}).get("persist-credentials"))

    def test_ansible_snapshot_wrapper_is_executable(self) -> None:
        wrapper_path = REPO_ROOT / RUN_WRAPPER_SCRIPT
        self.assertTrue(wrapper_path.exists(), "Expected run-ansible-snapshot to exist")
        self.assertTrue(wrapper_path.stat().st_mode & 0o111, "run-ansible-snapshot must be executable")

    def test_production_scripts_do_not_contain_test_only_evidence_hooks(self) -> None:
        blocked_tokens = (
            "LOCAL_AI_TEST_",
            "hold_lock_for_test_if_requested",
            "hold-ready",
            "hold-release",
        )
        for script_path in (RUN_WRAPPER_SCRIPT, FINALIZE_EVIDENCE_SCRIPT, FINALIZE_EVIDENCE_MODULE):
            with self.subTest(script=str(script_path)):
                script_text = (REPO_ROOT / script_path).read_text(encoding="utf-8")
                for token in blocked_tokens:
                    self.assertNotIn(token, script_text)


if __name__ == "__main__":
    unittest.main()
