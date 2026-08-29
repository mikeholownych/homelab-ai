from __future__ import annotations

from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
README_PATH = REPO_ROOT / "README.md"
COMMISSIONING_PATH = REPO_ROOT / "docs/commissioning.md"
ARCHITECTURE_PATH = REPO_ROOT / "docs/architecture.md"
OPERATIONS_PATH = REPO_ROOT / "docs/operations.md"


def test_readme_covers_required_topics():
    assert README_PATH.exists()
    content = README_PATH.read_text(encoding="utf-8").lower()
    required_topics = [
        "prerequisites",
        "supported host profile",
        "ubuntu install",
        "inventory",
        "vault",
        "bootstrap",
        "convergence",
        "scheduled reconciliation",
        "patching",
        "upgrade",
        "validation",
        "benchmark",
        "evidence",
        "observability",
        "future host",
        "clustering",
        "cmdb",
        "itsm",
        "rollback",
    ]
    for topic in required_topics:
        assert topic in content, f"Missing topic '{topic}' in README.md"


def test_commissioning_sequence_present():
    assert COMMISSIONING_PATH.exists()
    content = COMMISSIONING_PATH.read_text(encoding="utf-8").lower()
    expected_steps = [
        "capture factory state",
        "verify model/serial/psu",
        "verify memory/storage",
        "update approved firmware",
        "verify bios prerequisites",
        "install/configure first b65",
        "validate first gpu",
        "install/configure second b65",
        "validate both gpus",
        "deploy xpu stack",
        "deploy inference runtime",
        "run single-gpu test",
        "run dual-gpu test",
        "run sustained load test",
        "reboot",
        "rerun convergence",
        "verify idempotency",
        "capture accepted baseline",
    ]
    for step in expected_steps:
        assert step in content, f"Missing commissioning step '{step}' in docs/commissioning.md"


def test_architecture_and_operations_docs_exist():
    assert ARCHITECTURE_PATH.exists()
    assert OPERATIONS_PATH.exists()
