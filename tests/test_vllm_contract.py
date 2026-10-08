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
    # Finding 2: validator stamps validation_ready_at into readiness evidence
    assert "--readiness-record" in source
    assert "stamp_readiness_record" in source
    assert "validation_ready_at" in source


def test_vllm_tasks_check_mode_aware_and_fail_closed():
    tasks = (REPO_ROOT / "roles/vllm_xpu/tasks/main.yml").read_text()
    assert "ansible_check_mode" in tasks
    assert "ignore_errors" not in tasks
    assert "NOT_TESTED" in tasks


def test_vllm_playbook_integration():
    site = (REPO_ROOT / "playbooks/site.yml").read_text()
    assert "vllm_xpu" in site
    assert "inference" in site


def test_container_launcher_is_real_and_digest_pinned():
    launcher = REPO_ROOT / "roles/vllm_xpu/files/vllm-xpu-runner.sh"
    assert launcher.exists()
    source = launcher.read_text()
    assert "@sha256:" in source  # refuses mutable tags at runtime
    assert "eval " not in source
    assert "serve --config" in source
    assert 'CONTAINER_NAME="${VLLM_CONTAINER_NAME:-vllm-xpu}"' in source
    assert '"$CONTAINER_NAME"' in source
    assert 'CONFIG_FILE="${VLLM_CONFIG_FILE:-$VLLM_CONFIG_DIR/vllm-config.yaml}"' in source
    assert 'ENV_FILE="${VLLM_ENV_FILE:-$VLLM_CONFIG_DIR/vllm.env}"' in source
    tasks = (REPO_ROOT / "roles/vllm_xpu/tasks/main.yml").read_text()
    assert "/usr/local/bin/vllm-xpu-runner" in tasks
    assert "image-ref" in tasks  # digest pin rendered to disk


def test_config_template_uses_cli_style_keys():
    template = (REPO_ROOT / "roles/vllm_xpu/templates/vllm-config.yaml.j2").read_text()
    for key in ("tensor-parallel-size", "gpu-memory-utilization", "max-model-len", "enforce-eager"):
        assert key in template, f"missing CLI-style key {key}"
    # vLLM config keys are CLI-style; underscore variants would be silently ignored.
    for bad in ("tensor_parallel_size:", "gpu_memory_utilization:", "max_model_len:"):
        assert f"{bad}" not in template


def test_container_mode_requires_runtime_role():
    tasks = (REPO_ROOT / "roles/vllm_xpu/tasks/main.yml").read_text()
    assert "container_runtime_enabled | bool" in tasks

def test_vllm_runner_recovery_record_reflects_restart_provenance():
    runner = (REPO_ROOT / "roles/vllm_xpu/files/vllm-xpu-runner.sh").read_text()
    assert "restart_count_source" in runner
    assert "service_invocation_id" in runner
    assert "systemd:NRestarts" in runner
    rec_tasks = (REPO_ROOT / "roles/vllm_xpu/tasks/main.yml").read_text()
    assert "restart_count_source" in rec_tasks


def test_vllm_env_carries_readiness_and_expected_model():
    env_tpl = (REPO_ROOT / "roles/vllm_xpu/templates/vllm.env.j2").read_text()
    assert "READINESS_RECORD=" in env_tpl
    assert "VLLM_XPU_EXPECTED_MODEL=" in env_tpl
    assert "VLLM_READINESS_POLL_SECS=" in env_tpl
    assert "VLLM_READINESS_TIMEOUT_SECS=" in env_tpl
    defaults = load_yaml("roles/vllm_xpu/defaults/main.yml")
    assert defaults["vllm_xpu_readiness_record"].endswith("/vllm_readiness.json")
    assert defaults["vllm_xpu_readiness_probe"].endswith("/local-ai-vllm-readiness")


def test_vllm_tasks_invoke_validator_with_readiness_record():
    tasks = (REPO_ROOT / "roles/vllm_xpu/tasks/main.yml").read_text()
    assert "--readiness-record" in tasks
    assert "vllm_xpu_readiness_record" in tasks

def test_ai5820_vllm_is_retired_and_loopback_bound():
    hostvars = load_yaml("inventory/production/host_vars/ai-5820-01.yml")
    assert isinstance(hostvars, dict)
    assert hostvars["vllm_xpu_host"] == "127.0.0.1"
    assert hostvars["vllm_xpu_install_enabled"] is False
    assert hostvars["vllm_xpu_service_enabled"] is False
    assert hostvars["vllm_xpu_api_key_required"] is True
    tasks = (REPO_ROOT / "roles/vllm_xpu/tasks/main.yml").read_text()
    assert "vllm_xpu_api_key_required" in tasks
    template = (REPO_ROOT / "roles/vllm_xpu/templates/vllm-config.yaml.j2").read_text()
    assert "api-key:" in template
    assert "vllm_xpu_api_key" in template
