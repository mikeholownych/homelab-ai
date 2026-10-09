"""Rules, alerts and dashboards are code: they must validate, evaluate correctly and only use metrics that exist."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from orchestrator_runtime import MetricsRegistry
from orchestrator_runtime.metrics import Histogram

ROOT = Path(__file__).resolve().parents[1]
OBS = ROOT / "observability"
RULES = OBS / "prometheus/rules/aihost.rules.yml"
PROMTOOL = shutil.which("promtool") or str(Path.home() / ".local/bin/promtool")
have_promtool = Path(PROMTOOL).exists()

# node_exporter series the rules and dashboards rely on (each verified against the live exporter when added).
NODE_METRICS = {
    "node_cpu_seconds_total", "node_memory_MemAvailable_bytes", "node_memory_MemTotal_bytes",
    "node_filesystem_avail_bytes", "node_filesystem_size_bytes", "node_systemd_unit_state",
}
# Declared in the gateway registry but never emitted today (unused paths): a panel on
# these would be permanently empty, which looks like "no problem" instead of "no data".
NEVER_EMITTED = {
    "aihost_inference_streaming_requests_total",
}


def _gateway_names() -> set[str]:
    names: set[str] = set()
    for metric in MetricsRegistry()._metrics:
        names.add(metric.name)
        if isinstance(metric, Histogram):
            names |= {f"{metric.name}_{suffix}" for suffix in ("bucket", "sum", "count")}
    return names


def _textfile_names() -> set[str]:
    script = (ROOT / "roles/monitoring/files/write-textfile-metrics.sh").read_text()
    return set(re.findall(r"\baihost_[a-z0-9_]+", script))


def _exprs_in_rules() -> list[str]:
    doc = yaml.safe_load(RULES.read_text())
    return [r["expr"] for g in doc["groups"] for r in g["rules"]]


def _recorded() -> set[str]:
    doc = yaml.safe_load(RULES.read_text())
    return {r["record"] for g in doc["groups"] for r in g["rules"] if "record" in r}


def _exprs_in_dashboards() -> list[tuple[str, str]]:
    found = []
    for path in sorted((OBS / "grafana/dashboards").glob("*.json")):
        for panel in json.loads(path.read_text())["panels"]:
            for target in panel.get("targets", []):
                found.append((path.name, target["expr"]))
    return found


def _referenced(expr: str) -> set[str]:
    return set(re.findall(r"\b(?:aihost|node)[_:][A-Za-z0-9_:]*", expr))


def test_every_referenced_metric_exists_and_is_actually_emitted():
    known = _gateway_names() | _textfile_names() | _recorded() | NODE_METRICS
    problems = []
    for expr in _exprs_in_rules() + [e for _, e in _exprs_in_dashboards()]:
        for name in _referenced(expr):
            if name not in known:
                problems.append(f"unknown metric {name} in: {expr[:90]}")
            if name in NEVER_EMITTED:
                problems.append(f"{name} is never emitted but is used in: {expr[:90]}")
    assert not problems, "\n".join(problems)


def test_every_recording_rule_is_used_somewhere_and_follows_the_naming_convention():
    expressions = _exprs_in_rules() + [e for _, e in _exprs_in_dashboards()]
    for name in _recorded():
        assert re.fullmatch(r"aihost:[a-z0-9_]+:[a-z0-9_]+", name), f"{name} must be level:metric:operations"
    unused = [n for n in _recorded() if not any(n in e for e in expressions)]
    assert not unused, f"recorded but never used by an alert, another rule or a panel: {unused}"


def test_alerts_have_severity_and_a_summary_and_wait_before_firing():
    doc = yaml.safe_load(RULES.read_text())
    alerts = [r for g in doc["groups"] for r in g["rules"] if "alert" in r]
    assert alerts
    for a in alerts:
        assert a["labels"]["severity"] in ("warning", "critical"), a["alert"]
        assert a["annotations"]["summary"], a["alert"]
        assert a.get("for"), f"{a['alert']} must have a for: duration so a single bad scrape cannot page"


def test_committed_dashboards_match_the_generator_and_are_well_formed():
    result = subprocess.run([sys.executable, str(OBS / "tools/build_dashboards.py"), "--check"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    for path in (OBS / "grafana/dashboards").glob("*.json"):
        board = json.loads(path.read_text())
        assert board["uid"] and board["title"] and board["panels"]
        ids = [p["id"] for p in board["panels"]]
        assert len(ids) == len(set(ids)), "panel ids must be unique"
        for panel in board["panels"]:
            if panel["type"] == "row":
                continue
            assert panel["description"], f"{path.name}: '{panel['title']}' needs a description"
            assert panel["fieldConfig"]["defaults"].get("unit"), f"{path.name}: '{panel['title']}' needs a unit"
            assert panel["targets"], panel["title"]


@pytest.mark.skipif(not have_promtool, reason="promtool is not installed (a test-time dependency only)")
def test_promtool_accepts_the_rules_and_the_example_config():
    for args in (["check", "rules", str(RULES)], ["check", "config", str(OBS / "prometheus/prometheus.example.yml")]):
        result = subprocess.run([PROMTOOL, *args], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(not have_promtool, reason="promtool is not installed (a test-time dependency only)")
def test_promtool_unit_tests_for_every_rule_pass():
    result = subprocess.run([PROMTOOL, "test", "rules", str(OBS / "prometheus/tests/aihost.rules.test.yml")], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
