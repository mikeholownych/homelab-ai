from __future__ import annotations

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
PRODUCTION_GROUP_VARS = PRODUCTION_ROOT / "group_vars"

REQUIRED_PATHS = (
    PRODUCTION_INVENTORY,
    PRODUCTION_GROUP_VARS / "all.yml",
    PRODUCTION_GROUP_VARS / "inference.yml",
    PRODUCTION_GROUP_VARS / "gpu.yml",
    PRODUCTION_GROUP_VARS / "cluster.yml",
    PRODUCTION_GROUP_VARS / "monitoring.yml",
    PRODUCTION_HOST_VARS,
    LAB_INVENTORY,
)

IDENTITY_TAG_TOKENS = {"production", "p620_dual_b65", "inference", "gpu", "ai-p620-01"}


def load_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def run_ansible_inventory(inventory_path: Path) -> dict[str, object]:
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
    return json.loads(output.stdout)


class InventoryContractTests(unittest.TestCase):
    def test_required_inventory_contract_files_exist(self) -> None:
        missing = sorted(str(path.relative_to(REPO_ROOT)) for path in REQUIRED_PATHS if not path.exists())
        self.assertEqual([], missing, f"Missing inventory contract paths: {missing}")

    def test_production_host_metadata_matches_contract(self) -> None:
        host_vars = load_yaml(PRODUCTION_HOST_VARS)

        self.assertEqual("CHANGE_ME", host_vars["ansible_host"])
        self.assertEqual("production", host_vars["environment"])
        self.assertEqual("p620_dual_b65", host_vars["hardware_profile"])
        self.assertEqual({"inference": True, "gpu": True}, host_vars["node_roles"])
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
                "clustering": False,
                "cmdb_export": False,
                "itsm_integration": False,
            },
            host_vars["features"],
        )

        for tag in host_vars.get("tags", []):
            self.assertNotIn(tag, IDENTITY_TAG_TOKENS)

        self.assertEqual(
            {
                "enabled": False,
                "membership_state": "standalone",
                "fleet": {
                    "id": None,
                    "coordinator": None,
                    "peer_hosts": [],
                    "quorum_size": None,
                },
            },
            host_vars["cluster"],
        )

    def test_production_inventory_parses_and_keeps_host_metadata_authoritative(self) -> None:
        inventory = run_ansible_inventory(PRODUCTION_INVENTORY)

        self.assertEqual(["ai-p620-01"], inventory["production"]["hosts"])
        self.assertEqual(["ai-p620-01"], inventory["inference"]["hosts"])
        self.assertEqual(["ai-p620-01"], inventory["gpu"]["hosts"])

        hostvars = inventory["_meta"]["hostvars"]["ai-p620-01"]
        self.assertEqual("production", hostvars["environment"])
        self.assertEqual("p620_dual_b65", hostvars["hardware_profile"])
        self.assertEqual("CHANGE_ME", hostvars["ansible_host"])
        self.assertEqual(False, hostvars["features"]["clustering"])
        self.assertIn("inference_secret_paths", hostvars)
        self.assertIn("gpu_secret_paths", hostvars)
        self.assertIn("monitoring_secret_paths", hostvars)

    def test_lab_inventory_parses_without_declaring_hosts(self) -> None:
        inventory = run_ansible_inventory(LAB_INVENTORY)
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


if __name__ == "__main__":
    unittest.main()
