"""Repository Context Investigator for Real-Repository Engineering."""
from __future__ import annotations

import ast
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Any, Optional

from autonomous_engineering.core.crypto import content_hash


@dataclass(frozen=True)
class FileInvestigationSummary:
    file_path: str
    exists: bool
    line_count: int
    functions: tuple[str, ...]
    classes: tuple[str, ...]
    imports: tuple[str, ...]
    file_hash: str


@dataclass(frozen=True)
class RepositoryInvestigationEvidence:
    repository_id: str
    repository_path: str
    target_paths: tuple[str, ...]
    summaries: tuple[FileInvestigationSummary, ...]
    related_tests: tuple[str, ...]
    investigation_hash: str
    summary_text: str

    @classmethod
    def create(
        cls,
        repository_id: str,
        repository_path: str,
        target_paths: tuple[str, ...],
        summaries: tuple[FileInvestigationSummary, ...],
        related_tests: tuple[str, ...],
        summary_text: str,
    ) -> RepositoryInvestigationEvidence:
        payload = {
            "repository_id": repository_id,
            "repository_path": repository_path,
            "target_paths": target_paths,
            "summaries": [asdict(s) for s in summaries],
            "related_tests": related_tests,
            "summary_text": summary_text,
        }
        digest = content_hash(payload)
        return cls(
            repository_id=repository_id,
            repository_path=repository_path,
            target_paths=target_paths,
            summaries=summaries,
            related_tests=related_tests,
            investigation_hash=digest,
            summary_text=summary_text,
        )


class RepositoryInvestigator:
    """Safely inspects authorized repository scope and extracts architectural context."""

    def __init__(self, repo_dir: Path) -> None:
        self.repo_dir = repo_dir

    def investigate_paths(
        self,
        repository_id: str,
        target_paths: List[str],
        test_paths: Optional[List[str]] = None,
    ) -> RepositoryInvestigationEvidence:
        summaries: List[FileInvestigationSummary] = []

        for rel_path in target_paths:
            full_path = self.repo_dir / rel_path.lstrip("/")
            if not full_path.exists() or not full_path.is_file():
                summaries.append(
                    FileInvestigationSummary(
                        file_path=rel_path,
                        exists=False,
                        line_count=0,
                        functions=(),
                        classes=(),
                        imports=(),
                        file_hash="none",
                    )
                )
                continue

            content = full_path.read_text(encoding="utf-8", errors="replace")
            f_hash = content_hash(content)
            lines = content.splitlines()

            funcs: List[str] = []
            classes: List[str] = []
            imports: List[str] = []

            if full_path.suffix == ".py":
                try:
                    tree = ast.parse(content, filename=str(full_path))
                    for node in ast.walk(tree):
                        if isinstance(node, ast.FunctionDef):
                            funcs.append(node.name)
                        elif isinstance(node, ast.AsyncFunctionDef):
                            funcs.append(node.name)
                        elif isinstance(node, ast.ClassDef):
                            classes.append(node.name)
                        elif isinstance(node, ast.Import):
                            for alias in node.names:
                                imports.append(alias.name)
                        elif isinstance(node, ast.ImportFrom):
                            if node.module:
                                imports.append(node.module)
                except SyntaxError:
                    pass

            summaries.append(
                FileInvestigationSummary(
                    file_path=rel_path,
                    exists=True,
                    line_count=len(lines),
                    functions=tuple(sorted(set(funcs))),
                    classes=tuple(sorted(set(classes))),
                    imports=tuple(sorted(set(imports))),
                    file_hash=f_hash,
                )
            )

        # Scan for existing tests if not explicitly specified
        discovered_tests = list(test_paths or [])
        if not discovered_tests:
            tests_dir = self.repo_dir / "tests"
            if tests_dir.exists() and tests_dir.is_dir():
                for t in tests_dir.glob("test_*.py"):
                    discovered_tests.append(str(t.relative_to(self.repo_dir)))

        summary_text = (
            f"Investigated {len(summaries)} files across repository {repository_id}. "
            f"Found {sum(s.line_count for s in summaries)} total lines, "
            f"{sum(len(s.functions) for s in summaries)} functions, "
            f"and {len(discovered_tests)} relevant test files."
        )

        return RepositoryInvestigationEvidence.create(
            repository_id=repository_id,
            repository_path=str(self.repo_dir),
            target_paths=tuple(target_paths),
            summaries=tuple(summaries),
            related_tests=tuple(discovered_tests),
            summary_text=summary_text,
        )
