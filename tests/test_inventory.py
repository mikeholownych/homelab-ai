from __future__ import annotations

import configparser
import json
import os
import subprocess
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_ROOT = REPO_ROOT / "inventory" / "production"
LAB_ROOT = REPO_ROOT / "inventory" / "lab"
PRODUCTION_INVENTORY = PRODUCTION_ROOT / "hosts.yml"
LAB_INVENTORY = LAB_ROOT / "hosts.yml"
PRODUCTION_HOST_VARS = PRODUCTION_ROOT / "host_vars" / "ai-p620-01.yml"
PRODUCTION_HOST_VARS_5820 = PRODUCTION_ROOT / "host_vars" / "ai-5820-01.yml"
PRODUCTION_GROUP_VARS = PRODUCTION_ROOT / "group_vars"
INVENTORY_README = REPO_ROOT / "inventory" / "README.md"

PRODUCTION_HOSTS = ("ai-p620-01", "ai-5820-01")

REQUIRED_PATHS = (
    INVENTORY_README,
    PRODUCTION_INVENTORY,
    PRODUCTION_GROUP_VARS / "all.yml",
    PRODUCTION_GROUP_VARS / "inference.yml",
    PRODUCTION_GROUP_VARS / "gpu.yml",
    PRODUCTION_GROUP_VARS / "cluster.yml",
    PRODUCTION_GROUP_VARS / "monitoring.yml",
    PRODUCTION_HOST_VARS,
    PRODUCTION_HOST_VARS_5820,
    LAB_INVENTORY,
)

HOST_PROFILES = {
    "ai-p620-01": "p620_dual_b65",
    "ai-5820-01": "d5820_dual_b65",
}

IDENTITY_TAG_TOKENS = {"production", "p620_dual_b65", "inference", "gpu", "ai-p620-01"}


def load_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def run_ansible_inventory(inventory_path: Path) -> tuple[dict[str, object], str]:
    executable = REPO_ROOT / ".venv" / "bin" / "ansible-inventory"
    command = [str(executable if executable.exists() else "ansible-inventory"), "-i", str(inventory_path), "--list"]
    env = os.environ.copy()
    env["ANSIBLE_CONFIG"] = str(REPO_ROOT / "ansible.cfg")
    output = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(output.stdout), output.stderr


def run_playbook_list_hosts(inventory_path: Path, playbook_path: Path) -> str:
    executable = REPO_ROOT / ".venv" / "bin" / "ansible-playbook"
    command = [str(executable if executable.exists() else "ansible-playbook"), "-i", str(inventory_path), str(playbook_path), "--list-hosts"]
    env = os.environ.copy()
    env["ANSIBLE_CONFIG"] = str(REPO_ROOT / "ansible.cfg")
    output = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return output.stdout


