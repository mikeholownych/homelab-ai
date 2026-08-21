from __future__ import annotations

import importlib.util
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AGGREGATOR_PATH = REPO_ROOT / "roles/validation/files/aggregate_validation.py"


def load_aggregator():
    spec = importlib.util.spec_from_file_location("aggregate_validation", AGGREGATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_classify_drift_no_drift():
    mod = load_aggregator()
    outcome = mod.classify_drift(
        predicted_changes=0,
        actual_changes=0,
        unresolved_changes=0,
        validation_status="PASS",
        has_blocking_failure=False,
    )
    assert outcome == "no_drift"


def test_classify_drift_remediated():
    mod = load_aggregator()
    outcome = mod.classify_drift(
        predicted_changes=2,
        actual_changes=2,
        unresolved_changes=0,
        validation_status="PASS",
        has_blocking_failure=False,
    )
    assert outcome == "remediated_drift"


def test_classify_drift_unresolved():
    mod = load_aggregator()
    outcome = mod.classify_drift(
        predicted_changes=2,
        actual_changes=0,
        unresolved_changes=2,
        validation_status="PASS",
        has_blocking_failure=False,
    )
    assert outcome == "unresolved_drift"


def test_classify_drift_blocking():
    mod = load_aggregator()
    outcome = mod.classify_drift(
        predicted_changes=0,
        actual_changes=0,
        unresolved_changes=0,
        validation_status="BLOCKED",
        has_blocking_failure=True,
    )
    assert outcome == "blocking_drift"
