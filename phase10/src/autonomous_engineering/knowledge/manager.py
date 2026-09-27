"""
Autonomous Engineering System - Phase 10
Workstream A: Versioned Repository Knowledge

Constructs a source-grounded, versioned AST representation of repositories.
Strictly distinguishes directly observed facts from inferred relationships,
enforces commit-hash provenance, and manages incremental invalidation.
"""

import ast
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class KnowledgeFactKind(str, Enum):
    OBSERVED_SOURCE_FACT = "OBSERVED_SOURCE_FACT"
    INFERRED_ARCHITECTURAL_RELATION = "INFERRED_ARCHITECTURAL_RELATION"


class KnowledgeError(Exception):
    """Base exception for repository knowledge management."""


class KnowledgeCapacityExceededError(KnowledgeError):
    """Raised when repository indexing exceeds bounded capacity limits."""


class StaleKnowledgeError(KnowledgeError):
    """Raised when querying knowledge bound to an obsolete repository commit."""


@dataclass(frozen=True)
class SymbolRecord:
    """A declared class, function, method, or variable extracted from source."""
    name: str
    kind: str  # "class", "function", "method", "variable"
    file_path: str
    line_number: int
    docstring: Optional[str]
    is_exported: bool
    fact_kind: KnowledgeFactKind = KnowledgeFactKind.OBSERVED_SOURCE_FACT


@dataclass(frozen=True)
class DependencyRecord:
    """An import dependency between modules."""
    source_file: str
    imported_module: str
    imported_symbols: List[str]
    is_external: bool
    fact_kind: KnowledgeFactKind = KnowledgeFactKind.OBSERVED_SOURCE_FACT


