"""
Autonomous Engineering System - Phase 9
Workstream A: Immutable Agent Profile Registry

Defines declarative, immutable agent execution contracts and enforces
the 3-way effective permission intersection:
    Effective Permissions = Profile Capabilities ∩ Work Order Authority ∩ Execution Environment
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class ProfileStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"
    REVOKED = "REVOKED"


class AgentProfileError(Exception):
    """Base error for profile registry operations."""


class ProfileValidationError(AgentProfileError):
    """Raised when profile schema or integrity validation fails."""


class ProfileRevokedError(AgentProfileError):
    """Raised when attempting to instantiate a revoked profile."""


class ProfileNotFoundError(AgentProfileError):
    """Raised when a requested profile identity or digest is not found."""


class UnauthorizedOperationError(AgentProfileError):
    """Raised when an operation exceeds profile or effective permissions."""


@dataclass(frozen=True)
class AgentProfile:
    """
    Immutable declarative execution contract for a specialized agent.
    Separated strictly from runtime agent instances.
    """
    profile_id: str
    semantic_version: str
    specialization: str
    supported_workload_classes: List[str]
    required_model_capabilities: List[str]
    permitted_tool_capabilities: List[str]
    prohibited_operations: List[str]
    context_requirements: Dict[str, Any]
    input_schema_version: str
    output_schema_version: str
    max_reasoning_budget: int
    max_execution_steps: int
    max_repair_attempts: int
    evidence_requirements: List[str]
    validation_requirements: List[str]
    permitted_terminal_dispositions: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def compute_digest(self) -> str:
        """
        Computes the canonical SHA-256 digest of this profile's declarative specification.
        """
        data = asdict(self)
        canonical_json = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AgentInstanceBinding:
    """
    Runtime binding connecting an immutable profile to a live execution context.
    """
    instance_id: str
    profile_id: str
    profile_digest: str
    work_order_id: str
    work_order_revision: int
    model_identifier: str
    model_revision: str
    inference_config: Dict[str, Any]
    authorized_mutation_paths: List[str]
    effective_tool_capabilities: List[str]
    bound_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class VersionedAgentProfileRegistry:
    """
    Authoritative registry for publishing, retrieving, validating,
    and resolving permissions for versioned agent profiles.
    """

    def __init__(self) -> None:
        self._profiles_by_digest: Dict[str, AgentProfile] = {}
        self._profiles_by_id_version: Dict[str, AgentProfile] = {}
        self._profile_status: Dict[str, ProfileStatus] = {}
        self._initialize_standard_profiles()

    def publish_profile(
        self,
        profile: AgentProfile,
        expected_digest: Optional[str] = None,
    ) -> str:
        """
        Publishes a new immutable agent profile.
        Validates integrity and ensures digest matches expected value if provided.
        """
        self._validate_profile_spec(profile)
        digest = profile.compute_digest()

        if expected_digest is not None and digest != expected_digest:
            raise ProfileValidationError(
                f"Computed profile digest {digest} does not match expected {expected_digest}"
            )

        id_ver_key = f"{profile.profile_id}@{profile.semantic_version}"
        if id_ver_key in self._profiles_by_id_version:
            existing_digest = self._profiles_by_id_version[id_ver_key].compute_digest()
            if existing_digest != digest:
                raise ProfileValidationError(
                    f"Profile {id_ver_key} already published with different digest {existing_digest}"
                )
            return existing_digest

        self._profiles_by_digest[digest] = profile
        self._profiles_by_id_version[id_ver_key] = profile
        self._profile_status[digest] = ProfileStatus.ACTIVE
        return digest

    def get_profile_by_digest(self, digest: str) -> AgentProfile:
        """Retrieves a profile by canonical content digest."""
        if digest not in self._profiles_by_digest:
            raise ProfileNotFoundError(f"Profile with digest {digest} not found")
        status = self._profile_status.get(digest, ProfileStatus.ACTIVE)
        if status == ProfileStatus.REVOKED:
            raise ProfileRevokedError(f"Profile {digest} has been revoked")
        return self._profiles_by_digest[digest]

    def get_profile(self, profile_id: str, semantic_version: str) -> AgentProfile:
        """Retrieves a profile by identity and semantic version."""
        key = f"{profile_id}@{semantic_version}"
        if key not in self._profiles_by_id_version:
            raise ProfileNotFoundError(f"Profile {key} not found")
        profile = self._profiles_by_id_version[key]
        digest = profile.compute_digest()
        status = self._profile_status.get(digest, ProfileStatus.ACTIVE)
        if status == ProfileStatus.REVOKED:
            raise ProfileRevokedError(f"Profile {key} ({digest}) has been revoked")
        return profile

    def revoke_profile(self, digest: str, reason: str) -> None:
        """Revokes a profile for safety or policy violations."""
        if digest not in self._profiles_by_digest:
            raise ProfileNotFoundError(f"Profile digest {digest} not found")
        self._profile_status[digest] = ProfileStatus.REVOKED

    def retire_profile(self, digest: str) -> None:
        """Retires a profile from new dispatches while keeping historical queries valid."""
        if digest not in self._profiles_by_digest:
            raise ProfileNotFoundError(f"Profile digest {digest} not found")
        self._profile_status[digest] = ProfileStatus.RETIRED

    def resolve_effective_permissions(
        self,
        profile: AgentProfile,
        work_order_authority: Dict[str, Any],
        environment_capabilities: Set[str],
    ) -> Dict[str, Any]:
        """
        Calculates the 3-way intersection:
        Profile Capabilities ∩ Work Order Authority ∩ Execution Environment.
        """
        # 1. Tool capabilities
        profile_tools = set(profile.permitted_tool_capabilities)
        wo_tools = set(work_order_authority.get("permitted_tools", profile.permitted_tool_capabilities))
        effective_tools = list(profile_tools & wo_tools & environment_capabilities)

        # 2. Path mutations
        wo_paths = set(work_order_authority.get("authorized_mutation_paths", []))
        # Profiles do not grant paths themselves; effective paths are bounded by WO
        effective_paths = sorted(list(wo_paths))

        # 3. Check prohibitions
        prohibited = set(profile.prohibited_operations)
        # Any tool that matches a prohibited operation is excluded
        effective_tools = [t for t in effective_tools if t not in prohibited]

        return {
            "effective_tools": effective_tools,
            "authorized_mutation_paths": effective_paths,
            "max_reasoning_budget": min(
                profile.max_reasoning_budget,
                work_order_authority.get("max_reasoning_budget", profile.max_reasoning_budget),
            ),
            "max_execution_steps": min(
                profile.max_execution_steps,
                work_order_authority.get("max_execution_steps", profile.max_execution_steps),
            ),
            "max_repair_attempts": min(
                profile.max_repair_attempts,
                work_order_authority.get("max_repair_attempts", profile.max_repair_attempts),
            ),
        }

    def instantiate_binding(
        self,
        instance_id: str,
        profile_digest: str,
        work_order_id: str,
        work_order_revision: int,
        model_identifier: str,
        model_revision: str,
        inference_config: Dict[str, Any],
        work_order_authority: Dict[str, Any],
        environment_capabilities: Set[str],
    ) -> AgentInstanceBinding:
        """
        Instantiates an authorized runtime binding for an agent execution step.
        """
        profile = self.get_profile_by_digest(profile_digest)
        effective = self.resolve_effective_permissions(
            profile, work_order_authority, environment_capabilities
        )

        return AgentInstanceBinding(
            instance_id=instance_id,
            profile_id=profile.profile_id,
            profile_digest=profile_digest,
            work_order_id=work_order_id,
            work_order_revision=work_order_revision,
            model_identifier=model_identifier,
            model_revision=model_revision,
            inference_config=inference_config,
            authorized_mutation_paths=effective["authorized_mutation_paths"],
            effective_tool_capabilities=effective["effective_tools"],
        )

    def _validate_profile_spec(self, p: AgentProfile) -> None:
        """Validates that a profile contains all mandatory fields and valid semantics."""
        if not p.profile_id or not p.semantic_version:
            raise ProfileValidationError("Profile must have valid profile_id and semantic_version")
        if not p.specialization:
            raise ProfileValidationError("Profile specialization must not be empty")
        if not p.supported_workload_classes:
            raise ProfileValidationError("Profile must support at least one workload class")
        if p.max_reasoning_budget <= 0:
            raise ProfileValidationError("max_reasoning_budget must be positive")
        if p.max_execution_steps <= 0:
            raise ProfileValidationError("max_execution_steps must be positive")

    def _initialize_standard_profiles(self) -> None:
        """Initializes the 8 standard qualified agent profiles."""
        standards = [
            AgentProfile(
                profile_id="repo-investigator",
                semantic_version="1.0.0",
                specialization="Repository Investigation and Context Extraction",
                supported_workload_classes=["investigation", "defect_repair", "multi_file", "refactor"],
                required_model_capabilities=["code_comprehension", "context_retrieval"],
                permitted_tool_capabilities=["read_file", "ast_grep", "git_log", "find_symbols"],
                prohibited_operations=["write_file", "git_push", "modify_ci", "network_outbound"],
                context_requirements={"min_context_window": 16384},
                input_schema_version="1.0.0",
                output_schema_version="1.0.0",
                max_reasoning_budget=1024,
                max_execution_steps=10,
                max_repair_attempts=0,
                evidence_requirements=["context_provenance", "symbol_manifest"],
                validation_requirements=["read_only_assertion"],
                permitted_terminal_dispositions=["INVESTIGATION_COMPLETE", "INVESTIGATION_FAILED"],
            ),
            AgentProfile(
                profile_id="systems-architect",
                semantic_version="1.0.0",
                specialization="System Architecture and Decomposition Planning",
                supported_workload_classes=["architectural_planning", "multi_file", "refactor"],
                required_model_capabilities=["structured_planning", "system_design"],
                permitted_tool_capabilities=["read_file", "find_symbols", "validate_plan_schema"],
                prohibited_operations=["write_file", "git_push", "modify_ci", "execute_code"],
                context_requirements={"min_context_window": 32768},
                input_schema_version="1.0.0",
                output_schema_version="1.0.0",
                max_reasoning_budget=2048,
                max_execution_steps=5,
                max_repair_attempts=1,
                evidence_requirements=["dag_plan", "interface_spec"],
                validation_requirements=["schema_validation"],
                permitted_terminal_dispositions=["PLAN_APPROVED", "PLAN_REJECTED"],
            ),
            AgentProfile(
                profile_id="implementation-engineer",
                semantic_version="1.0.0",
                specialization="Code Implementation and Bounded Mutation",
                supported_workload_classes=["defect_repair", "multi_file", "refactor", "feature"],
                required_model_capabilities=["code_generation", "tool_calling", "patch_synthesis"],
                permitted_tool_capabilities=["read_file", "write_file", "run_sandbox_command"],
                prohibited_operations=["git_push", "modify_ci", "network_outbound"],
                context_requirements={"min_context_window": 32768},
                input_schema_version="1.0.0",
                output_schema_version="1.0.0",
                max_reasoning_budget=2048,
                max_execution_steps=15,
                max_repair_attempts=3,
                evidence_requirements=["ast_syntax_pass", "unified_diff"],
                validation_requirements=["sandbox_unit_tests"],
                permitted_terminal_dispositions=["ACCEPTED", "REPAIRABLE", "REJECTED"],
            ),
            AgentProfile(
                profile_id="test-engineer",
                semantic_version="1.0.0",
                specialization="Automated Test Suite Development",
                supported_workload_classes=["test_development", "regression_verification"],
                required_model_capabilities=["test_synthesis", "assertion_generation"],
                permitted_tool_capabilities=["read_file", "write_file", "run_sandbox_command"],
                prohibited_operations=["git_push", "modify_ci", "network_outbound"],
                context_requirements={"min_context_window": 16384},
                input_schema_version="1.0.0",
                output_schema_version="1.0.0",
                max_reasoning_budget=1536,
                max_execution_steps=10,
                max_repair_attempts=2,
                evidence_requirements=["test_pass_verdict", "coverage_delta"],
                validation_requirements=["sandbox_unit_tests"],
                permitted_terminal_dispositions=["TESTS_PASSING", "TESTS_FAILING"],
            ),
            AgentProfile(
                profile_id="security-reviewer",
                semantic_version="1.0.0",
                specialization="Static Security and Vulnerability Analysis",
                supported_workload_classes=["security_analysis", "defect_repair", "multi_file"],
                required_model_capabilities=["vulnerability_detection", "taint_analysis"],
                permitted_tool_capabilities=["read_file", "ast_grep", "run_security_ast_scan"],
                prohibited_operations=["write_file", "git_push", "modify_ci", "execute_code"],
                context_requirements={"min_context_window": 32768},
                input_schema_version="1.0.0",
                output_schema_version="1.0.0",
                max_reasoning_budget=2048,
                max_execution_steps=8,
                max_repair_attempts=0,
                evidence_requirements=["security_ast_verdict", "threat_assessment"],
                validation_requirements=["zero_cwe_violations"],
                permitted_terminal_dispositions=["SECURITY_CLEAN", "SECURITY_VIOLATION"],
            ),
            AgentProfile(
                profile_id="performance-analyst",
                semantic_version="1.0.0",
                specialization="Algorithmic Complexity and Resource Profiling",
                supported_workload_classes=["performance_investigation", "refactor"],
                required_model_capabilities=["complexity_analysis", "profiling_interpretation"],
                permitted_tool_capabilities=["read_file", "run_benchmark_sandbox"],
                prohibited_operations=["write_file", "git_push", "modify_ci"],
                context_requirements={"min_context_window": 16384},
                input_schema_version="1.0.0",
                output_schema_version="1.0.0",
                max_reasoning_budget=1536,
                max_execution_steps=8,
                max_repair_attempts=0,
                evidence_requirements=["latency_benchmark_record"],
                validation_requirements=["non_regression_assertion"],
                permitted_terminal_dispositions=["PERFORMANCE_PASS", "PERFORMANCE_REGRESSION"],
            ),
            AgentProfile(
                profile_id="integration-reviewer",
                semantic_version="1.0.0",
                specialization="API Conformance and Cross-Repository Integration",
                supported_workload_classes=["multi_file", "feature", "refactor"],
                required_model_capabilities=["interface_matching", "contract_validation"],
                permitted_tool_capabilities=["read_file", "type_check", "ast_grep"],
                prohibited_operations=["write_file", "git_push", "modify_ci"],
                context_requirements={"min_context_window": 32768},
                input_schema_version="1.0.0",
                output_schema_version="1.0.0",
                max_reasoning_budget=1536,
                max_execution_steps=6,
                max_repair_attempts=0,
                evidence_requirements=["typecheck_verdict", "api_diff"],
                validation_requirements=["zero_type_errors"],
                permitted_terminal_dispositions=["INTEGRATION_VALID", "INTEGRATION_MISMATCH"],
            ),
            AgentProfile(
                profile_id="incident-investigator",
                semantic_version="1.0.0",
                specialization="Crash Log Triage and Root Cause Isolation",
                supported_workload_classes=["investigation", "defect_repair"],
                required_model_capabilities=["stacktrace_analysis", "root_cause_isolation"],
                permitted_tool_capabilities=["read_file", "git_bisect", "read_logs"],
                prohibited_operations=["write_file", "git_push", "modify_ci"],
                context_requirements={"min_context_window": 16384},
                input_schema_version="1.0.0",
                output_schema_version="1.0.0",
                max_reasoning_budget=1536,
                max_execution_steps=10,
                max_repair_attempts=0,
                evidence_requirements=["root_cause_report", "minimal_repro"],
                validation_requirements=["reproduction_pass"],
                permitted_terminal_dispositions=["ROOT_CAUSE_IDENTIFIED", "ROOT_CAUSE_UNKNOWN"],
            ),
        ]

        for prof in standards:
            self.publish_profile(prof)
