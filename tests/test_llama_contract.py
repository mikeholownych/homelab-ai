from __future__ import annotations

import json
from pathlib import Path
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


def load_yaml(relpath: str) -> object:
    return yaml.safe_load((REPO_ROOT / relpath).read_text(encoding="utf-8"))


def test_llama_cpp_commit_is_exact_sha():
    defaults = load_yaml("roles/llama_cpp_sycl/defaults/main.yml")
    commit = defaults["llama_cpp_sycl_git_commit"]
    assert len(commit) == 40
    assert all(c in "0123456789abcdefABCDEF" for c in commit)
    assert defaults["llama_cpp_sycl_install_enabled"] is False


def test_llama_cpp_cmake_sycl_options():
    defaults = load_yaml("roles/llama_cpp_sycl/defaults/main.yml")
    cmake_args = defaults["llama_cpp_sycl_cmake_args"]
    assert "-DGGML_SYCL=ON" in cmake_args
    assert any("INTEL" in arg.upper() or "SYCL" in arg.upper() for arg in cmake_args)


def test_llama_cpp_service_template_hardening():
    template = (REPO_ROOT / "roles/llama_cpp_sycl/templates/llama-server.service.j2").read_text()
    assert "Restart=on-failure" in template
    assert "ExecStart=" in template
    assert "LimitNOFILE=" in template
    assert "LimitMEMLOCK=" in template
    assert "EnvironmentFile=" in template


def test_llama_cpp_dual_gpu_validation_mandatory():
    defaults = load_yaml("roles/llama_cpp_sycl/defaults/main.yml")
    assert defaults["llama_cpp_sycl_dual_gpu_support_certified"] is False
    tasks = (REPO_ROOT / "roles/llama_cpp_sycl/tasks/main.yml").read_text()
    assert "tensor_split" in tasks or "split_mode" in tasks


def test_llama_cpp_validator_script_contract():
    validator = REPO_ROOT / "roles/llama_cpp_sycl/files/validate_llama.py"
    assert validator.exists()
    source = validator.read_text()
    assert "llama" in source
    assert "physical_acceptance" in source
    assert "PASS" in source
    assert "FAIL" in source
    assert "NOT_TESTED" in source
    assert "git_commit" in source


def test_llama_cpp_tasks_check_mode_aware():
    tasks = (REPO_ROOT / "roles/llama_cpp_sycl/tasks/main.yml").read_text()
    assert "ansible_check_mode" in tasks
    assert "ignore_errors" not in tasks
    assert "NOT_TESTED" in tasks


def test_llama_source_is_actually_built_from_pinned_commit():
    tasks = (REPO_ROOT / "roles/llama_cpp_sycl/tasks/main.yml").read_text()
    # Pinned clone
    assert "ansible.builtin.git:" in tasks
    assert "version: \"{{ llama_cpp_sycl_git_commit }}\"" in tasks
    # Configure with role-declared flags, then compile
    assert "llama_cpp_sycl_cmake_args }}" in tasks
    assert "--build" in tasks
    # Binary lands where the systemd unit expects it
    assert f"{REPO_ROOT.name}" not in tasks  # no accidental absolute repo refs
    assert "bin/llama-server" in tasks


def test_sycl_toolchain_absence_fails_closed_before_building():
    tasks = (REPO_ROOT / "roles/llama_cpp_sycl/tasks/main.yml").read_text()
    probe_pos = tasks.find("which\", \"icx")
    fail_pos = tasks.find("SYCL toolchain is absent")
    build_pos = tasks.find("Compile llama.cpp SYCL binaries")
    assert -1 < probe_pos < fail_pos < build_pos
    assert "unresolved vendor support decision" in tasks