@dataclass
class RepositoryKnowledgeGraph:
    """
    Source-grounded knowledge graph for an authorized repository revision.
    """
    repository_id: str
    baseline_commit: str
    symbols_by_file: Dict[str, List[SymbolRecord]] = field(default_factory=dict)
    dependencies_by_file: Dict[str, List[DependencyRecord]] = field(default_factory=dict)
    reverse_dependencies: Dict[str, Set[str]] = field(default_factory=dict)
    test_mappings: Dict[str, List[str]] = field(default_factory=dict)
    dirty_files: Set[str] = field(default_factory=set)
    indexed_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def compute_digest(self) -> str:
        """Computes canonical digest over all symbol and dependency records."""
        payload = {
            "repository_id": self.repository_id,
            "baseline_commit": self.baseline_commit,
            "symbols_count": sum(len(v) for v in self.symbols_by_file.values()),
            "dependencies_count": sum(len(v) for v in self.dependencies_by_file.values()),
            "files": sorted(list(self.symbols_by_file.keys())),
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class RepositoryKnowledgeManager:
    """
    Constructs, indexes, and maintains versioned repository knowledge graphs.
    """

    def __init__(
        self,
        max_symbols_per_repo: int = 50000,
        max_edges_per_repo: int = 100000,
    ) -> None:
        self.max_symbols = max_symbols_per_repo
        self.max_edges = max_edges_per_repo
        self._graphs: Dict[str, RepositoryKnowledgeGraph] = {}

    def get_graph(
        self,
        repository_id: str,
        expected_commit: Optional[str] = None,
    ) -> Optional[RepositoryKnowledgeGraph]:
        """Retrieves active knowledge graph for a repository, enforcing commit freshness."""
        graph = self._graphs.get(repository_id)
        if not graph:
            return None

        if expected_commit and graph.baseline_commit != expected_commit:
            raise StaleKnowledgeError(
                f"Knowledge graph for '{repository_id}' is at commit '{graph.baseline_commit}', but caller requested '{expected_commit}'"
            )
        return graph

    def index_repository(
        self,
        repo_dir: Path,
        repository_id: str,
        baseline_commit: str,
    ) -> RepositoryKnowledgeGraph:
        """
        Builds a source-grounded knowledge graph by parsing Python ASTs across the repository.
        """
        graph = RepositoryKnowledgeGraph(
            repository_id=repository_id,
            baseline_commit=baseline_commit,
        )

        total_symbols = 0
        total_edges = 0

        # Scan all .py files in repository
        py_files = sorted(list(repo_dir.rglob("*.py")))
        for file_path in py_files:
            rel_path = str(file_path.relative_to(repo_dir))
            # Ignore transient venvs and pycache
            if ".venv" in rel_path or "__pycache__" in rel_path or ".git" in rel_path:
                continue

            try:
                content = file_path.read_text(encoding="utf-8")
                tree = ast.parse(content, filename=rel_path)
            except Exception as e:
                logger.warning("Failed to parse AST for %s: %s", rel_path, e)
                continue

            symbols, deps = self._extract_ast_facts(tree, rel_path)

            if total_symbols + len(symbols) > self.max_symbols:
                raise KnowledgeCapacityExceededError(
                    f"Symbol count exceeded bound of {self.max_symbols}"
                )
            if total_edges + len(deps) > self.max_edges:
                raise KnowledgeCapacityExceededError(
                    f"Dependency edge count exceeded bound of {self.max_edges}"
                )

            graph.symbols_by_file[rel_path] = symbols
            graph.dependencies_by_file[rel_path] = deps
            total_symbols += len(symbols)
            total_edges += len(deps)

            # Build reverse dependencies
            for d in deps:
                target = d.imported_module
                if target not in graph.reverse_dependencies:
                    graph.reverse_dependencies[target] = set()
                graph.reverse_dependencies[target].add(rel_path)

        # Build test mappings: test_*.py -> implementation files
        self._map_test_relationships(graph)

        self._graphs[repository_id] = graph
        return graph

    def invalidate_file(
        self,
        repository_id: str,
        modified_file_path: str,
    ) -> Set[str]:
        """
        Invalidates a modified file and marks all downstream dependents as dirty.
        Returns the set of affected files requiring re-investigation.
        """
        graph = self._graphs.get(repository_id)
        if not graph:
            return set()

        affected: Set[str] = {modified_file_path}
        graph.dirty_files.add(modified_file_path)

        # Remove existing symbols for this file
        graph.symbols_by_file.pop(modified_file_path, None)
        graph.dependencies_by_file.pop(modified_file_path, None)

        # Find downstream modules that import this file (or its module name)
        mod_name = modified_file_path.replace("/", ".").replace(".py", "")
        downstream = graph.reverse_dependencies.get(mod_name, set())
        for d in downstream:
            affected.add(d)
            graph.dirty_files.add(d)

        return affected

    def _extract_ast_facts(
        self,
        tree: ast.AST,
        file_path: str,
    ) -> Tuple[List[SymbolRecord], List[DependencyRecord]]:
        """Deterministically extracts symbols and import statements from an AST."""
        symbols: List[SymbolRecord] = []
        dependencies: List[DependencyRecord] = []

        # Check for explicit __all__ export list
        all_exports: Optional[Set[str]] = None
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        if isinstance(node.value, (ast.List, ast.Tuple)):
                            all_exports = {
                                elt.value for elt in node.value.elts if isinstance(elt, ast.Constant)
                            }

        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                doc = ast.get_docstring(node)
                is_exp = node.name in all_exports if all_exports else not node.name.startswith("_")
                symbols.append(
                    SymbolRecord(
                        name=node.name,
                        kind="class",
                        file_path=file_path,
                        line_number=node.lineno,
                        docstring=doc,
                        is_exported=is_exp,
                    )
                )
                for item in node.body:
                    if isinstance(item, ast.FunctionDef):
                        m_doc = ast.get_docstring(item)
                        symbols.append(
                            SymbolRecord(
                                name=f"{node.name}.{item.name}",
                                kind="method",
                                file_path=file_path,
                                line_number=item.lineno,
                                docstring=m_doc,
                                is_exported=not item.name.startswith("_"),
                            )
                        )
            elif isinstance(node, ast.FunctionDef):
                doc = ast.get_docstring(node)
                is_exp = node.name in all_exports if all_exports else not node.name.startswith("_")
                symbols.append(
                    SymbolRecord(
                        name=node.name,
                        kind="function",
                        file_path=file_path,
                        line_number=node.lineno,
                        docstring=doc,
                        is_exported=is_exp,
                    )
                )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    dependencies.append(
                        DependencyRecord(
                            source_file=file_path,
                            imported_module=alias.name,
                            imported_symbols=[],
                            is_external=self._is_external_import(alias.name),
                        )
                    )
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                syms = [alias.name for alias in node.names]
                dependencies.append(
                    DependencyRecord(
                        source_file=file_path,
                        imported_module=mod,
                        imported_symbols=syms,
                        is_external=self._is_external_import(mod),
                    )
                )

        return symbols, dependencies

    def _is_external_import(self, module_name: str) -> bool:
        """Determines if an import is standard library or third-party."""
        known_std_lib = {
            "os", "sys", "ast", "json", "hashlib", "time", "datetime",
            "pathlib", "typing", "dataclasses", "enum", "logging",
            "shutil", "tempfile", "subprocess", "unittest", "pytest", "re"
        }
        root = module_name.split(".")[0]
        return root in known_std_lib or root.startswith("_")

    def _map_test_relationships(self, graph: RepositoryKnowledgeGraph) -> None:
        """Associates test files with corresponding implementation files."""
        for file_path in graph.symbols_by_file:
            if "test" in file_path.lower():
                # Check what modules this test imports
                deps = graph.dependencies_by_file.get(file_path, [])
                for d in deps:
                    imported = d.imported_module
                    # Match against files in graph
                    for candidate in graph.symbols_by_file:
                        cand_mod = candidate.replace("/", ".").replace(".py", "")
                        if cand_mod == imported or cand_mod.endswith(f".{imported}"):
                            if candidate not in graph.test_mappings:
                                graph.test_mappings[candidate] = []
                            if file_path not in graph.test_mappings[candidate]:
                                graph.test_mappings[candidate].append(file_path)
