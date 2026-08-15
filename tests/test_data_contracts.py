from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

import jsonschema
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
HARDWARE_PROFILE = REPO_ROOT / "profiles" / "hardware" / "p620_dual_b65.yml"
PATCHING_POLICY = REPO_ROOT / "policies" / "patching.yml"
UPGRADES_POLICY = REPO_ROOT / "policies" / "upgrades.yml"
DRIFT_POLICY = REPO_ROOT / "policies" / "drift.yml"
VALIDATION_POLICY = REPO_ROOT / "policies" / "validation.yml"
SCHEMA_DIR = REPO_ROOT / "schemas"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "schemas"

SCHEMA_FIXTURES = {
    "validation": FIXTURE_DIR / "validation.valid.json",
    "evidence": FIXTURE_DIR / "evidence.valid.json",
    "benchmark": FIXTURE_DIR / "benchmark.valid.json",
    "cmdb": FIXTURE_DIR / "cmdb.valid.json",
    "itsm": FIXTURE_DIR / "itsm.valid.json",
}


def load_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


class DataContractTests(unittest.TestCase):
    def test_hardware_profile_matches_requested_contract(self) -> None:
        profile = load_yaml(HARDWARE_PROFILE)

        self.assertEqual("1.0.0", profile["schema_version"])
        self.assertEqual("p620_dual_b65", profile["profile_name"])
        self.assertEqual("30E1S7NJ00", profile["platform"]["machine_type_model"])
        self.assertIn("AMD Ryzen Threadripper PRO 3945WX", profile["cpu"]["model_patterns"])
        self.assertEqual(2, profile["gpu"]["count_expected"])
        self.assertEqual("Intel Arc Pro B65", profile["gpu"]["expected_models"][0]["model"])
        self.assertEqual(32, profile["gpu"]["expected_models"][0]["memory_gib"]["approximate"])
        self.assertEqual(4, profile["gpu"]["expected_models"][0]["memory_gib"]["tolerance_gib"])
        self.assertEqual(4, profile["pcie"]["host_link"]["max_generation"])
        self.assertEqual("blocking", profile["pcie"]["material_degradation"]["default_severity"])
        self.assertEqual(
            "not_tested",
            profile["firmware"]["above_4g_decoding"]["undiscoverable_status"],
        )
        self.assertEqual("blocking", profile["firmware"]["resizable_bar"]["missing_severity"])
        self.assertEqual(48, profile["memory"]["installed_gib"]["expected"])
        self.assertEqual("warning", profile["memory"]["installed_gib"]["out_of_tolerance_severity"])
        self.assertIn("dimm_topology", profile["discovery_fields"]["record"])
        self.assertIn("serial_number", profile["discovery_fields"]["asset_identifiers"])
        self.assertIn("gpu_model_match", profile["severity_rules"]["blocking"])
        self.assertIn("level_zero_detected", profile["severity_rules"]["blocking"])

    def test_patching_and_upgrade_policies_separate_routine_and_high_risk_lifecycles(self) -> None:
        patching = load_yaml(PATCHING_POLICY)
        upgrades = load_yaml(UPGRADES_POLICY)

        self.assertEqual({"os_packages", "security_updates"}, set(patching["routine_components"]))
        self.assertEqual(False, patching["high_risk_components"]["kernel"]["auto_apply"])
        self.assertEqual(False, patching["high_risk_components"]["intel_gpu"]["auto_apply"])
        self.assertEqual(False, patching["high_risk_components"]["firmware_bios"]["auto_apply"])

        for component_name in (
            "intel_gpu",
            "level_zero",
            "pytorch_xpu",
            "vllm",
            "llama_cpp",
            "kernel",
            "firmware_bios",
        ):
            component = upgrades["lifecycle_components"][component_name]
            self.assertIn("current", component)
            self.assertIn("candidate", component)
            self.assertIn("previous_known_good", component)
            self.assertEqual(False, component["enabled"])
            self.assertEqual("commissioning_required", component["commissioning_state"])
            self.assertIsNone(component["current"])
            self.assertIsNone(component["candidate"])
            self.assertIsNone(component["previous_known_good"])

    def test_drift_policy_defines_four_states_and_manual_remediation_for_high_risk_components(self) -> None:
        drift = load_yaml(DRIFT_POLICY)

        self.assertEqual(
            {"in_sync", "drift_detected", "reconciliation_pending", "exception_approved"},
            set(drift["states"]),
        )
        self.assertEqual("drift_detected", drift["remediation"]["default_state"])
        self.assertIn("os_security_patches", drift["remediation"]["auto_reconcile_allowed_for"])
        for component_name in (
            "kernel",
            "intel_gpu",
            "level_zero",
            "pytorch_xpu",
            "vllm",
            "llama_cpp",
            "firmware_bios",
        ):
            self.assertIn(component_name, drift["remediation"]["manual_approval_required_for"])

    def test_validation_policy_requires_blocking_and_advisory_checks(self) -> None:
        validation = load_yaml(VALIDATION_POLICY)
        checks = {check["id"]: check for check in validation["required_checks"]}

        self.assertEqual("blocking", checks["gpu_count"]["severity"])
        self.assertEqual("blocking", checks["gpu_model_match"]["severity"])
        self.assertEqual("blocking", checks["resizable_bar_enabled"]["severity"])
        self.assertEqual("blocking", checks["level_zero_detected"]["severity"])
        self.assertEqual("blocking", checks["pcie_link_health"]["severity"])
        self.assertEqual("warning", checks["memory_capacity"]["severity"])
        self.assertEqual("information", checks["dimm_topology_observed"]["severity"])

    def test_schema_fixtures_validate_against_draft_2020_12_contracts(self) -> None:
        for schema_name, fixture_path in SCHEMA_FIXTURES.items():
            with self.subTest(schema=schema_name):
                schema = load_json(SCHEMA_DIR / f"{schema_name}.schema.json")
                fixture = load_json(fixture_path)
                self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])
                jsonschema.Draft202012Validator.check_schema(schema)
                jsonschema.validate(fixture, schema)

    def test_schemas_reject_invalid_extra_properties_status_and_missing_expected_observed(self) -> None:
        for schema_name, fixture_path in SCHEMA_FIXTURES.items():
            with self.subTest(schema=schema_name):
                schema = load_json(SCHEMA_DIR / f"{schema_name}.schema.json")
                fixture = load_json(fixture_path)
                validator = jsonschema.Draft202012Validator(schema)

                extra_property_case = copy.deepcopy(fixture)
                extra_property_case["unexpected"] = True
                self.assertTrue(list(validator.iter_errors(extra_property_case)))

                invalid_status_case = copy.deepcopy(fixture)
                invalid_status_case["status"] = "invalid-status"
                self.assertTrue(list(validator.iter_errors(invalid_status_case)))

                missing_expected_observed_case = copy.deepcopy(fixture)
                if schema_name == "validation":
                    del missing_expected_observed_case["checks"][0]["expected"]
                elif schema_name == "evidence":
                    del missing_expected_observed_case["artifacts"][0]["observed"]
                elif schema_name == "benchmark":
                    del missing_expected_observed_case["measurements"][0]["expected"]
                elif schema_name == "cmdb":
                    del missing_expected_observed_case["inventory"]["observed"]
                elif schema_name == "itsm":
                    del missing_expected_observed_case["change_request"]["observed"]
                self.assertTrue(list(validator.iter_errors(missing_expected_observed_case)))


if __name__ == "__main__":
    unittest.main()
