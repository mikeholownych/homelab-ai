from __future__ import annotations

import importlib.util
import json
import py_compile
import subprocess
import sys
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import validate_contract  # noqa: E402

TUNING_DIR = REPO_ROOT / "profiles" / "tuning"
TUNING_POLICY = REPO_ROOT / "policies" / "tuning.yml"
ROLE_DIR = REPO_ROOT / "roles" / "os_tuning"
COLLECTOR_PATH = ROLE_DIR / "files" / "collect_telemetry.py"
HELPER_PATH = ROLE_DIR / "files" / "set_cpu_power.py"
AGGREGATOR_PATH = REPO_ROOT / "roles" / "validation" / "files" / "aggregate_validation.py"
MANAGED_SUBSYSTEMS = (
    "cpu",
    "numa",
    "memory",
    "transparent_hugepages",
    "hugepages",
    "io",
    "irq",
    "kernel",
)
TUNING_CHECK_IDS = (
    "os_tuning_profile",
    "os_tuning_governor",
    "os_tuning_thp",
    "os_tuning_hugepages",
    "os_tuning_sysctl",
    "running_kernel",
    "numa_topology",
)


def load_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def profile_names() -> list[str]:
    return sorted(path.stem for path in TUNING_DIR.glob("*.yml"))


def subsystem_deltas(candidate: dict, baseline: dict) -> list[str]:
    changed = []
    for subsystem in MANAGED_SUBSYSTEMS:
        if candidate["os_tuning"][subsystem] != baseline["os_tuning"][subsystem]:
            changed.append(subsystem)
    return changed


class TuningProfileContractTests(unittest.TestCase):
    def test_expected_profile_set_exists(self) -> None:
        self.assertEqual(
            ["baseline", "custom_kernel_candidate", "inference_candidate_01", "inference_candidate_02"],
            profile_names(),
        )

    def test_every_tuning_profile_validates_against_versioned_schema(self) -> None:
        for name in profile_names():
            document = load_yaml(TUNING_DIR / f"{name}.yml")
            errors = validate_contract.collect_schema_errors("tuning_profile", document)
            self.assertEqual([], errors, f"{name} failed schema validation: {errors}")

    def test_schema_is_registered_in_contract_registry(self) -> None:
        paths = validate_contract.get_schema_paths()
        self.assertTrue(paths["tuning_profile"].exists())

    def test_schema_rejects_unknown_governor_value(self) -> None:
        document = load_yaml(TUNING_DIR / "baseline.yml")
        document["profile_name"] = "negative_test"
        document["state"] = "candidate"
        document["os_tuning"]["cpu"]["governor"] = "turbo"
        self.assertNotEqual([], validate_contract.collect_schema_errors("tuning_profile", document))

    def test_baseline_is_conservative_and_authoritative(self) -> None:
        document = load_yaml(TUNING_DIR / "baseline.yml")
        state = document["os_tuning"]
        self.assertEqual("baseline", document["state"])
        for field in ("governor", "energy_performance_preference", "cstate_policy"):
            self.assertIsNone(state["cpu"][field])
        self.assertFalse(state["cpu"]["affinity_enabled"])
        self.assertEqual("default", state["numa"]["policy"])
        self.assertFalse(state["numa"]["runtime_binding_enabled"])
        for field in ("swappiness", "dirty_ratio", "dirty_background_ratio", "zone_reclaim_mode"):
            self.assertIsNone(state["memory"][field])
        self.assertEqual("default", state["transparent_hugepages"]["enabled"])
        self.assertEqual("default", state["transparent_hugepages"]["defrag"])
        self.assertFalse(state["hugepages"]["enabled"])
        self.assertIsNone(state["hugepages"]["size_kib"])
        self.assertIsNone(state["io"]["scheduler"])
        self.assertIsNone(state["io"]["read_ahead_kb"])
        self.assertFalse(state["irq"]["affinity_enabled"])
        self.assertEqual({}, state["kernel"]["sysctl"])
        self.assertEqual([], state["kernel"]["cmdline"])
        self.assertIsNone(state["kernel"]["expected_release"])
        self.assertFalse(state["custom_kernel"]["enabled"])

    def test_candidates_are_single_subsystem_experiments_derived_from_baseline(self) -> None:
        baseline = load_yaml(TUNING_DIR / "baseline.yml")
        for name in ("inference_candidate_01", "inference_candidate_02"):
            candidate = load_yaml(TUNING_DIR / f"{name}.yml")
            self.assertEqual("candidate", candidate["state"], name)
            self.assertEqual("baseline", candidate["parent_baseline"], name)
            deltas = subsystem_deltas(candidate, baseline)
            self.assertEqual(1, len(deltas), f"{name} must change exactly one subsystem, got {deltas}")

    def test_high_risk_classes_stay_disabled_in_every_shipped_profile(self) -> None:
        for name in profile_names():
            profile = load_yaml(TUNING_DIR / f"{name}.yml")["os_tuning"]
            self.assertFalse(profile["custom_kernel"]["enabled"], name)
            self.assertFalse(profile["numa"]["runtime_binding_enabled"], name)
            self.assertFalse(profile["irq"]["affinity_enabled"], name)


