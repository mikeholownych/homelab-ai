from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

import jsonschema
import yaml
from jsonschema import FormatChecker


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
            {"no_drift", "remediated_drift", "unresolved_drift", "blocking_drift"},
            set(drift["states"]),
        )
        self.assertEqual("unresolved_drift", drift["remediation"]["default_state"])
        self.assertIn("os_security_patches", drift["remediation"]["auto_reconcile_allowed_for"])
        self.assertEqual("healthy", drift["states"]["no_drift"]["classification"])
        self.assertEqual("manual_block", drift["states"]["blocking_drift"]["remediation_mode"])
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

        self.assertEqual(
            {
                "machine_model",
                "cpu_present",
                "cpu_model_match",
                "gpu_count",
                "gpu_model_match",
                "gpu_vram_per_card",
                "level_zero_device_count",
                "pytorch_xpu_device_count",
                "per_device_tensor_operations",
                "pcie_topology",
                "resizable_bar_enabled",
                "above_4g_decoding_enabled",
                "vllm_health",
                "single_gpu_inference_configured",
                "dual_gpu_inference_configured",
                "llama_cpp_fallback_health",
                "required_services",
                "scheduled_reconciliation",
                "vault_access",
            },
            set(checks),
        )
        self.assertEqual("30E1S7NJ00", checks["machine_model"]["expected"]["value"])
        self.assertEqual("blocking", checks["machine_model"]["severity"])
        self.assertEqual("hardware", checks["cpu_present"]["classification"])
        self.assertEqual("blocking", checks["cpu_model_match"]["severity"])
        self.assertEqual("blocking", checks["gpu_count"]["severity"])
        self.assertEqual("blocking", checks["gpu_model_match"]["severity"])
        self.assertEqual(32, checks["gpu_vram_per_card"]["expected"]["target_gib"])
        self.assertEqual(28, checks["gpu_vram_per_card"]["expected"]["minimum_gib"])
        self.assertEqual(36, checks["gpu_vram_per_card"]["expected"]["maximum_gib"])
        self.assertEqual(2, checks["level_zero_device_count"]["expected"]["value"])
        self.assertEqual(2, checks["pytorch_xpu_device_count"]["expected"]["value"])
        self.assertEqual("always", checks["per_device_tensor_operations"]["applies_when"])
        self.assertEqual("always", checks["pcie_topology"]["applies_when"])
        self.assertEqual("blocking", checks["resizable_bar_enabled"]["severity"])
        self.assertEqual("blocking", checks["above_4g_decoding_enabled"]["severity"])
        self.assertEqual("when_observable", checks["above_4g_decoding_enabled"]["applies_when"])
        self.assertEqual("NOT_TESTED", checks["above_4g_decoding_enabled"]["undiscoverable_result"])
        self.assertEqual("when_vllm_enabled", checks["vllm_health"]["applies_when"])
        self.assertEqual("always", checks["single_gpu_inference_configured"]["applies_when"])
        self.assertEqual(
            "when_selected_inference_profile_tensor_parallel_size_equals_2",
            checks["dual_gpu_inference_configured"]["applies_when"],
        )
        self.assertEqual("when_llama_cpp_enabled", checks["llama_cpp_fallback_health"]["applies_when"])
        self.assertEqual("warning", checks["required_services"]["severity"])
        self.assertEqual("information", checks["scheduled_reconciliation"]["severity"])
        self.assertEqual("blocking", checks["vault_access"]["severity"])

    def test_schema_fixtures_validate_against_draft_2020_12_contracts(self) -> None:
        format_checker = FormatChecker()
        for schema_name, fixture_path in SCHEMA_FIXTURES.items():
            with self.subTest(schema=schema_name):
                schema = load_json(SCHEMA_DIR / f"{schema_name}.schema.json")
                fixture = load_json(fixture_path)
                self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])
                jsonschema.Draft202012Validator.check_schema(schema)
                jsonschema.validate(fixture, schema, format_checker=format_checker)

    def test_schemas_reject_invalid_extra_properties_status_and_missing_expected_observed(self) -> None:
        format_checker = FormatChecker()
        for schema_name, fixture_path in SCHEMA_FIXTURES.items():
            with self.subTest(schema=schema_name):
                schema = load_json(SCHEMA_DIR / f"{schema_name}.schema.json")
                fixture = load_json(fixture_path)
                validator = jsonschema.Draft202012Validator(schema, format_checker=format_checker)

                extra_property_case = copy.deepcopy(fixture)
                extra_property_case["unexpected"] = True
                self.assertTrue(list(validator.iter_errors(extra_property_case)))

                invalid_status_case = copy.deepcopy(fixture)
                invalid_status_case["status"] = "invalid-status"
                self.assertTrue(list(validator.iter_errors(invalid_status_case)))

                invalid_timestamp_case = copy.deepcopy(fixture)
                invalid_timestamp_case["generated_at"] = "2026-99-99T25:61:61Z"
                self.assertTrue(list(validator.iter_errors(invalid_timestamp_case)))

                missing_expected_observed_case = copy.deepcopy(fixture)
                if schema_name == "validation":
                    del missing_expected_observed_case["checks"][0]["expected"]
                    nested_extra_property_case = copy.deepcopy(fixture)
                    nested_extra_property_case["checks"][0]["expected"]["unexpected"] = True
                elif schema_name == "evidence":
                    del missing_expected_observed_case["artifacts"][0]["observed"]
                    nested_extra_property_case = copy.deepcopy(fixture)
                    nested_extra_property_case["artifacts"][0]["observed"]["unexpected"] = True
                    status_case = copy.deepcopy(fixture)
                    status_case["status"] = "incomplete"
                    self.assertFalse(list(validator.iter_errors(status_case)))
                elif schema_name == "benchmark":
                    del missing_expected_observed_case["correctness"]["observed"]
                    nested_extra_property_case = copy.deepcopy(fixture)
                    nested_extra_property_case["telemetry"]["prompt_tokens_per_second"]["expected"]["unexpected"] = True
                elif schema_name == "cmdb":
                    del missing_expected_observed_case["configuration_item"]["observed"]
                    nested_extra_property_case = copy.deepcopy(fixture)
                    nested_extra_property_case["configuration_item"]["expected"]["runtime_versions"]["unexpected"] = True
                    extra_capability_case = copy.deepcopy(fixture)
                    extra_capability_case["configuration_item"]["expected"]["capabilities"]["arbitrary_future_command_capability"] = True
                    self.assertTrue(list(validator.iter_errors(extra_capability_case)))
                elif schema_name == "itsm":
                    del missing_expected_observed_case["execution_result"]["observed"]
                    nested_extra_property_case = copy.deepcopy(fixture)
                    nested_extra_property_case["validation_result"]["observed"]["unexpected"] = True
                self.assertTrue(list(validator.iter_errors(missing_expected_observed_case)))
                self.assertTrue(list(validator.iter_errors(nested_extra_property_case)))

    def test_validation_schema_uses_uppercase_terminal_statuses(self) -> None:
        schema = load_json(SCHEMA_DIR / "validation.schema.json")
        self.assertEqual(["PASS", "FAIL", "BLOCKED", "NOT_TESTED"], schema["properties"]["status"]["enum"])
        check_status_enum = schema["properties"]["checks"]["items"]["properties"]["status"]["enum"]
        self.assertEqual(["PASS", "FAIL", "BLOCKED", "NOT_TESTED"], check_status_enum)

    def test_benchmark_schema_requires_duration_and_model_split_parameters(self) -> None:
        schema = load_json(SCHEMA_DIR / "benchmark.schema.json")
        self.assertIn("duration", schema["required"])
        self.assertIn("split_parameters", schema["properties"]["model"]["properties"])
        correctness_required = schema["properties"]["correctness"]["required"]
        self.assertEqual(["status", "summary", "expected", "observed"], correctness_required)

    def test_evidence_schema_allows_incomplete_status(self) -> None:
        schema = load_json(SCHEMA_DIR / "evidence.schema.json")
        self.assertIn("incomplete", schema["properties"]["status"]["enum"])


if __name__ == "__main__":
    unittest.main()
