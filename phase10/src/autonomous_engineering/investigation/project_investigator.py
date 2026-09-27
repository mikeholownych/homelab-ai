"""
Autonomous Engineering System - Phase 10
Workstream B: Repository-Scale Investigation

Extends the repository investigator capability to perform multi-module dependency tracing,
change-impact analysis, test coverage discovery, and architectural boundary analysis
grounded strictly in verified repository knowledge records.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from autonomous_engineering.knowledge.manager import (
    KnowledgeFactKind,
    RepositoryKnowledgeGraph,
    SymbolRecord,
)


class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass(frozen=True)
class SourceCitation:
    """Exact source location citing a repository fact."""
    repository_id: str
    baseline_commit: str
    file_path: str
    line_number: int
    symbol_name: Optional[str] = None


@dataclass(frozen=True)
class InvestigationFinding:
    """A verified architectural or code relationship finding."""
    finding_id: str
    topic: str
    summary: str
    fact_kind: KnowledgeFactKind
    citations: List[SourceCitation]
    confidence: ConfidenceLevel
    related_files: List[str]


@dataclass(frozen=True)
class ImpactAnalysisResult:
    """Result of analyzing the downstream impact of proposed file modifications."""
    target_files: List[str]
    directly_affected_symbols: List[str]
    downstream_dependent_modules: List[str]
    associated_test_files: List[str]
    risk_level: str
    unresolved_questions: List[str]


@dataclass(frozen=True)
class RepositoryInvestigationReport:
    """Comprehensive multi-module investigation report."""
    report_id: str
    repository_id: str
    baseline_commit: str
    objective: str
    findings: List[InvestigationFinding]
    impact_analysis: ImpactAnalysisResult
    architectural_boundaries: Dict[str, List[str]]
    created_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class RepositoryScaleInvestigator:
    """
    Conducts repository-scale architectural investigations and change-impact analysis
    using verified knowledge graph records.
    """

    def __init__(self, knowledge_graph: RepositoryKnowledgeGraph) -> None:
        self.graph = knowledge_graph

    def trace_dependencies(self, file_path: str) -> Dict[str, Any]:
        """
        Traces both upstream imports and downstream reverse dependents for a file.
        """
        upstream = [
            d.imported_module for d in self.graph.dependencies_by_file.get(file_path, [])
        ]
        mod_name = file_path.replace("/", ".").replace(".py", "")
        downstream = list(self.graph.reverse_dependencies.get(mod_name, set()))

        return {
            "file_path": file_path,
            "upstream_dependencies": upstream,
            "downstream_dependents": downstream,
        }

    def analyze_change_impact(self, target_files: List[str]) -> ImpactAnalysisResult:
        """
        Performs static change-impact analysis for a proposed set of file modifications.
        Identifies affected symbols, downstream importing modules, and associated tests.
        """
        affected_symbols: List[str] = []
        downstream_dependents: Set[str] = set()
        associated_tests: Set[str] = set()
        unresolved: List[str] = []

        for f in target_files:
            # Collect symbols defined in this file
            symbols = self.graph.symbols_by_file.get(f, [])
            for s in symbols:
                affected_symbols.append(f"{s.file_path}:{s.name}")

            # Collect downstream dependents
            mod_name = f.replace("/", ".").replace(".py", "")
            downstream = self.graph.reverse_dependencies.get(mod_name, set())
            downstream_dependents.update(downstream)

            # Collect associated tests
            tests = self.graph.test_mappings.get(f, [])
            associated_tests.update(tests)

            # Check if this file has zero test coverage
            if not tests:
                unresolved.append(f"No dedicated test files discovered for target file '{f}'")

        # Determine risk level based on dependent count
        if len(downstream_dependents) > 5 or len(target_files) > 3:
            risk = "HIGH"
        elif len(downstream_dependents) > 0:
            risk = "MEDIUM"
        else:
            risk = "LOW"

        return ImpactAnalysisResult(
            target_files=target_files,
            directly_affected_symbols=affected_symbols,
            downstream_dependent_modules=sorted(list(downstream_dependents)),
            associated_test_files=sorted(list(associated_tests)),
            risk_level=risk,
            unresolved_questions=unresolved,
        )

    def generate_investigation_report(
        self,
        objective: str,
        focal_files: List[str],
    ) -> RepositoryInvestigationReport:
        """
        Produces a comprehensive structured investigation report citing exact source facts.
        """
        impact = self.analyze_change_impact(focal_files)

        findings: List[InvestigationFinding] = []
        for idx, f in enumerate(focal_files):
            symbols = self.graph.symbols_by_file.get(f, [])
            citations = [
                SourceCitation(
                    repository_id=self.graph.repository_id,
                    baseline_commit=self.graph.baseline_commit,
                    file_path=s.file_path,
                    line_number=s.line_number,
                    symbol_name=s.name,
                )
                for s in symbols[:5]
            ]
            findings.append(
                InvestigationFinding(
                    finding_id=f"find-{idx + 1}",
                    topic=f"Module Structure for {f}",
                    summary=f"Contains {len(symbols)} declared symbols; imported by {len(self.trace_dependencies(f)['downstream_dependents'])} modules.",
                    fact_kind=KnowledgeFactKind.OBSERVED_SOURCE_FACT,
                    citations=citations,
                    confidence=ConfidenceLevel.HIGH,
                    related_files=[f] + self.trace_dependencies(f)["downstream_dependents"],
                )
            )

        # Detect architectural boundaries by top-level directory
        boundaries: Dict[str, List[str]] = {}
        for p in self.graph.symbols_by_file:
            top_pkg = p.split("/")[0] if "/" in p else "root"
            if top_pkg not in boundaries:
                boundaries[top_pkg] = []
            boundaries[top_pkg].append(p)

        return RepositoryInvestigationReport(
            report_id=f"rep-inv-{self.graph.baseline_commit[:8]}",
            repository_id=self.graph.repository_id,
            baseline_commit=self.graph.baseline_commit,
            objective=objective,
            findings=findings,
            impact_analysis=impact,
            architectural_boundaries=boundaries,
        )