class TuningPolicyContractTests(unittest.TestCase):
    def test_promotion_policy_declares_full_lifecycle(self) -> None:
        policy = load_yaml(TUNING_POLICY)
        self.assertEqual("1.0.0", policy["schema_version"])
        authoritative_expectations = {
            "baseline": True,
            "accepted": True,
            "candidate": False,
            "rejected": False,
        }
        for state, expected_authoritative in authoritative_expectations.items():
            self.assertIn(state, policy["states"])
            self.assertEqual(expected_authoritative, policy["states"][state]["authoritative"], state)

    def test_promotion_criteria_thresholds_exist_and_are_sane(self) -> None:
        criteria = load_yaml(TUNING_POLICY)["promotion"]["criteria"]
        self.assertGreaterEqual(criteria["min_runs_per_profile"], 3)
        self.assertGreater(criteria["min_generation_throughput_improvement_pct"], 0.0)
        self.assertTrue(criteria["correctness_required"])
        self.assertTrue(criteria["stability_required"])
        self.assertTrue(criteria["reboot_persistence_required"])
        self.assertTrue(criteria["soak_required"])

    def test_rejection_procedure_preserves_evidence_and_rolls_back(self) -> None:
        rejection = load_yaml(TUNING_POLICY)["rejection"]
        procedure = "\n".join(rejection["procedure"])
        self.assertIn("rejected", procedure)
        self.assertIn("reconverge", procedure)

    def test_custom_kernel_requires_prebuilt_first_with_documented_justification(self) -> None:
        kernel_rules = load_yaml(TUNING_POLICY)["kernel_experiments"]
        self.assertTrue(kernel_rules["prebuilt_first"])
        self.assertTrue(kernel_rules["supported_sources_only"])
        self.assertTrue(kernel_rules["pin_in_git"])
        self.assertTrue(kernel_rules["retain_previous_kernel"])
        self.assertGreaterEqual(len(kernel_rules["custom_kernel_requires"]), 3)


