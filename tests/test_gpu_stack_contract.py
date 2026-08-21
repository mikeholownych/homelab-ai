import importlib.util
import json
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).parents[1]
VALIDATOR = ROOT / "roles/pytorch_xpu/files/validate_xpu.py"


def load_yaml(path):
    return yaml.safe_load((ROOT / path).read_text())


def test_b65_on_ubuntu_2404_is_gated_on_official_omix_prerequisites():
    defaults = load_yaml("roles/intel_gpu/defaults/main.yml")
    assert defaults["intel_gpu_target_pci_ids"] == ["8086:e222"]
    assert defaults["intel_gpu_minimum_ubuntu_point_release"] == "24.04.4"
    assert defaults["intel_gpu_minimum_kernel"] == "6.17"
    assert defaults["intel_gpu_install_enabled"] is False
    assert "Ubuntu Desktop 24.04.4" in defaults["intel_gpu_support_blocker"]


def test_unresolved_host_stack_has_no_partial_apt_installation():
    tasks = (ROOT / "roles/intel_gpu/tasks/main.yml").read_text()
    assert "apt_repository" not in tasks
    assert "intel-omix=" not in tasks


def test_vendor_support_conflict_is_unconditionally_fail_closed():
    defaults = load_yaml("roles/intel_gpu/defaults/main.yml")
    assert defaults["intel_gpu_stack_status"] == "unresolved_vendor_support_conflict"
    tasks = load_yaml("roles/intel_gpu/tasks/main.yml")
    first = tasks[0]
    assert "ansible.builtin.fail" in first
    assert "compatibility_set_approved" not in json.dumps(defaults)


def test_gpu_role_enforces_devices_access_and_physical_checks():
    tasks = (ROOT / "roles/intel_gpu/tasks/main.yml").read_text()
    for contract in ("intel_gpu_expected_count", "intel_gpu_target_pci_ids", "hardware_inventory",
                     "hardware_validation"):
        assert contract in tasks
    assert "ignore_errors" not in tasks


def test_pytorch_wheel_and_python_are_pinned_by_hash():
    defaults = load_yaml("roles/pytorch_xpu/defaults/main.yml")
    assert defaults["pytorch_xpu_python_version"] == "3.12"
    assert defaults["pytorch_xpu_version"] == "2.12.1+xpu"
    assert defaults["pytorch_xpu_wheel_url"].startswith("https://download-r2.pytorch.org/whl/xpu/")
    assert len(defaults["pytorch_xpu_wheel_sha256"]) == 64
    assert "latest" not in json.dumps(defaults).lower()
    lock = (ROOT / "roles/pytorch_xpu/files/requirements-xpu-py312.lock").read_text()
    assert "torch==2.12.1+xpu --hash=sha256:" in lock
    assert len([line for line in lock.splitlines() if "==" in line]) >= 30
    assert "--require-hashes" in (ROOT / "roles/pytorch_xpu/tasks/main.yml").read_text()
    assert "dependency_lock_approved" not in json.dumps(defaults)


def test_pytorch_role_promotes_current_only_after_validation():
    tasks = load_yaml("roles/pytorch_xpu/tasks/main.yml")
    names = [task["name"] for task in tasks]
    validate_at = next(i for i, name in enumerate(names) if "Validate every XPU" in name)
    promote_at = next(i for i, name in enumerate(names) if "Promote validated" in name)
    assert validate_at < promote_at
    assert "pytorch_xpu_promoter" in json.dumps(tasks[promote_at])
    assert "promote_venv.py" in json.dumps(tasks)
    assert "runtime.json" in json.dumps(tasks)


