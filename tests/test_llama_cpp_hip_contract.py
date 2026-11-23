"""Phase 3b contract: the HIP worker may leave loopback only with a per-worker API key."""
import shutil
import subprocess
import textwrap
from pathlib import Path

import jinja2
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/llama_cpp_hip"
ANSIBLE_PLAYBOOK = ROOT / ".venv/bin/ansible-playbook"

WORKER = {
    "service_name": "llama-hip-test.service",
    "container_name": "llama-hip-test",
    "served_name": "test-model",
    "port": 8101,
    "context": 4096,
    "model_file": "m.gguf",
}


def load(path: str):
    return yaml.safe_load((ROOT / path).read_text())


def render_unit(**overrides) -> str:
    variables = {
        "llama_cpp_hip_uid": 999,
        "llama_cpp_hip_user": "aihost-runtime",
        "llama_cpp_hip_home": "/var/lib/aihost-runtime",
        "llama_cpp_hip_storage_root": "/var/lib/local-ai/podman-aihost-runtime",
        "llama_cpp_hip_model_dir": "/var/lib/local-ai/models/gguf",
        "llama_cpp_hip_image": "ghcr.io/ggml-org/llama.cpp",
        "llama_cpp_hip_digest": "sha256:" + "0" * 64,
        "llama_cpp_hip_host": "127.0.0.1",
        "llama_cpp_hip_default_args": ["-ngl", "99"],
        "llama_cpp_hip_config_root": "/etc/local-ai/llama-hip",
        "llama_cpp_hip_api_key_required": False,
        "llama_worker": WORKER,
        "llama_worker_key": "qwen",
    }
    variables.update(overrides)
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.filters["bool"] = bool
    return env.from_string((ROLE / "templates/llama-hip.service.j2").read_text()).render(**variables)


def test_api_key_is_off_by_default_and_key_file_lives_under_hip_config_root():
    defaults = load("roles/llama_cpp_hip/defaults/main.yml")
    assert defaults["llama_cpp_hip_api_key_required"] is False
    assert defaults["llama_cpp_hip_host"] == "127.0.0.1"
    assert defaults["llama_cpp_hip_config_root"] == "/etc/local-ai/llama-hip"


def test_unit_passes_api_key_file_only_when_required():
    open_unit = render_unit()
    assert "--api-key-file" not in open_unit
    assert "worker-api-key" not in open_unit

    keyed = render_unit(llama_cpp_hip_api_key_required=True, llama_cpp_hip_host="10.0.8.6")
    assert "--api-key-file /cfg/api-key" in keyed
    assert "-v /etc/local-ai/llama-hip/qwen/worker-api-key:/cfg/api-key:ro" in keyed
    assert "--host 10.0.8.6 --port 8101" in keyed
    # The key itself must never be rendered into a world-readable unit file.
    assert "--api-key " not in keyed


def test_key_files_are_private_per_worker_and_generated_once():
    tasks = (ROLE / "tasks/main.yml").read_text()
    assert "{{ llama_cpp_hip_config_root }}/{{ item.key }}/worker-api-key" in tasks
    assert 'mode: "0400"' in tasks
    assert "lookup('ansible.builtin.password', '/dev/null" in tasks
    assert tasks.count("no_log: true") >= 3
    # Every key task is gated on the flag.
    for task in yaml.safe_load(tasks):
        if "worker-api-key" in yaml.safe_dump(task) and "slurp" in yaml.safe_dump(task):
            assert "llama_cpp_hip_api_key_required | bool" in task["when"]


def test_health_check_authenticates_with_bearer_when_key_required():
    tasks = (ROLE / "tasks/start_worker.yml").read_text()
    assert "'Authorization': 'Bearer '" in tasks
    assert "worker-api-key" in tasks
    assert "no_log" in tasks


def _assert_task() -> dict:
    task = yaml.safe_load((ROLE / "tasks/main.yml").read_text())[0]
    assert "ansible.builtin.assert" in task
    return {"name": "bind guard", "ansible.builtin.assert": task["ansible.builtin.assert"], "when": task["when"]}


def _run_guard(tmp_path: Path, host: str, key_required) -> subprocess.CompletedProcess:
    playbook = [{
        "hosts": "localhost",
        "connection": "local",
        "gather_facts": False,
        "vars": {
            "llama_cpp_hip_enabled": True,
            "llama_cpp_hip_digest": "sha256:" + "0" * 64,
            "llama_cpp_hip_workers": {"w": WORKER},
            "llama_cpp_hip_drain_via_gateway": False,
            "llama_cpp_hip_host": host,
            "llama_cpp_hip_api_key_required": key_required,
        },
        "tasks": [_assert_task()],
    }]
    path = tmp_path / "guard.yml"
    path.write_text(yaml.safe_dump(playbook))
    return subprocess.run(
        [str(ANSIBLE_PLAYBOOK), "-i", "localhost,", str(path)],
        capture_output=True, text=True, cwd=tmp_path, check=False,
    )


@pytest.mark.skipif(not ANSIBLE_PLAYBOOK.exists(), reason="ansible not bootstrapped (.venv)")
@pytest.mark.parametrize(
    ("host", "key_required", "ok"),
    [
        ("127.0.0.1", False, True),    # lab default
        ("10.0.8.6", False, False),    # unauthenticated LAN bind is forbidden
        ("0.0.0.0", False, False),     # so is a wildcard bind
        ("10.0.8.6", True, True),      # LAN bind with a key
        ("127.0.0.1", True, True),     # loopback with a key
        ("10.0.8.6", "yes please", False),  # key flag must be a real boolean
    ],
)
def test_bind_assert_forbids_unauthenticated_non_loopback(tmp_path, host, key_required, ok):
    result = _run_guard(tmp_path, host, key_required)
    assert (result.returncode == 0) is ok, result.stdout + result.stderr


def test_production_host_requires_key_and_firewall_ssh_scope():
    hv = load("inventory/production/host_vars/ai-ms-s1-max-01.yml")
    assert hv["llama_cpp_hip_host"] == "10.0.8.6"
    assert hv["llama_cpp_hip_api_key_required"] is True
    # ufw default-deny needs an explicit SSH scope or the security role refuses to run.
    assert set(hv["security_management_cidrs"]) >= {
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
    }
    assert "10.0.8.5/32" in hv["security_inference_api_cidrs"]