class OsTuningRoleStructureTests(unittest.TestCase):
    REQUIRED_ROLE_FILES = (
        "defaults/main.yml",
        "tasks/main.yml",
        "handlers/main.yml",
        "meta/main.yml",
        "files/collect_telemetry.py",
        "files/set_cpu_power.py",
        "templates/95-aihost-tuning.cfg.j2",
        "templates/61-aihost-io.rules.j2",
        "templates/aihost-cpu-power.service.j2",
    )

    def test_role_files_present(self) -> None:
        for relative in self.REQUIRED_ROLE_FILES:
            self.assertTrue((ROLE_DIR / relative).exists(), relative)

    def test_role_tasks_avoid_shell_module_blanket_ignore_errors_and_latest_state(self) -> None:
        for path in sorted((ROLE_DIR / "tasks").glob("*.yml")):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("ansible.builtin.shell:", text, path.name)
            self.assertNotIn("ignore_errors", text, path.name)
            self.assertNotIn("state: latest", text, path.name)

    def test_role_commands_always_declare_changed_semantics(self) -> None:
        for path in sorted((ROLE_DIR / "tasks").glob("*.yml")):
            tasks = yaml.safe_load(path.read_text(encoding="utf-8")) or []
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                has_command = any(
                    isinstance(key, str) and key.startswith("ansible.builtin.command") for key in task
                )
                if has_command:
                    self.assertIn(
                        "changed_when",
                        task,
                        f"{path.name}: command task '{task.get('name')}' must declare changed_when",
                    )

    def test_safety_gates_cover_all_certification_flags(self) -> None:
        gates = (ROLE_DIR / "tasks" / "safety_gates.yml").read_text(encoding="utf-8")
        self.assertIn("os_tuning_irq_affinity_certified", gates)
        self.assertIn("os_tuning_numa_binding_certified", gates)
        self.assertIn("os_tuning_custom_kernel_certified", gates)

    def test_defaults_keep_high_risk_classes_uncertified(self) -> None:
        defaults = load_yaml(ROLE_DIR / "defaults" / "main.yml")
        self.assertFalse(defaults["os_tuning_irq_affinity_certified"])
        self.assertFalse(defaults["os_tuning_numa_binding_certified"])
        self.assertFalse(defaults["os_tuning_custom_kernel_certified"])
        self.assertFalse(defaults["os_tuning_kernel_drift_autoremediate"])
        self.assertLessEqual(defaults["os_tuning_hugepages_max_host_memory_pct"], 50)
        self.assertEqual("baseline", defaults["os_tuning_profile"])

    def test_role_file_paths_do_not_collide_with_base_os(self) -> None:
        defaults = load_yaml(ROLE_DIR / "defaults" / "main.yml")
        base_os_defaults = load_yaml(REPO_ROOT / "roles" / "base_os" / "defaults" / "main.yml")
        self.assertNotEqual(
            defaults["os_tuning_grub_dropin_path"],
            base_os_defaults.get("base_os_grub_dropin_path"),
        )
        self.assertIn("95-aihost-tuning.cfg", defaults["os_tuning_grub_dropin_path"])


class TelemetryCollectorTests(unittest.TestCase):
    def test_python_sources_compile_without_execution_side_effects(self) -> None:
        for source in (COLLECTOR_PATH, HELPER_PATH):
            py_compile.compile(str(source), doraise=True)

    def test_collector_avoids_shell_out_patterns(self) -> None:
        text = COLLECTOR_PATH.read_text(encoding="utf-8")
        self.assertNotIn("shell=True", text)
        self.assertNotIn("os.system", text)

    def test_collector_produces_all_evidence_sections_on_this_host(self) -> None:
        result = subprocess.run(
            [sys.executable, str(COLLECTOR_PATH)], capture_output=True, text=True, timeout=120, check=False
        )
        self.assertEqual(0, result.returncode, result.stderr)
        observed = json.loads(result.stdout)
        for section in ("numa", "interrupts", "cpu_power", "memory_policy", "hugepages", "io", "kernel"):
            self.assertIn(section, observed)
        self.assertIs(observed["simulated"], False)
        self.assertIsInstance(observed["kernel"]["running_release"], str)
        self.assertIsInstance(observed["interrupts"]["total_irq_lines"], int)

    def test_bracketed_choice_parses_active_thp_mode(self) -> None:
        module = load_module("collect_telemetry_under_test", COLLECTOR_PATH)
        self.assertEqual("always", module.bracketed_choice("[always] madvise never"))
        self.assertEqual("madvise", module.bracketed_choice("always [madvise] never"))
        self.assertIsNone(module.bracketed_choice("always madvise never"))

    def test_helper_exposes_validate_mode_interface(self) -> None:
        help_result = subprocess.run(
            [sys.executable, str(HELPER_PATH), "--help"], capture_output=True, check=False
        )
        self.assertEqual(0, help_result.returncode)
        self.assertIn(b"--validate", help_result.stdout)


