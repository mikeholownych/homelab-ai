"""Exercise reconciliation reload decisions without touching a system manager."""
from itertools import product
from pathlib import Path

import pytest
import yaml
from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment

ROOT = Path(__file__).resolve().parents[1]
ENV = NativeEnvironment(undefined=StrictUndefined)
ENV.filters["bool"] = bool


def tasks(role, section="tasks", file="main.yml"):
    return yaml.safe_load((ROOT / "roles" / role / section / file).read_text())


def task(role, name, section="tasks", file="main.yml"):
    return next(t for t in tasks(role, section, file) if t["name"] == name)


CASES = [
    ("inference_policy", "Establish inference policy before any worker starts", "tasks", "main.yml", ["inference_policy_unit"]),
    ("inference_policy", "Reload inference policy", "handlers", "main.yml", ["inference_policy_unit"]),
    ("orchestrator_gateway", "Establish persistent gateway state", "tasks", "main.yml", ["orchestrator_gateway_unit", "orchestrator_gateway_removed_dropins"]),
    ("orchestrator_gateway", "Restart gateway service", "handlers", "main.yml", ["orchestrator_gateway_unit", "orchestrator_gateway_removed_dropins"]),
    ("vllm_top_console", "Enable the console service", "tasks", "main.yml", ["vllm_top_console_unit"]),
    ("vllm_top_console", "Restart vllm-top console", "handlers", "main.yml", ["vllm_top_console_unit"]),
    ("monitoring", "Establish textfile metrics timer state", "tasks", "main.yml", ["monitoring_metrics_units"]),
    ("monitoring", "Manage evidence sync timer state", "tasks", "evidence_sync.yml", ["monitoring_evidence_sync_service_unit", "monitoring_evidence_sync_timer_unit"]),
]


@pytest.mark.parametrize("role,name,section,file,variables", CASES)
def test_reload_only_for_changed_units(role, name, section, file, variables):
    expression = task(role, name, section, file)["ansible.builtin.systemd_service"]["daemon_reload"]
    for flags in product([False, True], repeat=len(variables)):
        context = {v: {"changed": flag} for v, flag in zip(variables, flags)}
        assert ENV.from_string(expression).render(context) is any(flags)
    # Skipped template tasks have no changed field.
    assert ENV.from_string(expression).render({v: {"skipped": True} for v in variables}) is False


@pytest.mark.parametrize("role,name,variables", [
    ("inference_origin", "Reload systemd after removing workload originators", ["inference_origin_removed_units"]),
    ("llama_cpp_container", "Reload systemd after installing or retiring unit files", ["llama_cpp_container_units", "llama_cpp_container_removed_units"]),
])
def test_standalone_reload_skipped_without_unit_changes(role, name, variables):
    expression = "{{ " + task(role, name)["when"][-1] + " }}"
    for flags in product([False, True], repeat=len(variables)):
        context = {v: {"changed": flag} for v, flag in zip(variables, flags)}
        assert ENV.from_string(expression).render(context) is any(flags)
    assert ENV.from_string(expression).render({v: {"skipped": True} for v in variables}) is False


def test_workers_reload_once_before_start_sequence_and_keep_drain():
    main = tasks("llama_cpp_container")
    reload_index = next(i for i, t in enumerate(main) if t["name"] == "Reload systemd after installing or retiring unit files")
    start_index = next(i for i, t in enumerate(main) if t.get("ansible.builtin.include_tasks") == "start_worker.yml")
    assert reload_index < start_index
    start = tasks("llama_cpp_container", file="start_worker.yml")
    assert all("daemon_reload" not in t.get("ansible.builtin.systemd_service", {}) for t in start)
    names = [t["name"] for t in start]
    drain = next(i for i, n in enumerate(names) if n.startswith("Assert drain succeeded"))
    worker_start = next(i for i, n in enumerate(names) if n.startswith("Ensure the worker"))
    assert drain < worker_start
