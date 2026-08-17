import importlib.util
import json
from pathlib import Path

import pytest
import subprocess
import yaml


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "roles/hardware_validation/files/classify_hardware.py"


def load_classifier():
    spec = importlib.util.spec_from_file_location("classify_hardware", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("fixture", "status", "rule"),
    [
        ("healthy", "pass", None),
        ("gpu_count", "blocking", "gpu_count"),
        ("rebar_missing", "blocking", "resizable_bar_enabled"),
        ("level_zero_missing", "blocking", "level_zero_detected"),
        ("pcie_degraded", "blocking", "pcie_link_health"),
    ],
)
def test_fixture_classification(fixture, status, rule):
    classifier = load_classifier()
    profile = yaml.safe_load((ROOT / "profiles/hardware/p620_dual_b65.yml").read_text())
    observed = json.loads((ROOT / f"tests/fixtures/hardware/{fixture}.json").read_text())
    result = classifier.classify(profile, observed)
    assert result["simulated"] is True
    assert result["physical_acceptance"] is False
    assert result["status"] == status
    if rule:
        assert any(c["rule"] == rule and c["severity"] == "blocking" for c in result["checks"])


def test_width_uses_physical_slot_capability():
    classifier = load_classifier()
    profile = yaml.safe_load((ROOT / "profiles/hardware/p620_dual_b65.yml").read_text())
    observed = json.loads((ROOT / "tests/fixtures/hardware/healthy.json").read_text())
    observed["pci"][0].update({"slot_width": 8, "current_width": 8})
    result = classifier.classify(profile, observed)
    assert not any(c["rule"] == "pcie_link_health" and c["severity"] == "blocking" for c in result["checks"])


def test_unknown_psu_is_informational():
    classifier = load_classifier()
    profile = yaml.safe_load((ROOT / "profiles/hardware/p620_dual_b65.yml").read_text())
    observed = json.loads((ROOT / "tests/fixtures/hardware/healthy.json").read_text())
    observed["power_supplies"] = []
    result = classifier.classify(profile, observed)
    assert any(c["rule"] == "psu_inventory" and c["severity"] == "informational" for c in result["checks"])


def test_role_commands_are_read_only_and_never_report_changed():
    tasks = yaml.safe_load((ROOT / "roles/hardware_inventory/tasks/main.yml").read_text())
    command_tasks = [task for task in tasks if "ansible.builtin.command" in task]
    assert command_tasks
    assert all(task.get("changed_when") is False for task in command_tasks)
    assert all("ignore_errors" not in task for task in command_tasks)


def test_classifier_writes_required_machine_readable_evidence(tmp_path):
    profile = yaml.safe_load((ROOT / "profiles/hardware/p620_dual_b65.yml").read_text())
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(profile))
    result = subprocess.run(
        [str(MODULE_PATH), "--profile", str(profile_path), "--observed",
         str(ROOT / "tests/fixtures/hardware/healthy.json"), "--output-dir", str(tmp_path)],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0
    for name in ("hardware.json", "pci.json", "memory.json", "storage.json", "firmware.json"):
        document = json.loads((tmp_path / name).read_text())
        assert document["simulated"] is True
        assert "expected" in document and "observed" in document
        assert {"severity", "status", "rationale"} <= document.keys()


def test_collector_has_no_simulation_mode_and_requires_core_sources():
    source = (ROOT / "roles/hardware_inventory/files/collect_hardware.py").read_text()
    assert "argparse" not in source
    for command in ("lspci", "lsblk", "ip"):
        assert f'["{command}"' in source
    assert '"simulated": False' in source
