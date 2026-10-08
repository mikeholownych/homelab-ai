"""Contract for the node_exporter role and the loopback-only worker binding (no host needed)."""
from __future__ import annotations

import re
from pathlib import Path

import jinja2
import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles" / "node_exporter"


def _defaults() -> dict:
    return yaml.safe_load((ROLE / "defaults/main.yml").read_text())


def _render() -> str:
    return jinja2.Template((ROLE / "templates/prometheus-node-exporter.default.j2").read_text()).render(**_defaults())


def test_defaults_publish_nothing_beyond_loopback_and_are_off_until_enabled():
    d = _defaults()
    assert d["node_exporter_enabled"] is False
    assert d["node_exporter_listen_address"].startswith("127.0.0.1:")
    assert d["node_exporter_allow_non_loopback"] is False


def test_arguments_wire_the_textfile_collector_and_a_safe_systemd_filter():
    args = re.search(r'^ARGS="(.*)"$', _render(), re.M).group(1)
    d = _defaults()
    assert f"--web.listen-address={d['node_exporter_listen_address']}" in args
    assert f"--collector.textfile.directory={d['node_exporter_textfile_dir']}" in args
    assert "--collector.systemd" in args
    pattern = re.search(r"--collector.systemd.unit-include=(\S+)", args).group(1)
    assert not re.search(r"[\\$ ]", pattern), "the value travels through systemd's EnvironmentFile unchanged"
    assert re.fullmatch(pattern, "aihost-llama-worker1.service") and re.fullmatch(pattern, "vllm-top-console.service")
    assert not re.fullmatch(pattern, "ssh.service")


def test_host_can_disable_only_named_collectors_without_replacing_other_arguments():
    host = yaml.safe_load((ROOT / "inventory/production/host_vars/ai-5820-01.yml").read_text())
    assert host["node_exporter_disabled_collectors"] == ["xfs", "thermal_zone"]
    args = jinja2.Template((ROLE / "templates/prometheus-node-exporter.default.j2").read_text()).render(
        **{**_defaults(), **host}
    )
    assert "--no-collector.xfs" in args
    assert "--no-collector.thermal_zone" in args
    assert "--collector.textfile.directory=" in args


def test_the_guard_accepts_loopback_and_rejects_anything_else_unless_allowed():
    tasks = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
    guard = tasks[0]["ansible.builtin.assert"]["that"][0]
    pattern = re.search(r"match\('(.+?)'\)", guard).group(1)
    for ok in ("127.0.0.1:9100", "localhost:9100", "[::1]:9100"):
        assert re.match(pattern, ok), ok
    for bad in ("0.0.0.0:9100", "10.0.8.5:9100", ":9100", "9100", "127.0.0.1.evil.com:9100"):
        assert not re.match(pattern, bad), bad
    assert "node_exporter_allow_non_loopback" in guard
    assert "node_exporter_disabled_collectors" in yaml.safe_dump(tasks[0]["ansible.builtin.assert"]["that"])


def test_the_scoped_playbook_includes_the_role_only_when_enabled():
    play = yaml.safe_load((ROOT / "playbooks/inference.yml").read_text())[0]
    entry = next(r for r in play["roles"] if r.get("role") == "node_exporter")
    assert "node_exporter_enabled" in entry["when"]


def test_llama_workers_listen_on_loopback_by_default():
    defaults = yaml.safe_load((ROOT / "roles/llama_cpp_container/defaults/main.yml").read_text())
    assert defaults["llama_cpp_container_host"] == "127.0.0.1"
