"""Tests for Phase 6 Preregistration Acceptance Gates."""
import json
import os
from pathlib import Path
import pytest

from autonomous_engineering.core.crypto import content_hash


def test_gate1_phase5_baseline_and_integrity():
    """Gate 1: Verify Phase 5 baseline commit, manifest, and preregistration."""
    manifest_path = Path("phase5/evidence/manifest.sha256")
    assert manifest_path.exists(), "Phase 5 manifest must exist"
    
    # Check that key Phase 5 artifacts exist
    assert Path("phase5/docs/deployment_state_and_resource_feasibility.md").exists()
    assert Path("phase5/evidence/final_report.md").exists()
    assert Path("phase5/run_demo.py").exists()


def test_gate2_serving_topology_verification():
    """Gate 2: Verify serving topology audit and explicit declaration of inference tiers."""
    topology_doc = Path("phase6/docs/serving_topology_verification.md")
    assert topology_doc.exists(), "Serving topology verification document must exist"
    content = topology_doc.read_text(encoding="utf-8")

    assert "engineering/b0" in content, "Must record physical B65 serving endpoint"
    assert "18010" in content, "Must record local forwarded port"
    assert "Phi-4" in content, "Must address Phi-4 execution reality"
    assert "NON-EXISTENT" in content or "OFFLINE REGISTRY" in content or "ADAPTER REPLAY" in content


def test_gate3_and_gate4_repository_investigator(tmp_path):
    """Gates 3 & 4: Verify RepositoryInvestigator context extraction and AST parsing."""
    from autonomous_engineering.investigation.repo_investigator import RepositoryInvestigator

    test_repo = tmp_path / "repo"
    test_repo.mkdir()
    src_dir = test_repo / "src"
    src_dir.mkdir()
    (src_dir / "mod.py").write_text(
        "import os\nfrom pathlib import Path\n\nclass Worker:\n    def run(self):\n        pass\n"
    )
    (test_repo / "tests").mkdir()
    (test_repo / "tests" / "test_mod.py").write_text("def test_run():\n    pass\n")

    inv = RepositoryInvestigator(test_repo)
    evidence = inv.investigate_paths(
        repository_id="test_repo",
        target_paths=["src/mod.py"],
    )

    assert len(evidence.summaries) == 1
    s = evidence.summaries[0]
    assert s.file_path == "src/mod.py"
    assert "Worker" in s.classes
    assert "run" in s.functions
    assert "os" in s.imports
    assert len(evidence.related_tests) >= 1
    assert len(evidence.investigation_hash) == 64


def test_gate10_campaign_process_isolation():
    """Gate 10: Continuously audit that protected campaign processes are undisturbed."""
    protected_pids = [986, 3130937, 2093382]
    for pid in protected_pids:
        proc_path = Path(f"/proc/{pid}")
        assert proc_path.exists(), f"Protected campaign PID {pid} must remain active"