class ValidationIntegrationTests(unittest.TestCase):
    def test_aggregator_knows_all_tuning_checks(self) -> None:
        aggregator = load_module("aggregate_validation_under_test", AGGREGATOR_PATH)
        for check_id in TUNING_CHECK_IDS:
            self.assertIn(check_id, aggregator.REQUIRED_CHECKS_SPEC, check_id)

    def test_validation_policy_lists_matching_check_ids(self) -> None:
        policy_ids = {
            item["id"] for item in load_yaml(REPO_ROOT / "policies" / "validation.yml")["required_checks"]
        }
        for check_id in TUNING_CHECK_IDS:
            self.assertIn(check_id, policy_ids, check_id)

    def test_inventory_selects_baseline_profile_with_feature_enabled(self) -> None:
        host_vars = load_yaml(REPO_ROOT / "inventory/production/host_vars/ai-p620-01.yml")
        self.assertEqual("baseline", host_vars["os_tuning_profile"])
        self.assertTrue(host_vars["features"]["os_tuning"])

    def test_site_playbook_includes_os_tuning_before_runtime_roles(self) -> None:
        site = (REPO_ROOT / "playbooks/site.yml").read_text(encoding="utf-8")
        tuning_position = site.find("name: os_tuning")
        pytorch_position = site.find("name: pytorch_xpu")
        vllm_position = site.find("name: vllm_xpu")
        self.assertGreater(tuning_position, -1)
        self.assertGreater(pytorch_position, tuning_position)
        self.assertGreater(vllm_position, pytorch_position)

    def test_read_only_paths_disable_mutations(self) -> None:
        for playbook in ("validate.yml", "drift-check.yml"):
            text = (REPO_ROOT / "playbooks" / playbook).read_text(encoding="utf-8")
            self.assertIn("os_tuning_apply_mutations: false", text, playbook)


if __name__ == "__main__":
    unittest.main()


class HugepagesParamContractTests(unittest.TestCase):
    """The generator and the allowlist must agree on kernel syntax (1G/2M, no B)."""

    def _patterns(self):
        defaults = load_yaml(ROLE_DIR / "defaults" / "main.yml")
        return defaults["os_tuning_allowed_boot_parameter_patterns"]

    def test_generated_hugepages_params_match_allowlist(self) -> None:
        import re

        patterns = self._patterns()
        generated = [
            "transparent_hugepage=always",
            "default_hugepagesz=1G",
            "hugepagesz=2M",
            "hugepages=512",
        ]
        for param in generated:
            self.assertTrue(
                any(re.match(str(p), param) for p in patterns),
                f"{param} generated by the role is rejected by its own allowlist",
            )

    def test_kernel_rejects_b_suffixed_sizes(self) -> None:
        import re

        patterns = self._patterns()
        for bad in ("default_hugepagesz=1GB", "hugepagesz=2MB"):
            self.assertFalse(
                any(re.match(str(p), bad) for p in patterns),
                f"{bad} is not valid kernel syntax but the allowlist accepts it",
            )


class CpuPowerHelperToleranceTests(unittest.TestCase):
    def test_missing_cpufreq_attributes_record_unavailable_not_failure(self) -> None:
        helper = load_module("set_cpu_power_under_test", HELPER_PATH)
        # On hosts without this cpufreq attribute the helper reports exit 5.
        rc = helper.apply_to_cpus("energy_performance_preference", "performance", validate_only=False)
        if not helper.online_cpus():
            self.skipTest("no cpufreq-capable CPUs on this machine")
        self.assertIn(rc, (0, 3, 5))
