from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

ROLE_DIR = REPO_ROOT / "roles" / "model_registry"


def load_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_filters():
    spec = importlib.util.spec_from_file_location(
        "aihost_validators_under_test", REPO_ROOT / "filter_plugins" / "aihost_validators.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module.FilterModule().filters()


class ModelRegistryStructureTests(unittest.TestCase):
    REQUIRED_ROLE_FILES = (
        "defaults/main.yml",
        "tasks/main.yml",
        "tasks/materialize.yml",
        "tasks/download_model.yml",
        "tasks/disk_budget.yml",
        "tasks/gc.yml",
        "tasks/prune_model_revisions.yml",
        "tasks/evidence.yml",
        "handlers/main.yml",
        "meta/main.yml",
    )

    def test_role_files_present(self) -> None:
        for relative in self.REQUIRED_ROLE_FILES:
            self.assertTrue((ROLE_DIR / relative).exists(), relative)

    def test_role_defaults_are_safe(self) -> None:
        defaults = load_yaml(ROLE_DIR / "defaults" / "main.yml")
        self.assertFalse(defaults["model_registry_enabled"])
        self.assertEqual({}, defaults["model_registry_models"])
        self.assertGreater(defaults["model_registry_min_free_disk_gib"], 0)
        self.assertGreaterEqual(defaults["model_registry_keep_revisions_per_model"], 1)
        # Undeclared caches are never touched without an explicit operator flag.
        self.assertFalse(defaults["model_registry_prune_undeclared"])

    def test_role_tasks_avoid_shell_module_and_blanket_ignore_errors(self) -> None:
        for path in sorted((ROLE_DIR / "tasks").glob("*.yml")):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("ansible.builtin.shell:", text, path.name)
            self.assertNotIn("ignore_errors", text, path.name)
            self.assertNotIn("state: latest", text, path.name)

    def test_downloads_enforce_checksums_via_native_module(self) -> None:
        text = (ROLE_DIR / "tasks" / "download_model.yml").read_text(encoding="utf-8")
        self.assertIn("get_url:", text)
        self.assertIn("checksum: \"sha256:{{ artifact.sha256 }}\"", text)
        # No curl|sh patterns anywhere in the role.
        for path in sorted((ROLE_DIR / "tasks").glob("*.yml")):
            role_text = path.read_text(encoding="utf-8")
            self.assertNotIn("curl", role_text, path.name)


class ModelStampFilterTests(unittest.TestCase):
    def test_stamp_is_stable_and_hash_sensitive(self) -> None:
        filters = load_filters()
        model = {
            "repo_id": "org/model",
            "revision": "v1",
            "artifacts": [
                {"path": "b.safetensors", "sha256": "b" * 64},
                {"path": "a.json", "sha256": "a" * 64},
            ],
        }
        stamp_one = filters["aihost_model_stamp"](model)
        stamp_two = filters["aihost_model_stamp"]({**model, "artifacts": list(reversed(model["artifacts"]))})
        self.assertEqual(stamp_one, stamp_two, "artifact order must not change the stamp")
        changed = {**model, "revision": "v2"}
        self.assertNotEqual(stamp_one, filters["aihost_model_stamp"](changed))
        self.assertEqual(stamp_one.count("|"), 2)

    def test_stamp_changes_when_any_artifact_hash_changes(self) -> None:
        filters = load_filters()
        model = {"repo_id": "o/m", "revision": "r", "artifacts": [{"sha256": "a" * 64}]}
        tampered = {"repo_id": "o/m", "revision": "r", "artifacts": [{"sha256": "f" * 64}]}
        self.assertNotEqual(filters["aihost_model_stamp"](model), filters["aihost_model_stamp"](tampered))


class ModelRegistryIntegrationTests(unittest.TestCase):
    def test_site_playbook_includes_models_before_runtime_roles(self) -> None:
        site = (REPO_ROOT / "playbooks/site.yml").read_text(encoding="utf-8")
        models_position = site.find("name: model_registry")
        vllm_position = site.find("name: vllm_xpu")
        self.assertGreater(models_position, -1)
        self.assertGreater(vllm_position, models_position)

    def test_host_feature_flag_defaults_off_until_models_are_declared(self) -> None:
        host_vars = load_yaml(REPO_ROOT / "inventory/production/host_vars/ai-p620-01.yml")
        self.assertFalse(host_vars["features"]["model_registry"])

    def test_disk_budget_refuses_without_headroom(self) -> None:
        budget = (ROLE_DIR / "tasks" / "disk_budget.yml").read_text(encoding="utf-8")
        self.assertIn("model_registry_min_free_disk_gib", budget)
        self.assertIn("model_registry_declared_demand_gib", budget)


if __name__ == "__main__":
    unittest.main()
