"""R5 drain-and-swap: a worker change waits for a successful drain, except for a worker the gateway does not route to.

2026-10-10: the drain-safety check treated the gateway's 404 not_found for a candidate that did not exist yet as a
failed drain, after the lead worker had already been stopped, leaving the lead pool down until fixed."""
from pathlib import Path

import yaml

TASKS = yaml.safe_load((Path(__file__).resolve().parents[1] / "roles/llama_cpp_container/tasks/start_worker.yml").read_text())


def task(name_prefix: str) -> dict:
    return next(t for t in TASKS if t["name"].startswith(name_prefix))


def test_not_found_means_not_routed_and_is_the_only_drain_exemption():
    record = task("Record the drain result")["ansible.builtin.set_fact"]
    assert "== 200" in record["llama_cpp_container_drained"]
    not_routed = record["llama_cpp_container_not_routed"]
    assert "== 404" in not_routed and "'not_found'" in not_routed  # a bare 404 (e.g. wrong URL) does not qualify
    condition = " ".join(task("Assert drain succeeded")["ansible.builtin.assert"]["that"])
    assert "llama_cpp_container_drained" in condition and "llama_cpp_container_not_routed" in condition
    assert "llama_cpp_container_force_restart" in condition


def test_drain_reads_the_response_body_and_waits_only_after_a_real_drain():
    assert task("Drain through the gateway")["ansible.builtin.uri"]["return_content"] is True
    assert task("Wait for in-flight work to finish")["when"] == "llama_cpp_container_drained | bool"
