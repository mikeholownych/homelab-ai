import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
COLLECTOR_PATH = ROOT / "roles/hardware_inventory/files/collect_hardware.py"

ROCMINFO_STRIX_HALO = """\
ROCk module version 6.14.14 is loaded
=====================
HSA System Attributes
=====================
Runtime Version:         1.18
==========
HSA Agents
==========
*******
Agent 1
*******
  Name:                    AMD RYZEN AI MAX+ 395 w/ Radeon 8060S
  Uuid:                    CPU-XX
  Marketing Name:          AMD RYZEN AI MAX+ 395 w/ Radeon 8060S
  Vendor Name:             CPU
  Device Type:             CPU
  Pool Info:
    Pool 1
      Segment:                 GLOBAL; FLAGS: FINE GRAINED
      Size:                    64288768(0x3d4f000) KB
    Pool 2
      Segment:                 GLOBAL; FLAGS: EXTENDED FINE GRAINED
      Size:                    64288768(0x3d4f000) KB
*******
Agent 2
*******
  Name:                    gfx1151
  Uuid:                    GPU-XX
  Marketing Name:          AMD Radeon Graphics
  Vendor Name:             AMD
  Device Type:             GPU
  Pool Info:
    Pool 1
      Segment:                 GLOBAL; FLAGS: COARSE GRAINED
      Size:                    64288768(0x3d4f000) KB
    Pool 2
      Segment:                 GROUP
      Size:                    64(0x40) KB
*******
Agent 3
*******
  Name:                    aie2p
  Uuid:                    AIE-XX
  Marketing Name:          RyzenAI-npu5
  Vendor Name:             AMD
  Device Type:             DSP
  Pool Info:
    Pool 1
      Segment:                 GLOBAL; FLAGS: KERNARG, COARSE GRAINED
      Size:                    65536(0x10000) KB
*** Done ***
"""

PROC_MODULES = (
    "amdgpu 20000000 45 - Live 0x0000000000000000\n"
    "amdxdna 143360 0 - Live 0x0000000000000000\n"
)


def load_collector():
    spec = importlib.util.spec_from_file_location("collect_hardware", COLLECTOR_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_run(outputs):
    def _run(command, required=True):
        return outputs.get(command[0], "")
    return _run


def test_strix_halo_rocm_agents_and_npu_collected(tmp_path):
    collector = load_collector()
    modules = tmp_path / "modules"
    modules.write_text(PROC_MODULES)
    node = tmp_path / "accel0"
    node.touch()

    result = collector.collect_amd_observations(
        run_fn=fake_run({"rocminfo": ROCMINFO_STRIX_HALO}),
        proc_modules=modules,
        device_node=str(node),
    )

    agents = {a["name"]: a for a in result["rocm"]["agents"]}
    assert [a["name"] for a in result["rocm"]["agents"]] == [
        "AMD RYZEN AI MAX+ 395 w/ Radeon 8060S", "gfx1151", "aie2p"]
    assert agents["gfx1151"]["device_type"] == "GPU"
    assert agents["gfx1151"]["memory_gib"] == 61.3
    assert agents["gfx1151"]["marketing_name"] == "AMD Radeon Graphics"
    assert agents["aie2p"]["device_type"] == "DSP"
    assert "memory_gib" not in agents["aie2p"]
    assert agents["aie2p"]["marketing_name"] == "RyzenAI-npu5"
    assert agents["AMD RYZEN AI MAX+ 395 w/ Radeon 8060S"]["device_type"] == "CPU"
    assert result["npu"] == {
        "kernel_module_loaded": True,
        "device_node": str(node),
        "device_node_exists": True,
    }


def test_npu_module_falls_back_to_lsmod_and_missing_node(tmp_path):
    collector = load_collector()
    result = collector.collect_amd_observations(
        run_fn=fake_run({
            "rocminfo": ROCMINFO_STRIX_HALO,
            "lsmod": "Module Size Used by\namdxdna 143360 0\n",
        }),
        proc_modules=tmp_path / "missing_modules",
        device_node=str(tmp_path / "no_accel"),
    )
    assert result["npu"]["kernel_module_loaded"] is True
    assert result["npu"]["device_node_exists"] is False


def test_nothing_added_when_rocm_and_npu_absent(tmp_path):
    collector = load_collector()
    result = collector.collect_amd_observations(
        run_fn=fake_run({"lsmod": "Module Size Used by\nxe 1 0\n"}),
        proc_modules=tmp_path / "missing_modules",
        device_node=str(tmp_path / "no_accel"),
    )
    assert result == {}


def test_parse_rocminfo_empty_text():
    assert load_collector().parse_rocminfo("") == []
