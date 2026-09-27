"""
Autonomous Engineering System - Phase 9
Workstream B: Evidence-Based Workload Classification

Analyzes admitted engineering operations to extract multidimensional workload
requirements, strictly decoupling computational difficulty from consequence of failure.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ReasoningComplexity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class FailureConsequence(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    IRREVERSIBLE = "IRREVERSIBLE"


class UncertaintyLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class WorkloadClassificationError(Exception):
    """Raised when workload classification fails or produces invalid contracts."""


@dataclass(frozen=True)
class WorkloadRequirements:
    """
    Structured, versioned specification of engineering task requirements.
    Decouples computational difficulty from failure consequence.
    """
    workload_id: str
    version: str
    task_class: str
    required_specializations: List[str]
    reasoning_complexity: ReasoningComplexity
    context_demand_tokens: int
    required_tools: List[str]
    expected_execution_cost: float
    failure_consequence: FailureConsequence
    mandatory_validation_suites: List[str]
    uncertainty_level: UncertaintyLevel
    resource_constraints: Dict[str, Any]
    classification_evidence: Dict[str, Any] = field(default_factory=dict)


class WorkloadRequirementsClassifier:
    """
    Evidence-based classifier determining multidimensional workload requirements.
    Applies deterministic invariant gates and optional advisory model heuristics.
    """

    def __init__(self, default_version: str = "1.0.0") -> None:
        self.default_version = default_version

    def classify(
        self,
        work_order_id: str,
        task_class: str,
        target_files: List[str],
        description: str,
        authorized_mutation_paths: List[str],
        advisory_model_hints: Optional[Dict[str, Any]] = None,
    ) -> WorkloadRequirements:
        """
        Classifies an admitted engineering operation into structured requirements.
        Ensures deterministic constraints override advisory model observations.
        """
        evidence: Dict[str, Any] = {
            "work_order_id": work_order_id,
            "task_class": task_class,
            "target_files_count": len(target_files),
            "target_files": target_files,
            "authorized_mutation_paths": authorized_mutation_paths,
            "has_advisory_hints": advisory_model_hints is not None,
        }

        # 1. Determine failure consequence based on target file sensitivity
        consequence = self._evaluate_failure_consequence(target_files, authorized_mutation_paths, evidence)

        # 2. Determine computational difficulty / reasoning complexity
        complexity = self._evaluate_reasoning_complexity(task_class, target_files, description, evidence)

        # 3. Determine required specializations based on task class & consequence
        specializations = self._determine_specializations(task_class, consequence, evidence)

        # 4. Determine context demand
        context_tokens = self._estimate_context_demand(target_files, task_class, evidence)

        # 5. Determine required tools
        tools = self._determine_required_tools(task_class, specializations)

        # 6. Determine mandatory validation suites (deterministic security gates)
        validation_suites = self._determine_validation_suites(task_class, consequence, evidence)

        # 7. Uncertainty estimation
        uncertainty = self._evaluate_uncertainty(description, target_files)

        # 8. Expected normalized execution cost
        cost = self._calculate_expected_cost(complexity, consequence, len(target_files), context_tokens)

        # 9. Resource constraints
        resource_constraints = {
            "max_wall_time_sec": 300 if complexity != ReasoningComplexity.CRITICAL else 600,
            "max_memory_mb": 4096 if context_tokens > 32768 else 2048,
            "gpu_worker_affinity": "any",
        }

        # Validate that advisory hints do not weaken mandatory safety constraints
        if advisory_model_hints:
            evidence["advisory_hints_applied"] = self._apply_advisory_hints_safely(
                advisory_model_hints, complexity, consequence
            )

        return WorkloadRequirements(
            workload_id=f"req-{work_order_id}",
            version=self.default_version,
            task_class=task_class,
            required_specializations=specializations,
            reasoning_complexity=complexity,
            context_demand_tokens=context_tokens,
            required_tools=tools,
            expected_execution_cost=cost,
            failure_consequence=consequence,
            mandatory_validation_suites=validation_suites,
            uncertainty_level=uncertainty,
            resource_constraints=resource_constraints,
            classification_evidence=evidence,
        )

    def _evaluate_failure_consequence(
        self,
        target_files: List[str],
        authorized_mutation_paths: List[str],
        evidence: Dict[str, Any],
    ) -> FailureConsequence:
        """
        Determines consequence of failure independently of reasoning complexity.
        Sensitive paths (auth, crypto, security, core authority) trigger HIGH/IRREVERSIBLE consequence.
        """
        sensitive_keywords = ["auth", "crypto", "token", "security", "permission", "admission", "fencing", "wal"]
        is_sensitive = False
        for f in target_files:
            lower = f.lower()
            if any(k in lower for k in sensitive_keywords):
                is_sensitive = True
                evidence["sensitive_path_matched"] = f
                break

        if is_sensitive:
            return FailureConsequence.HIGH

        if len(target_files) > 5 or any("service" in p for p in authorized_mutation_paths):
            return FailureConsequence.MEDIUM

        return FailureConsequence.LOW

    def _evaluate_reasoning_complexity(
        self,
        task_class: str,
        target_files: List[str],
        description: str,
        evidence: Dict[str, Any],
    ) -> ReasoningComplexity:
        """Evaluates computational problem difficulty based on problem structure."""
        tc = task_class.lower()
        if "architectural" in tc or "concurrency" in description.lower() or "race_condition" in description.lower():
            evidence["complexity_rationale"] = "Architectural or distributed concurrency logic"
            return ReasoningComplexity.CRITICAL

        if tc in ["multi_file", "refactor"] or len(target_files) >= 3:
            evidence["complexity_rationale"] = "Multi-file structural refactoring"
            return ReasoningComplexity.HIGH

        if tc in ["defect_repair", "test_development"]:
            evidence["complexity_rationale"] = "Targeted defect or unit test synthesis"
            return ReasoningComplexity.MEDIUM

        return ReasoningComplexity.LOW

    def _determine_specializations(
        self,
        task_class: str,
        consequence: FailureConsequence,
        evidence: Dict[str, Any],
    ) -> List[str]:
        """Determines ordered sequence of specialized agent profiles required."""
        specializations: List[str] = ["repo-investigator"]

        tc = task_class.lower()
        if tc == "architectural_planning":
            specializations.extend(["systems-architect"])
        elif tc == "test_development":
            specializations.extend(["test-engineer", "integration-reviewer"])
        elif tc in ["defect_repair", "multi_file", "refactor"]:
            specializations.extend(["implementation-engineer", "integration-reviewer"])
        elif tc == "security_analysis":
            specializations.extend(["security-reviewer"])
        else:
            specializations.extend(["implementation-engineer"])

        # High consequence tasks MANDATE an independent security reviewer
        if consequence in [FailureConsequence.HIGH, FailureConsequence.IRREVERSIBLE]:
            if "security-reviewer" not in specializations:
                specializations.append("security-reviewer")
                evidence["mandatory_security_escalation"] = True

        return specializations

    def _estimate_context_demand(
        self,
        target_files: List[str],
        task_class: str,
        evidence: Dict[str, Any],
    ) -> int:
        """Estimates minimum token context demand."""
        base_tokens = 4096
        per_file_tokens = 2048
        file_tokens = len(target_files) * per_file_tokens

        tc = task_class.lower()
        if tc in ["multi_file", "architectural_planning"]:
            multiplier = 2.0
        else:
            multiplier = 1.0

        estimated = int((base_tokens + file_tokens) * multiplier)
        # Clamp to realistic window bounds
        clamped = max(8192, min(estimated, 65536))
        evidence["context_tokens_estimated"] = clamped
        return clamped

    def _determine_required_tools(
        self,
        task_class: str,
        specializations: List[str],
    ) -> List[str]:
        """Determines required tools based on assigned specializations."""
        tools = {"read_file", "ast_grep"}
        if any(s in specializations for s in ["implementation-engineer", "test-engineer"]):
            tools.add("write_file")
            tools.add("run_sandbox_command")
        if "security-reviewer" in specializations:
            tools.add("run_security_ast_scan")
        return sorted(list(tools))

    def _determine_validation_suites(
        self,
        task_class: str,
        consequence: FailureConsequence,
        evidence: Dict[str, Any],
    ) -> List[str]:
        """Determines mandatory validation suites."""
        suites = ["syntax_ast"]
        if consequence in [FailureConsequence.HIGH, FailureConsequence.IRREVERSIBLE]:
            suites.append("security_ast_scan")
        if task_class.lower() != "investigation":
            suites.append("sandbox_test_suite")
        return sorted(suites)

    def _evaluate_uncertainty(self, description: str, target_files: List[str]) -> UncertaintyLevel:
        """Evaluates uncertainty level based on specification clarity and target definiteness."""
        if not target_files or len(description) < 30:
            return UncertaintyLevel.HIGH
        if len(target_files) > 4:
            return UncertaintyLevel.MEDIUM
        return UncertaintyLevel.LOW

    def _calculate_expected_cost(
        self,
        complexity: ReasoningComplexity,
        consequence: FailureConsequence,
        file_count: int,
        context_tokens: int,
    ) -> float:
        """Computes expected normalized engineering cost units."""
        complexity_weights = {
            ReasoningComplexity.LOW: 1.0,
            ReasoningComplexity.MEDIUM: 2.0,
            ReasoningComplexity.HIGH: 4.0,
            ReasoningComplexity.CRITICAL: 8.0,
        }
        consequence_weights = {
            FailureConsequence.LOW: 1.0,
            FailureConsequence.MEDIUM: 1.5,
            FailureConsequence.HIGH: 2.5,
            FailureConsequence.IRREVERSIBLE: 5.0,
        }
        token_cost = context_tokens / 16384.0
        file_factor = 1.0 + (0.2 * file_count)

        return round(
            complexity_weights[complexity] * consequence_weights[consequence] * token_cost * file_factor,
            2,
        )

    def _apply_advisory_hints_safely(
        self,
        hints: Dict[str, Any],
        current_complexity: ReasoningComplexity,
        current_consequence: FailureConsequence,
    ) -> Dict[str, Any]:
        """
        Advisory hints may escalate complexity or context demands,
        but are NEVER permitted to downgrade failure consequence or bypass validation.
        """
        applied = {}
        if "suggested_complexity" in hints:
            # Only allow upward escalation from hints
            suggested = hints["suggested_complexity"]
            if suggested == "CRITICAL" and current_complexity != ReasoningComplexity.CRITICAL:
                applied["complexity_escalated_by_hint"] = True
        return applied
