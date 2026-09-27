import tempfile
from pathlib import Path
import pytest

from autonomous_engineering.knowledge.manager import (
    KnowledgeCapacityExceededError,
    KnowledgeFactKind,
    RepositoryKnowledgeManager,
    StaleKnowledgeError,
)


@pytest.fixture
def sample_repo(tmp_path):
    repo_dir = tmp_path / "sample_repo"
    repo_dir.mkdir()
    (repo_dir / "src").mkdir()
    (repo_dir / "src" / "calc.py").write_text(
        '"""Calculator module."""\n'
        'import math\n\n'
        'class Calculator:\n'
        '    """Performs arithmetic."""\n'
        '    def add(self, a: int, b: int) -> int:\n'
        '        return a + b\n\n'
        'def helper():\n'
        '    return 42\n'
    )
    (repo_dir / "src" / "service.py").write_text(
        'from src.calc import Calculator\n\n'
        'class Service:\n'
        '    def __init__(self):\n'
        '        self.calc = Calculator()\n'
    )
    (repo_dir / "tests").mkdir()
    (repo_dir / "tests" / "test_calc.py").write_text(
        'from src.calc import Calculator\n\n'
        'def test_add():\n'
        '    assert Calculator().add(1, 2) == 3\n'
    )
    return repo_dir


def test_knowledge_graph_extraction(sample_repo):
    mgr = RepositoryKnowledgeManager()
    graph = mgr.index_repository(sample_repo, "sample-repo", "commit-001")

    assert "src/calc.py" in graph.symbols_by_file
    calc_symbols = {s.name: s for s in graph.symbols_by_file["src/calc.py"]}
    assert "Calculator" in calc_symbols
    assert calc_symbols["Calculator"].kind == "class"
    assert calc_symbols["Calculator"].docstring == "Performs arithmetic."
    assert "Calculator.add" in calc_symbols
    assert "helper" in calc_symbols

    # Test reverse dependencies
    assert "src.calc" in graph.reverse_dependencies
    assert "src/service.py" in graph.reverse_dependencies["src.calc"]
    assert "tests/test_calc.py" in graph.reverse_dependencies["src.calc"]

    # Test test mappings
    assert "src/calc.py" in graph.test_mappings
    assert "tests/test_calc.py" in graph.test_mappings["src/calc.py"]


def test_knowledge_graph_invalidation(sample_repo):
    mgr = RepositoryKnowledgeManager()
    graph = mgr.index_repository(sample_repo, "sample-repo", "commit-001")

    # Invalidate src/calc.py -> should mark calc.py and dependents (service.py) as dirty
    affected = mgr.invalidate_file("sample-repo", "src/calc.py")
    assert "src/calc.py" in affected
    assert "src/service.py" in affected
    assert "src/calc.py" in graph.dirty_files
    assert "src/service.py" in graph.dirty_files


def test_stale_knowledge_rejection(sample_repo):
    mgr = RepositoryKnowledgeManager()
    mgr.index_repository(sample_repo, "sample-repo", "commit-v1")

    # Querying with commit-v2 raises StaleKnowledgeError
    with pytest.raises(StaleKnowledgeError):
        mgr.get_graph("sample-repo", expected_commit="commit-v2")


def test_knowledge_capacity_exceeded(sample_repo):
    # Enforce tight capacity bound
    mgr = RepositoryKnowledgeManager(max_symbols_per_repo=2)

    with pytest.raises(KnowledgeCapacityExceededError):
        mgr.index_repository(sample_repo, "sample-repo", "commit-v1")
