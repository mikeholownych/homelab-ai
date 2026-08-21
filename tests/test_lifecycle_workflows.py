from __future__ import annotations

import json
from pathlib import Path
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_yaml(relpath: str) -> object:
    return yaml.safe_load((REPO_ROOT / relpath).read_text(encoding="utf-8"))


def test_patching_policy_separates_routine_from_high_risk():
    policy = load_yaml("policies/patching.yml")
    assert "os_packages" in policy["routine_components"]
    assert "security_updates" in policy["routine_components"]
    high_risk = policy["high_risk_components"]
    assert {"kernel", "intel_gpu", "level_zero", "pytorch_xpu", "vllm", "llama_cpp", "firmware_bios"} <= set(high_risk.keys())
    for comp in high_risk.values():
        assert comp["auto_apply"] is False
        assert comp["approval"] == "manual"


def test_patch_playbook_structure_and_tags():
    content = (REPO_ROOT / "playbooks/patch.yml").read_text()
    assert "patch" in content
    assert "reboot" in content or "reboot-required" in content
    assert "validation" in content


def test_upgrade_playbook_requires_explicit_component_and_version():
    content = (REPO_ROOT / "playbooks/upgrade.yml").read_text()
    assert "upgrade_component" in content
    assert "upgrade_version" in content
    assert "validation" in content


def test_upgrade_policy_defines_current_candidate_previous():
    policy = load_yaml("policies/upgrades.yml")
    components = policy["lifecycle_components"]
    for name, spec in components.items():
        assert "current" in spec
        assert "candidate" in spec
        assert "previous_known_good" in spec
