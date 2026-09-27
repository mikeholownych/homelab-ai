from pathlib import Path
import pytest

from autonomous_engineering.investigation.project_investigator import (
    ConfidenceLevel,
    RepositoryScaleInvestigator,
)
from autonomous_engineering.knowledge.manager import RepositoryKnowledgeManager


@pytest.fixture
def indexed_graph(tmp_path):
    repo_dir = tmp_path / "investigate_repo"
    repo_dir.mkdir()
    (repo_dir / "core").mkdir()
    (repo_dir / "core" / "engine.py").write_text("class Engine:\n    def start(self): pass\n")
    (repo_dir / "api").mkdir()
    (repo_dir / "api" / "routes.py").write_text("from core.engine import Engine\ndef handle(): Engine().start()\n")
    (repo_dir / "tests").mkdir()
    (repo_dir / "tests" / "test_engine.py").write_text("from core.engine import Engine\ndef test_eng(): Engine().start()\n")

    mgr = RepositoryKnowledgeManager()
    return mgr.index_repository(repo_dir, "test-repo", "commit-inv-1")


def test_investigator_dependency_tracing(indexed_graph):
    investigator = RepositoryScaleInvestigator(indexed_graph)

    trace = investigator.trace_dependencies("core/engine.py")
    assert "api/routes.py" in trace["downstream_dependents"]
    assert "tests/test_engine.py" in trace["downstream_dependents"]


def test_investigator_change_impact_analysis(indexed_graph):
    investigator = RepositoryScaleInvestigator(indexed_graph)

    impact = investigator.analyze_change_impact(["core/engine.py"])
    assert any("core/engine.py:Engine" in s for s in impact.directly_affected_symbols)
    assert "api/routes.py" in impact.downstream_dependent_modules
    assert "tests/test_engine.py" in impact.associated_test_files
    assert impact.risk_level in ["LOW", "MEDIUM", "HIGH"]


def test_investigator_report_generation(indexed_graph):
    investigator = RepositoryScaleInvestigator(indexed_graph)

    report = investigator.generate_investigation_report(
        objective="Refactor engine initialization",
        focal_files=["core/engine.py"],
    )

    assert report.repository_id == "test-repo"
    assert report.baseline_commit == "commit-inv-1"
    assert len(report.findings) >= 1
    finding = report.findings[0]
    assert finding.confidence == ConfidenceLevel.HIGH
    assert len(finding.citations) >= 1
    assert finding.citations[0].file_path == "core/engine.py"
    assert finding.citations[0].symbol_name == "Engine"
