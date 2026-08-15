from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "schemas"
VALIDATION_FIXTURE = FIXTURE_DIR / "validation.valid.json"
ITSM_FIXTURE = FIXTURE_DIR / "itsm.valid.json"


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


class ContractSemanticValidationTests(unittest.TestCase):
    def test_validation_fixture_passes_semantic_validator(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "scripts.validate_contract", "validation", str(VALIDATION_FIXTURE)],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_validation_semantics_reject_pass_with_failed_check(self) -> None:
        payload = load_json(VALIDATION_FIXTURE)
        payload["checks"][0]["status"] = "FAIL"
        payload["summary"]["blocking_failures"] = 0
        temp_path = REPO_ROOT / "evidence" / "validation.invalid-semantic.json"
        temp_path.write_text(json.dumps(payload), encoding="utf-8")
        self.addCleanup(temp_path.unlink)

        result = subprocess.run(
            [sys.executable, "-m", "scripts.validate_contract", "validation", str(temp_path)],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("top-level status", result.stderr)

    def test_validation_semantics_reject_wrong_summary_counts(self) -> None:
        payload = load_json(VALIDATION_FIXTURE)
        second_check = copy.deepcopy(payload["checks"][0])
        second_check["id"] = "gpu_model_match"
        second_check["status"] = "BLOCKED"
        payload["checks"].append(second_check)
        payload["summary"]["blocking_failures"] = 0
        temp_path = REPO_ROOT / "evidence" / "validation.invalid-counts.json"
        temp_path.write_text(json.dumps(payload), encoding="utf-8")
        self.addCleanup(temp_path.unlink)

        result = subprocess.run(
            [sys.executable, "-m", "scripts.validate_contract", "validation", str(temp_path)],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("summary blocking_failures", result.stderr)

    def test_itsm_fixture_passes_semantic_validator(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "scripts.validate_contract", "itsm", str(ITSM_FIXTURE)],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_itsm_semantics_require_selected_action_in_permitted_actions(self) -> None:
        payload = load_json(ITSM_FIXTURE)
        payload["selected_action"] = "UPGRADE"
        temp_path = REPO_ROOT / "evidence" / "itsm.invalid-action.json"
        temp_path.write_text(json.dumps(payload), encoding="utf-8")
        self.addCleanup(temp_path.unlink)

        result = subprocess.run(
            [sys.executable, "-m", "scripts.validate_contract", "itsm", str(temp_path)],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("selected_action", result.stderr)

    def test_itsm_semantics_reject_implemented_without_approval_and_passed_results(self) -> None:
        payload = load_json(ITSM_FIXTURE)
        payload["status"] = "IMPLEMENTED"
        payload["approval_state"] = "PENDING"
        payload["selected_action"] = "PATCH"
        payload["executed_action"] = "PATCH"
        payload["execution_result"]["observed"]["status"] = "PASS"
        payload["validation_result"]["observed"]["status"] = "PASS"
        temp_path = REPO_ROOT / "evidence" / "itsm.invalid-implemented.json"
        temp_path.write_text(json.dumps(payload), encoding="utf-8")
        self.addCleanup(temp_path.unlink)

        result = subprocess.run(
            [sys.executable, "-m", "scripts.validate_contract", "itsm", str(temp_path)],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("IMPLEMENTED", result.stderr)


if __name__ == "__main__":
    unittest.main()
