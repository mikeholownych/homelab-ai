from __future__ import annotations

import json
from pathlib import Path
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_yaml(relpath: str) -> object:
    return yaml.safe_load((REPO_ROOT / relpath).read_text(encoding="utf-8"))


def test_vllm_version_and_image_pinned_without_latest():
    defaults = load_yaml("roles/vllm_xpu/defaults/main.yml")
    assert defaults["vllm_xpu_version"] == "0.7.3"
    assert "latest" not in defaults["vllm_xpu_container_tag"].lower()
    assert defaults["vllm_xpu_container_digest"].startswith("sha256:")
    assert len(defaults["vllm_xpu_container_digest"]) == 71
    assert defaults["vllm_xpu_install_enabled"] is False


def test_vllm_profiles_support_single_and_dual_gpu():
    defaults = load_yaml("roles/vllm_xpu/defaults/main.yml")
    profiles = defaults["vllm_xpu_profiles"]
    assert "small" in profiles
    assert "large" in profiles
    assert profiles["small"]["tensor_parallel_size"] == 1
    assert profiles["large"]["tensor_parallel_size"] == 2
    assert defaults["vllm_xpu_active_profile"] in ("small", "large")


def test_vllm_service_configuration_separated_from_secrets():
    tasks = (REPO_ROOT / "roles/vllm_xpu/tasks/main.yml").read_text()
    assert "vllm-config.yaml" in tasks
    assert "vllm.env" in tasks
    defaults_dump = json.dumps(load_yaml("roles/vllm_xpu/defaults/main.yml"))
    assert "secret/local-ai/services" in defaults_dump


def test_vllm_systemd_service_hardening():
    template = (REPO_ROOT / "roles/vllm_xpu/templates/vllm.service.j2").read_text()
    assert "Restart=on-failure" in template
    assert "EnvironmentFile=" in template
    assert "ExecStart=" in template
    assert "LimitNOFILE=" in template
    assert "LimitMEMLOCK=" in template
    assert "TimeoutStopSec=" in template


def test_vllm_validator_script_contract():
    validator = REPO_ROOT / "roles/vllm_xpu/files/validate_vllm.py"
    assert validator.exists()
    source = validator.read_text()
    assert "/health" in source
    assert "/v1/models" in source
    assert "/v1/chat/completions" in source or "/v1/completions" in source
    assert "tensor_parallel_size" in source
    assert "physical_acceptance" in source
    assert "PASS" in source
    assert "FAIL" in source
    assert "NOT_TESTED" in source


def test_vllm_tasks_check_mode_aware_and_fail_closed():
    tasks = (REPO_ROOT / "roles/vllm_xpu/tasks/main.yml").read_text()
    assert "ansible_check_mode" in tasks
    assert "ignore_errors" not in tasks
    assert "NOT_TESTED" in tasks


def test_vllm_playbook_integration():
    site = (REPO_ROOT / "playbooks/site.yml").read_text()
    assert "vllm_xpu" in site
    assert "inference" in site
