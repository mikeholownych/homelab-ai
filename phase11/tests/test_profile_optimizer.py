import pytest

from autonomous_engineering.optimization.profile_optimizer import (
    AgentProfileOptimizer,
    ProfilePermissionError,
)
from autonomous_engineering.profiles.registry import VersionedAgentProfileRegistry


def test_profile_optimization_permission_non_expansion():
    registry = VersionedAgentProfileRegistry()
    optimizer = AgentProfileOptimizer(registry)

    # Base profile has read_file, write_file, run_sandbox_command
    # 1. Successful refinement with subset of tools
    opt = optimizer.optimize_profile(
        profile_id="implementation-engineer",
        base_version="1.0.0",
        new_version="1.1.0",
        optimized_system_prompt="Refined prompt focusing on deterministic diffs",
        optimized_focus="concise_diff_generation",
        permitted_tools_override=["read_file", "write_file"],
    )
    assert opt.semantic_version == "1.1.0"
    assert opt.permitted_tool_capabilities == ["read_file", "write_file"]

    # 2. Attempting to expand authority (e.g. adding deploy_to_production) fails closed
    with pytest.raises(ProfilePermissionError):
        optimizer.optimize_profile(
            profile_id="implementation-engineer",
            base_version="1.0.0",
            new_version="1.2.0",
            optimized_system_prompt="Privileged prompt",
            optimized_focus="privilege_escalation",
            permitted_tools_override=["read_file", "write_file", "deploy_to_production"],
        )
