"""The CAIS reload must never reach a gateway that is still starting (2026-11-05 activation rollback).

A SIGHUP queued as a handler was flushed one second after the release restart, before the new process installed its
signal handler, and the default action killed it. The reload is now a task that runs only after strict readiness.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROLE = Path(__file__).resolve().parent.parent / "roles" / "orchestrator_gateway"


def _flatten(tasks):
    for task in tasks or []:
        yield task
        for key in ("block", "rescue", "always"):
            yield from _flatten(task.get(key))


def test_no_handler_signals_the_gateway():
    handlers = yaml.safe_load((ROLE / "handlers" / "main.yml").read_text())
    for handler in handlers:
        assert "--signal=HUP" not in str(handler), handler["name"]


def test_cais_reload_runs_only_after_verified_readiness_and_only_when_enforcing():
    names = []
    reload_task = None
    for task in _flatten(yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())):
        names.append(task.get("name"))
        if "--signal=HUP" in str(task.get("ansible.builtin.command", "")):
            reload_task = task
        assert "Reload gateway CAIS state" not in str(task.get("notify", "")), task.get("name")
    assert reload_task is not None
    assert names.index(reload_task["name"]) > names.index("Verify the activated gateway identity and readiness")
    assert "orchestrator_gateway_cais_mode == 'enforce'" in reload_task["when"]
