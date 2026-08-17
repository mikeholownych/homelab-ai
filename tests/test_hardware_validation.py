import importlib.util
import json
from pathlib import Path

import pytest
import subprocess
import yaml


ROOT = Path(__file__).parents[1]
MODULE_PATH = ROOT / "roles/hardware_validation/files/classify_hardware.py"
COLLECTOR_PATH = ROOT / "roles/hardware_inventory/files/collect_hardware.py"


def load_classifier():
    spec = importlib.util.spec_from_file_location("classify_hardware", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_collector():
    spec = importlib.util.spec_from_file_location("collect_hardware", COLLECTOR_PATH)
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
        ("gpu_model", "blocking", "gpu_model_match"),
        ("vram_mismatch", "blocking", "gpu_memory"),
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


def test_realistic_lspci_parser_uses_explicit_link_fields_and_slot_width():
    collector = load_collector()
    pci = collector.parse_lspci(
        (ROOT / "tests/fixtures/hardware/lspci_b65.txt").read_text(),
        (ROOT / "tests/fixtures/hardware/dmidecode_slots.txt").read_text(),
    )
    assert pci[0] == {
        "bdf": "0000:41:00.0", "vendor_id": "8086", "device_id": "e222",
        "device_max_generation": 5, "device_max_width": 16,
        "current_generation": 4, "current_width": 16, "slot_width": 16,
        "bar_sizes_gib": [32.0], "rebar_enabled": True,
    }
    assert pci[1]["slot_width"] == 8
    assert pci[1]["current_width"] == 8


def test_realistic_level_zero_parser_reports_bdf_and_vram_not_bar():
    collector = load_collector()
    devices = collector.parse_level_zero((ROOT / "tests/fixtures/hardware/zeinfo_b65.json").read_text())
    assert [item["bdf"] for item in devices] == ["0000:41:00.0", "0000:61:00.0"]
    assert all(item["memory_gib"] == 32 for item in devices)
    assert all(item["memory_source"] == "level_zero_global_memory" for item in devices)


def test_unknown_vram_and_unbound_level_zero_cannot_pass():
    classifier = load_classifier()
    profile = yaml.safe_load((ROOT / "profiles/hardware/p620_dual_b65.yml").read_text())
    observed = json.loads((ROOT / "tests/fixtures/hardware/healthy.json").read_text())
    observed["level_zero_devices"][0]["memory_gib"] = None
    observed["level_zero_devices"][1]["bdf"] = "0000:ff:00.0"
    result = classifier.classify(profile, observed)
    assert result["status"] == "blocking"
    assert result["physical_acceptance"] is False


def test_above4g_unknown_is_not_tested_not_inferred_from_bar():
    classifier = load_classifier()
    profile = yaml.safe_load((ROOT / "profiles/hardware/p620_dual_b65.yml").read_text())
    observed = json.loads((ROOT / "tests/fixtures/hardware/healthy.json").read_text())
    observed["firmware"]["above_4g_decoding"] = {"value": None, "source": "not exposed", "confidence": "unknown"}
    result = classifier.classify(profile, observed)
    check = next(item for item in result["checks"] if item["rule"] == "above_4g_decoding_enabled")
    assert check["status"] == "not_tested"
    assert result["physical_acceptance"] is False


def test_gen3_blocks_even_if_device_claims_gen3_maximum():
    classifier = load_classifier()
    profile = yaml.safe_load((ROOT / "profiles/hardware/p620_dual_b65.yml").read_text())
    observed = json.loads((ROOT / "tests/fixtures/hardware/healthy.json").read_text())
    observed["pci"][0].update({"device_max_generation": 3, "current_generation": 3})
    result = classifier.classify(profile, observed)
    check = next(item for item in result["checks"] if item["rule"] == "pcie_link_health")
    assert check["status"] == "fail"
    assert check["severity"] == "blocking"


def test_gpu_identity_must_bind_to_same_pci_bdf():
    classifier = load_classifier()
    profile = yaml.safe_load((ROOT / "profiles/hardware/p620_dual_b65.yml").read_text())
    observed = json.loads((ROOT / "tests/fixtures/hardware/healthy.json").read_text())
    observed["pci"][1]["device_id"] = "ffff"
    result = classifier.classify(profile, observed)
    check = next(item for item in result["checks"] if item["rule"] == "gpu_model_match")
    assert check["status"] == "fail"


def test_successful_live_observation_still_does_not_grant_commissioning_acceptance():
    classifier = load_classifier()
    profile = yaml.safe_load((ROOT / "profiles/hardware/p620_dual_b65.yml").read_text())
    observed = json.loads((ROOT / "tests/fixtures/hardware/healthy.json").read_text())
    observed["simulated"] = False
    result = classifier.classify(profile, observed)
    assert result["status"] == "pass"
    assert result["physical_acceptance"] is False
