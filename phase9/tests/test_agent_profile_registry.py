import pytest

from autonomous_engineering.profiles.registry import (
    AgentProfile,
    ProfileNotFoundError,
    ProfileRevokedError,
    ProfileValidationError,
    VersionedAgentProfileRegistry,
)


def test_standard_profiles_initialized():
    registry = VersionedAgentProfileRegistry()
    investigator = registry.get_profile("repo-investigator", "1.0.0")
    assert investigator.profile_id == "repo-investigator"
    assert "investigation" in investigator.supported_workload_classes
    assert "read_file" in investigator.permitted_tool_capabilities
    assert "write_file" in investigator.prohibited_operations

    engineer = registry.get_profile("implementation-engineer", "1.0.0")
    assert engineer.profile_id == "implementation-engineer"
    assert "write_file" in engineer.permitted_tool_capabilities
    assert engineer.max_repair_attempts == 3


def test_profile_digest_immutability():
    registry = VersionedAgentProfileRegistry()
    profile = registry.get_profile("repo-investigator", "1.0.0")
    digest1 = profile.compute_digest()
    digest2 = profile.compute_digest()
    assert digest1 == digest2
    assert len(digest1) == 64

    # Retrieval by digest
    retrieved = registry.get_profile_by_digest(digest1)
    assert retrieved.profile_id == profile.profile_id


def test_effective_permissions_three_way_intersection():
    registry = VersionedAgentProfileRegistry()
    engineer = registry.get_profile("implementation-engineer", "1.0.0")

    # Work order grants only read_file and write_file, mutation to src/
    work_order_authority = {
        "permitted_tools": ["read_file", "write_file", "network_outbound"],
        "authorized_mutation_paths": ["src/service.py"],
        "max_reasoning_budget": 1024,
    }

    # Environment supports read_file, write_file, run_sandbox_command
    env_capabilities = {"read_file", "write_file", "run_sandbox_command"}

    effective = registry.resolve_effective_permissions(
        profile=engineer,
        work_order_authority=work_order_authority,
        environment_capabilities=env_capabilities,
    )

    # Intersection:
    # Profile tools: {"read_file", "write_file", "run_sandbox_command"}
    # WO tools: {"read_file", "write_file", "network_outbound"}
    # Env tools: {"read_file", "write_file", "run_sandbox_command"}
    # Intersection = {"read_file", "write_file"}
    # Prohibited: network_outbound, git_push, modify_ci
    assert sorted(effective["effective_tools"]) == ["read_file", "write_file"]
    assert effective["authorized_mutation_paths"] == ["src/service.py"]
    # Reasoning budget capped by the tighter WO authority
    assert effective["max_reasoning_budget"] == 1024


def test_profile_revocation_blocks_retrieval():
    registry = VersionedAgentProfileRegistry()
    profile = registry.get_profile("incident-investigator", "1.0.0")
    digest = profile.compute_digest()

    registry.revoke_profile(digest, "Security policy update")

    with pytest.raises(ProfileRevokedError):
        registry.get_profile_by_digest(digest)

    with pytest.raises(ProfileRevokedError):
        registry.get_profile("incident-investigator", "1.0.0")


def test_profile_publication_validation_and_digest_mismatch():
    registry = VersionedAgentProfileRegistry()
    custom_profile = AgentProfile(
        profile_id="custom-analyst",
        semantic_version="1.0.0",
        specialization="Custom Data Analyst",
        supported_workload_classes=["data_analysis"],
        required_model_capabilities=["code_comprehension"],
        permitted_tool_capabilities=["read_file"],
        prohibited_operations=["write_file"],
        context_requirements={"min_context_window": 8192},
        input_schema_version="1.0.0",
        output_schema_version="1.0.0",
        max_reasoning_budget=512,
        max_execution_steps=5,
        max_repair_attempts=0,
        evidence_requirements=["analysis_log"],
        validation_requirements=["syntax_pass"],
        permitted_terminal_dispositions=["ACCEPTED"],
    )

    # Valid publication
    digest = registry.publish_profile(custom_profile)
    assert len(digest) == 64

    # Publication with mismatched expected digest
    with pytest.raises(ProfileValidationError):
        registry.publish_profile(custom_profile, expected_digest="0" * 64)
