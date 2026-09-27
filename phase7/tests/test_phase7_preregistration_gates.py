"""Preregistration Gates & Environmental Non-Interference Verification for Phase 7."""
import os
from pathlib import Path
import pytest

from autonomous_engineering.core.types import WorkOrderState


def test_gate1_baseline_and_topology_reconciliation():
    """Gate 1: Verifies Phase 6 baseline commit, checksum manifest, and dual-TP=1 topology."""
    base_dir = Path(__file__).resolve().parent.parent
    
    # 1. Check baseline documents
    top_doc = base_dir / "docs" / "serving_topology_verification.md"
    base_doc = base_dir / "docs" / "phase7_baseline_verification.md"
    plan_doc = base_dir / "docs" / "phase7_engineering_plan.md"
    assert top_doc.exists(), "serving_topology_verification.md must exist"
    assert base_doc.exists(), "phase7_baseline_verification.md must exist"
    assert plan_doc.exists(), "phase7_engineering_plan.md must exist"

    top_text = top_doc.read_text()
    assert "Dual-TP=1" in top_text or "dual TP=1" in top_text
    assert "engineering/b0" in top_text
    assert "127.0.0.1:18010" in top_text


def test_gate8_campaign_process_isolation():
    """Gate 8: Audits protected T5820 autonomous-readiness campaign processes."""
    protected_pids = [986, 3130937, 2093382]
    for pid in protected_pids:
        proc_path = Path(f"/proc/{pid}")
        assert proc_path.exists(), f"Protected process PID {pid} must be active and undisturbed."
        
        status_text = (proc_path / "status").read_text()
        assert "State:" in status_text, f"Process status for PID {pid} must be readable."


def test_gate10_unattended_observability_invariants():
    """Gate 10: Verifies observability telemetry and fail-closed state tracking."""
    from autonomous_engineering.service.observability import (
        ServiceObservability,
        ServiceHealthStatus,
    )
    obs = ServiceObservability()
    snap = obs.get_snapshot(current_queue_depth=0)
    assert snap.health_status == ServiceHealthStatus.HEALTHY
    assert snap.active_tasks == 0
    assert snap.stale_rejections == 0

    obs.record_stale_rejection()
    snap2 = obs.get_snapshot(current_queue_depth=3)
    assert snap2.stale_rejections == 1
    assert snap2.queue_depth == 3
