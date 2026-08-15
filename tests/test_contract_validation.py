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
EVIDENCE_FIXTURE = FIXTURE_DIR / "evidence.valid.json"


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def run_contract_validator(contract_type: str, fixture_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "scripts.validate_contract", contract_type, str(fixture_path)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


class ContractSemanticValidationTests(unittest.TestCase):
    def test_validation_fixture_passes_semantic_validator(self) -> None:
        result = run_contract_validator("validation", VALIDATION_FIXTURE)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_validation_semantics_reject_pass_with_failed_check(self) -> None:
        payload = load_json(VALIDATION_FIXTURE)
        payload["checks"][0]["status"] = "FAIL"
        payload["summary"]["blocking_failures"] = 0
        temp_path = REPO_ROOT / "evidence" / "validation.invalid-semantic.json"
        temp_path.write_text(json.dumps(payload), encoding="utf-8")
        self.addCleanup(temp_path.unlink)

        result = run_contract_validator("validation", temp_path)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("schema validation failed", result.stderr)

    def test_validation_semantics_reject_wrong_summary_counts(self) -> None:
        payload = load_json(VALIDATION_FIXTURE)
        second_check = copy.deepcopy(payload["checks"][0])
        second_check["id"] = "gpu_model_match"
        second_check["status"] = "BLOCKED"
        payload["checks"].append(second_check)
        payload["status"] = "BLOCKED"
        payload["summary"]["classification"] = "blocked"
        payload["summary"]["blocking_failures"] = 0
        temp_path = REPO_ROOT / "evidence" / "validation.invalid-counts.json"
        temp_path.write_text(json.dumps(payload), encoding="utf-8")
        self.addCleanup(temp_path.unlink)

        result = run_contract_validator("validation", temp_path)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("summary blocking_failures", result.stderr)

    def test_validation_semantics_require_blocked_top_level_truth_table(self) -> None:
        payload = load_json(VALIDATION_FIXTURE)
        payload["status"] = "FAIL"
        payload["summary"]["classification"] = "degraded"
        payload["checks"][0]["status"] = "BLOCKED"
        payload["summary"]["blocking_failures"] = 1
        payload["summary"]["failed_checks"] = 0
        temp_path = REPO_ROOT / "evidence" / "validation.invalid-blocked-top-level.json"
        temp_path.write_text(json.dumps(payload), encoding="utf-8")
        self.addCleanup(temp_path.unlink)

        result = run_contract_validator("validation", temp_path)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("BLOCKED", result.stderr)

    def test_validation_semantics_require_failed_top_level_truth_table(self) -> None:
        payload = load_json(VALIDATION_FIXTURE)
        payload["status"] = "NOT_TESTED"
        payload["summary"]["classification"] = "incomplete"
        payload["checks"][0]["status"] = "FAIL"
        payload["summary"]["failed_checks"] = 1
        temp_path = REPO_ROOT / "evidence" / "validation.invalid-failed-top-level.json"
        temp_path.write_text(json.dumps(payload), encoding="utf-8")
        self.addCleanup(temp_path.unlink)

        result = run_contract_validator("validation", temp_path)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("FAIL", result.stderr)

    def test_validation_semantics_require_not_tested_top_level_truth_table(self) -> None:
        payload = load_json(VALIDATION_FIXTURE)
        payload["checks"][0]["status"] = "NOT_TESTED"
        payload["summary"]["not_tested"] = 1
        payload["status"] = "PASS"
        payload["summary"]["classification"] = "healthy"
        temp_path = REPO_ROOT / "evidence" / "validation.invalid-not-tested-top-level.json"
        temp_path.write_text(json.dumps(payload), encoding="utf-8")
        self.addCleanup(temp_path.unlink)

        result = run_contract_validator("validation", temp_path)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("NOT_TESTED", result.stderr)

    def test_validator_rejects_schema_invalid_timestamp_before_semantics(self) -> None:
        payload = load_json(VALIDATION_FIXTURE)
        payload["generated_at"] = "2026-99-99T25:61:61Z"
        temp_path = REPO_ROOT / "evidence" / "validation.invalid-timestamp.json"
        temp_path.write_text(json.dumps(payload), encoding="utf-8")
        self.addCleanup(temp_path.unlink)

        result = run_contract_validator("validation", temp_path)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("schema", result.stderr.lower())

    def test_itsm_fixture_passes_semantic_validator(self) -> None:
        result = run_contract_validator("itsm", ITSM_FIXTURE)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_itsm_semantics_require_selected_action_in_permitted_actions(self) -> None:
        payload = load_json(ITSM_FIXTURE)
        payload["selected_action"] = "UPGRADE"
        temp_path = REPO_ROOT / "evidence" / "itsm.invalid-action.json"
        temp_path.write_text(json.dumps(payload), encoding="utf-8")
        self.addCleanup(temp_path.unlink)

        result = run_contract_validator("itsm", temp_path)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("permitted_actions", result.stderr)

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

        result = run_contract_validator("itsm", temp_path)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("APPROVED", result.stderr)

    def test_itsm_semantics_require_matching_selected_and_executed_actions(self) -> None:
        payload = load_json(ITSM_FIXTURE)
        payload["status"] = "IMPLEMENTED"
        payload["approval_state"] = "APPROVED"
        payload["selected_action"] = "PATCH"
        payload["executed_action"] = "UPGRADE"
        payload["permitted_actions"] = ["PATCH", "UPGRADE"]
        payload["execution_result"]["observed"]["status"] = "PASS"
        payload["validation_result"]["observed"]["status"] = "PASS"
        temp_path = REPO_ROOT / "evidence" / "itsm.invalid-mismatched-action.json"
        temp_path.write_text(json.dumps(payload), encoding="utf-8")
        self.addCleanup(temp_path.unlink)

        result = run_contract_validator("itsm", temp_path)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("executed_action", result.stderr)

    def test_itsm_semantics_require_approved_status_to_match_approval_state(self) -> None:
        payload = load_json(ITSM_FIXTURE)
        payload["status"] = "APPROVED"
        payload["approval_state"] = "REJECTED"
        temp_path = REPO_ROOT / "evidence" / "itsm.invalid-approved-state.json"
        temp_path.write_text(json.dumps(payload), encoding="utf-8")
        self.addCleanup(temp_path.unlink)

        result = run_contract_validator("itsm", temp_path)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("APPROVED", result.stderr)

    def test_itsm_semantics_require_rejected_status_to_have_no_execution(self) -> None:
        payload = load_json(ITSM_FIXTURE)
        payload["status"] = "REJECTED"
        payload["approval_state"] = "REJECTED"
        payload["selected_action"] = "VALIDATE"
        payload["executed_action"] = "VALIDATE"
        payload["execution_result"]["observed"]["status"] = "PASS"
        temp_path = REPO_ROOT / "evidence" / "itsm.invalid-rejected-execution.json"
        temp_path.write_text(json.dumps(payload), encoding="utf-8")
        self.addCleanup(temp_path.unlink)

        result = run_contract_validator("itsm", temp_path)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("NOT_TESTED", result.stderr)

    def test_itsm_semantics_require_failed_status_to_include_failure_result(self) -> None:
        payload = load_json(ITSM_FIXTURE)
        payload["status"] = "FAILED"
        payload["approval_state"] = "APPROVED"
        payload["selected_action"] = "PATCH"
        payload["executed_action"] = "PATCH"
        payload["execution_result"]["observed"]["status"] = "PASS"
        payload["validation_result"]["observed"]["status"] = "PASS"
        temp_path = REPO_ROOT / "evidence" / "itsm.invalid-failed-success.json"
        temp_path.write_text(json.dumps(payload), encoding="utf-8")
        self.addCleanup(temp_path.unlink)

        result = run_contract_validator("itsm", temp_path)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("FAILED", result.stderr)

    def test_validator_rejects_incomplete_evidence_structure_via_schema(self) -> None:
        payload = load_json(EVIDENCE_FIXTURE)
        payload["status"] = "incomplete"
        temp_path = REPO_ROOT / "evidence" / "evidence.invalid-incomplete-structure.json"
        temp_path.write_text(json.dumps(payload), encoding="utf-8")
        self.addCleanup(temp_path.unlink)

        result = run_contract_validator("evidence", temp_path)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("schema", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
