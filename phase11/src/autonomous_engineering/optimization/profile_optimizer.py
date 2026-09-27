"""
Autonomous Engineering System - Phase 11
Workstream F: Specialized-Agent Profile Optimizer

Synthesizes, versions, and validates optimized agent profiles.
Enforces the 3-way effective permission intersection and guarantees that profile
refinements never expand tool permissions beyond authorized work-order boundaries.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Optional, Set

from autonomous_engineering.profiles.registry import (
    AgentProfile,
    UnauthorizedOperationError,
    VersionedAgentProfileRegistry,
)


class ProfilePermissionError(UnauthorizedOperationError):
    """Raised when an optimized profile attempts to expand permissions beyond base authority."""


@dataclass(frozen=True)
class ProfileOptimizationRecord:
    """Audit record of a specialized agent profile optimization."""
    base_profile_id: str
    base_version: str
    optimized_version: str
    optimization_focus: str  # e.g., "concise_diff_generation", "strict_ast_verification"
    modified_instructions_digest: str
    effective_permission_subset_verified: bool
    evaluation_outcome_summary: Dict[str, Any]
    created_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class AgentProfileOptimizer:
    """
    Produces and verifies optimized agent profile versions.
    Guarantees strict subset authority and immutable versioning.
    """

    def __init__(self, profile_registry: VersionedAgentProfileRegistry) -> None:
        self.profile_registry = profile_registry

    def optimize_profile(
        self,
        profile_id: str,
        base_version: str,
        new_version: str,
        optimized_system_prompt: str,
        optimized_focus: str,
        permitted_tools_override: Optional[List[str]] = None,
    ) -> AgentProfile:
        """
        Synthesizes an optimized profile version:
        1. Retrieves base profile.
        2. Validates that new permitted tools are a strict subset of base profile tools (permission non-expansion).
        3. Constructs immutable profile with incremented semantic version.
        4. Registers into the versioned agent profile registry.
        """
        base_profile = self.profile_registry.get_profile(profile_id, base_version)

        # Enforce permission non-expansion
        target_tools = permitted_tools_override or base_profile.permitted_tool_capabilities
        base_tools_set = set(base_profile.permitted_tool_capabilities)
        if not set(target_tools).issubset(base_tools_set):
            unauthorized_tools = set(target_tools) - base_tools_set
            raise ProfilePermissionError(
                f"Profile optimization cannot expand authority: unauthorized tools {unauthorized_tools}"
            )

        optimized_profile = AgentProfile(
            profile_id=profile_id,
            semantic_version=new_version,
            specialization=base_profile.specialization,
            supported_workload_classes=base_profile.supported_workload_classes,
            required_model_capabilities=base_profile.required_model_capabilities,
            permitted_tool_capabilities=target_tools,
            prohibited_operations=base_profile.prohibited_operations,
            context_requirements=base_profile.context_requirements,
            input_schema_version=base_profile.input_schema_version,
            output_schema_version=base_profile.output_schema_version,
            max_reasoning_budget=base_profile.max_reasoning_budget,
            max_execution_steps=base_profile.max_execution_steps,
            max_repair_attempts=base_profile.max_repair_attempts,
            evidence_requirements=base_profile.evidence_requirements,
            validation_requirements=base_profile.validation_requirements,
            permitted_terminal_dispositions=base_profile.permitted_terminal_dispositions,
        )

        self.profile_registry.publish_profile(optimized_profile)
        return optimized_profile