class InventoryContractTests(unittest.TestCase):
    def test_ansible_default_inventory_is_production_and_local_checks_use_fixture(self) -> None:
        parser = configparser.ConfigParser()
        parser.read(REPO_ROOT / "ansible.cfg", encoding="utf-8")
        self.assertEqual("inventory/production/hosts.yml", parser["defaults"]["inventory"])

        makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("-i tests/fixtures/inventory/healthy.yml --check tests/integration/baseline_os.yml", makefile)
        self.assertIn("localhost-safe", makefile)

    def test_required_inventory_contract_files_exist(self) -> None:
        missing = sorted(str(path.relative_to(REPO_ROOT)) for path in REQUIRED_PATHS if not path.exists())
        self.assertEqual([], missing, f"Missing inventory contract paths: {missing}")

    def test_production_host_metadata_matches_contract(self) -> None:
        for hostname in PRODUCTION_HOSTS:
            path = PRODUCTION_ROOT / "host_vars" / f"{hostname}.yml"
            host_vars = load_yaml(path)
            expected_profile = HOST_PROFILES[hostname]
            with self.subTest(host=hostname):
                self.assertEqual("CHANGE_ME", host_vars["ansible_host"])
                self.assertEqual("production", host_vars["node_metadata"]["environment"])
                self.assertEqual(hostname, host_vars["node_metadata"]["hostname"])
                self.assertEqual(expected_profile, host_vars["hardware_profile"])
                self.assertEqual({"inference": True, "gpu": True}, host_vars["node_roles"])
                self.assertEqual("worker", host_vars["cluster"]["node_role"])
                self.assertEqual(
                    {"worker": True, "api": False, "scheduler": False, "storage": False},
                    host_vars["cluster"]["roles"],
                )
                self.assertEqual(
                    {
                        "gpu": True,
                        "inference": True,
                        "benchmarking": True,
                        "monitoring": True,
                        "cluster_eligible": True,
                    },
                    host_vars["capabilities"],
                )
                self.assertEqual(
                    {
                        "monitoring": True,
                        "scheduled_reconciliation": True,
                        "os_tuning": True,
                        "model_registry": False,
                        "clustering": False,
                        "cmdb_export": False,
                        "itsm_integration": False,
                        "ray_enabled": False,
                        "distributed_vllm_enabled": False,
                    },
                    host_vars["features"],
                )

                for tag in host_vars.get("tags", []):
                    self.assertNotIn(tag, IDENTITY_TAG_TOKENS)

                self.assertEqual(
                    {
                        "enabled": False,
                        "name": None,
                        "membership_state": "standalone",
                        "node_role": "worker",
                        "roles": {"worker": True, "api": False, "scheduler": False, "storage": False},
                        "capabilities": {
                            "ray": False,
                            "distributed_vllm": False,
                            "worker_service": True,
                            "api_service": False,
                            "scheduler_service": False,
                            "storage_service": False,
                        },
                        "ray_enabled": False,
                        "distributed_vllm_enabled": False,
                        "endpoints": {
                            "api_base_url": None,
                            "scheduler_address": None,
                            "ray_gcs_address": None,
                            "object_storage_url": None,
                        },
                        "fleet": {
                            "id": None,
                            "coordinator": None,
                            "peer_hosts": [],
                            "quorum_size": None,
                        },
                    },
                    host_vars["cluster"],
                )
                self.assertEqual(
                    {
                        "primary_bind_address": None,
                        "management_fqdn": None,
                        "metrics_endpoint": None,
                    },
                    host_vars["network_endpoints"],
                )

    def test_production_inventory_parses_and_keeps_host_metadata_authoritative(self) -> None:
        inventory, stderr = run_ansible_inventory(PRODUCTION_INVENTORY)
        self.assertEqual("", stderr.strip())

        self.assertEqual(["production", "inference", "gpu", "cluster", "monitoring"], inventory["ai_hosts"]["children"])
        for group in ("production", "inference", "gpu", "cluster", "monitoring"):
            self.assertEqual(set(PRODUCTION_HOSTS), set(inventory[group]["hosts"]))
            self.assertEqual(2, len(inventory[group]["hosts"]))

        hostvars = inventory["_meta"]["hostvars"]["ai-p620-01"]
        self.assertEqual("production", hostvars["node_metadata"]["environment"])
        self.assertEqual("p620_dual_b65", hostvars["hardware_profile"])
        self.assertEqual("CHANGE_ME", hostvars["ansible_host"])
        self.assertEqual(False, hostvars["features"]["clustering"])
        self.assertEqual(False, hostvars["features"]["ray_enabled"])
        self.assertEqual(False, hostvars["features"]["distributed_vllm_enabled"])
        self.assertIn("inference_secret_paths", hostvars)
        self.assertIn("gpu_secret_paths", hostvars)
        self.assertIn("cluster_secret_paths", hostvars)
        self.assertIn("monitoring_secret_paths", hostvars)
        self.assertIn("cluster_defaults", hostvars)
        self.assertEqual("worker", hostvars["cluster"]["node_role"])
        self.assertEqual("unselected", hostvars["model_selection_controls"]["serving_model"]["selection_state"])
        self.assertEqual("disabled", hostvars["model_selection_controls"]["benchmark_model"]["execution_state"])
        self.assertIsNone(hostvars["cluster"]["endpoints"]["api_base_url"])

        hostvars_5820 = inventory["_meta"]["hostvars"]["ai-5820-01"]
        self.assertEqual("production", hostvars_5820["node_metadata"]["environment"])
        self.assertEqual("d5820_dual_b65", hostvars_5820["hardware_profile"])
        self.assertEqual("CHANGE_ME", hostvars_5820["ansible_host"])
        self.assertEqual(False, hostvars_5820["features"]["clustering"])
        self.assertEqual(False, hostvars_5820["features"]["ray_enabled"])
        self.assertEqual(False, hostvars_5820["features"]["distributed_vllm_enabled"])
        self.assertEqual("worker", hostvars_5820["cluster"]["node_role"])
        self.assertEqual("unselected", hostvars_5820["model_selection_controls"]["serving_model"]["selection_state"])
        self.assertEqual("disabled", hostvars_5820["model_selection_controls"]["benchmark_model"]["execution_state"])
        self.assertEqual(950, hostvars_5820["benchmarking_psu_capacity_watts"])
        self.assertEqual(200, hostvars_5820["benchmarking_gpu_tdp_watts"])
        self.assertIsNone(hostvars_5820["cluster"]["endpoints"]["api_base_url"])

    def test_production_site_playbook_list_hosts_resolves_ai_hosts(self) -> None:
        output = run_playbook_list_hosts(PRODUCTION_INVENTORY, REPO_ROOT / "playbooks" / "site.yml")
        for hostname in PRODUCTION_HOSTS:
            self.assertIn(hostname, output)

    def test_lab_inventory_parses_without_declaring_hosts(self) -> None:
        inventory, stderr = run_ansible_inventory(LAB_INVENTORY)
        self.assertEqual("", stderr.strip())
        self.assertEqual({}, inventory["_meta"]["hostvars"])
        self.assertEqual([], inventory.get("lab", {}).get("hosts", []))

    def test_group_vars_use_only_secret_path_references_and_disabled_commissioning_profiles(self) -> None:
        all_vars = load_yaml(PRODUCTION_GROUP_VARS / "all.yml")
        inference_vars = load_yaml(PRODUCTION_GROUP_VARS / "inference.yml")
        gpu_vars = load_yaml(PRODUCTION_GROUP_VARS / "gpu.yml")

        for secret_path in all_vars["secret_paths"].values():
            self.assertIsInstance(secret_path, str)
            self.assertTrue(secret_path.startswith("secret/"), secret_path)

        for secret_path in inference_vars["inference_secret_paths"].values():
            self.assertTrue(secret_path.startswith("secret/"), secret_path)

        for secret_path in gpu_vars["gpu_secret_paths"].values():
            self.assertTrue(secret_path.startswith("secret/"), secret_path)

        for model_profile in inference_vars["model_profiles"].values():
            self.assertEqual(False, model_profile["enabled"])
            self.assertEqual("commissioning_required", model_profile["commissioning_state"])
            self.assertIsNone(model_profile["model_id"])

        for runtime_profile in gpu_vars["runtime_profiles"].values():
            self.assertEqual(False, runtime_profile["enabled"])
            self.assertEqual("commissioning_required", runtime_profile["commissioning_state"])
            self.assertIsNone(runtime_profile["current"])
            self.assertIsNone(runtime_profile["candidate"])
            self.assertIsNone(runtime_profile["previous_known_good"])

        self.assertEqual(
            None,
            inference_vars["model_selection_controls"]["serving_model"]["config_path"],
        )
        self.assertEqual(
            "unselected",
            inference_vars["model_selection_controls"]["benchmark_model"]["selection_state"],
        )
        self.assertIsNone(inference_vars["model_selection_controls"]["benchmark_model"]["config_path"])

    def test_inventory_docs_explain_reserved_environment_key_and_operator_inputs(self) -> None:
        readme = INVENTORY_README.read_text(encoding="utf-8")
        self.assertIn("node_metadata.environment", readme)
        self.assertIn("Ansible reserves the flat variable name `environment`", readme)
        self.assertIn("sole exception", readme)
        self.assertIn("operator input", readme)
        self.assertIn("ansible_host", readme)

    def test_change_me_occurs_only_for_ansible_host(self) -> None:
        command = ["rg", "-n", "CHANGE_ME", "inventory"]
        result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertEqual(2, len(lines), lines)
        self.assertTrue(all(line.endswith("ansible_host: CHANGE_ME") for line in lines), lines)


if __name__ == "__main__":
    unittest.main()
