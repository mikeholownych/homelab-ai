from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(path: str):
    return yaml.safe_load((ROOT / path).read_text())


def test_rocm_defaults_are_fail_closed_and_pinned():
    d = load("roles/rocm/defaults/main.yml")
    assert d["rocm_install_enabled"] is False
    assert d["rocm_release"] == "7.2.0"
    assert d["rocm_apt_suite"] == "noble"
    assert d["rocm_signing_key_sha256"] == (
        "3e660bdc559b34781b5498e79b9c117394b46ce55592812db0b84d65986b4df2"
    )
    assert d["rocm_signing_key_fingerprint"] == "CA8BBB4727A47B4D09B4EE8969386B48A1A693C5C"
    assert d["rocm_packages"]["rocm-core"] == "7.2.0.70200-43~24.04"
    assert d["rocm_packages"]["rocminfo"] == "1.0.0.70200-43~24.04"
    assert d["rocm_expected_gpu_agent"] == "gfx1151"
    assert d["rocm_expected_npu_agent"] == "aie2p"
    assert "latest" not in d["rocm_repository_urls"]["rocm"]