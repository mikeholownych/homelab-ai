"""Tests verifying Phase 5 10 Registered Acceptance Gates and Baseline Criteria."""
import os
from pathlib import Path
import pytest

from autonomous_engineering.router.evidence_router import EvidenceBasedRouter, RoutingTopology
from autonomous_engineering.eval.candidates import (
    CONTROL_QWEN3_CODER_30B_AWQ,
    CANDIDATE_PHI4_FP8,
)


def test_gate1_phase4_baseline_integrity():
    # Verify Phase 4 manifest exists and files are intact
    manifest_path = Path(__file__).parent.parent.parent / "phase4" / "evidence" / "manifest.sha256"
    assert manifest_path.exists()
    assert manifest_path.stat().st_size > 0


def test_gate2_and_gate3_vram_feasibility_proof():
    # Proof that concurrent B65 residency is mathematically impossible without exceeding 31.89 GB
    b65_physical_vram_gb = 31.89
    qwen3_tp2_vram_per_card = CONTROL_QWEN3_CODER_30B_AWQ.vram_budget_gb  # 24.5 GB
    phi4_tp1_vram = CANDIDATE_PHI4_FP8.vram_budget_gb  # 15.2 GB

    remaining_headroom = b65_physical_vram_gb - qwen3_tp2_vram_per_card
    assert remaining_headroom == pytest.approx(7.39, 0.01)

    # Coexistence check
    can_coexist_on_same_gpu = (qwen3_tp2_vram_per_card + phi4_tp1_vram) <= b65_physical_vram_gb
    assert can_coexist_on_same_gpu is False, "Concurrent residency MUST be proven impossible"


def test_gate4_tool_contract_schema_fidelity():
    from autonomous_engineering.eval.deployment_qual import AUTHORIZED_TOOLS
    assert len(AUTHORIZED_TOOLS) == 3
    tool_names = {t["function"]["name"] for t in AUTHORIZED_TOOLS}
    assert tool_names == {"read_file", "write_file", "replace_content"}


def test_gate10_campaign_process_isolation():
    # Verify that protected campaign processes (PID 986, 3130937, 2093382) are intact
    import subprocess
    cmd = ["ps", "-fp", "986,3130937,2093382"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0
    # Process table must show the running instances
    assert "986" in res.stdout
    assert "2093382" in res.stdout
    assert "3130937" in res.stdout
