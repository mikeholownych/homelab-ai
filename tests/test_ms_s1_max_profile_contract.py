from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_ms_s1_max_hardware_profile_shape():
    profile = yaml.safe_load(
        (ROOT / "profiles/hardware/ms_s1_max_strix_halo.yml").read_text()
    )
    assert profile["profile_name"] == "ms_s1_max_strix_halo"
    assert profile["compute_evidence_backend"] == "rocm"
    assert profile["gpu"]["count_expected"] == 1
    assert profile["gpu"]["approved_pci_devices"][0]["vendor_id"] == "1002"
    assert profile["gpu"]["approved_pci_devices"][0]["device_id"] in ("1586", "0x1586")
    assert profile["gpu"]["expected_models"][0]["memory_gib"]["approximate"] == 61
    assert profile["npu"]["required"] is True
    assert profile["npu"]["hsa_name"] == "aie2p"
    assert profile["firmware"]["resizable_bar"]["required"] is False
    assert profile["firmware"]["above_4g_decoding"]["required"] is False