def test_validator_runs_real_per_device_math_and_emits_fail_closed_json(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("validate_xpu", VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class Tensor:
        def __init__(self, value):
            self.value = value

        def __add__(self, other):
            return Tensor(self.value + other.value)

        def item(self):
            return self.value

    class Props:
        name = "Intel Arc Pro B65"
        total_memory = 32 * 1024**3

    class XPU:
        @staticmethod
        def is_available(): return True

        @staticmethod
        def device_count(): return 2

        @staticmethod
        def get_device_properties(_index): return Props()

        @staticmethod
        def synchronize(_index): return None

    class Torch:
        __version__ = "test"
        xpu = XPU()

        @staticmethod
        def tensor(value, device):
            assert device in ("xpu:0", "xpu:1")
            return Tensor(value)

    output = tmp_path / "runtime.json"
    result = module.validate(Torch(), expected_count=2)
    module.write_result(output, result)
    assert result["status"] == "PASS"
    assert [device["tensor_result"] for device in result["devices"]] == [3.0, 3.0]
    assert json.loads(output.read_text())["physical_acceptance"] is False


def test_validator_serializes_torch_import_failure():
    source = VALIDATOR.read_text()
    assert "except ImportError as exc:" in source
    assert '"torch import failed"' in source


def test_container_runtime_is_opt_in_and_maps_dri_only():
    defaults = load_yaml("roles/container_runtime/defaults/main.yml")
    assert defaults["container_runtime_enabled"] is False
    assert defaults["container_runtime_device_mappings"] == ["/dev/dri:/dev/dri"]
    tasks = (ROOT / "roles/container_runtime/tasks/main.yml").read_text()
    assert "/etc/cdi/local-ai-dri.yaml" in tasks
    assert defaults["container_runtime_render_nodes"] == ["/dev/dri/renderD128", "/dev/dri/renderD129"]


def test_gpu_validation_reuses_bdf_correlated_hardware_roles():
    tasks = (ROOT / "roles/intel_gpu/tasks/main.yml").read_text()
    assert "name: hardware_inventory" in tasks
    assert "name: hardware_validation" in tasks
    assert "regex_findall" not in tasks
    collector = (ROOT / "roles/hardware_inventory/files/collect_hardware.py").read_text()
    assert '"runtime_versions"' in collector
    assert '"kernel_driver"' in collector
    assert '"level_zero_packages"' in collector


def test_atomic_promoter_preserves_previous_and_uses_replace(tmp_path):
    path = ROOT / "roles/pytorch_xpu/files/promote_venv.py"
    spec = importlib.util.spec_from_file_location("promote_venv", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir(); new.mkdir()
    current, previous = tmp_path / "current", tmp_path / "previous"
    current.symlink_to(old)
    assert module.promote(new, current, previous) is True
    assert current.resolve() == new
    assert previous.resolve() == old
    assert module.promote(new, current, previous) is False
    assert previous.resolve() == old


def test_xpu_validation_schema_accepts_validator_output():
    import jsonschema
    schema = json.loads((ROOT / "schemas/xpu-validation.schema.json").read_text())
    document = {"schema_version": "1.0.0", "status": "NOT_TESTED", "physical_acceptance": False,
                "expected_count": 2, "observed_count": 0, "devices": [], "reason": "no physical hardware"}
    jsonschema.validate(document, schema)


def test_check_mode_has_explicit_skip_semantics():
    tasks = (ROOT / "roles/pytorch_xpu/tasks/main.yml").read_text()
    assert "ansible_check_mode" in tasks
    assert "NOT_TESTED" in tasks


def test_gpu_playbook_tags_select_work_without_defining_identity():
    site = (ROOT / "playbooks/site.yml").read_text()
    assert "name: intel_gpu" in site
    assert "name: pytorch_xpu" in site
    assert "capabilities.gpu" in site
    assert "gpu" in site and "runtime" in site


def test_primary_source_provenance_is_recorded():
    doc = (ROOT / "docs/intel-gpu.md").read_text()
    for url in (
        "https://dgpu-docs.intel.com/overview/supported-hardware/xe-driver-gpus.html",
        "https://github.com/intel/compute-runtime/releases/tag/26.27.39122.11",
        "https://docs.pytorch.org/docs/stable/notes/get_start_xpu.html",
        "https://download.pytorch.org/whl/xpu/torch/",
    ):
        assert url in doc
    assert "2026-08-17" in doc
    assert "NOT_TESTED" in doc
