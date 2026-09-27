import pytest
from autonomous_engineering.physical_qualification.maintenance_manager import (
    MaintenanceProposalManager,
    MaintenanceStatus,
)


def test_create_maintenance_proposal():
    mgr = MaintenanceProposalManager()
    prop = mgr.create_candidate_swap_proposal(
        target_candidate_id="CAND-QWEN2.5-7B-AWQ",
        target_model="Qwen/Qwen2.5-7B-Instruct-AWQ",
        snapshot_revision="b25037543e9394b818fdfca67ab2a00ecc7dd641",
        target_gpu=1,
        target_worker="vllm-xpu-tp1-worker2",
        target_port=8001,
    )
    assert prop.proposal_id.startswith("MAINT-PROP-CAND-QWEN2.5-7B-AWQ")
    assert prop.target_gpu_index == 1
    assert prop.status == MaintenanceStatus.STOPPED_PENDING_AUTHORIZATION
    assert prop.max_maintenance_duration_min == 15
    assert len(prop.rollback_trigger_conditions) >= 4
    assert len(prop.deployment_steps) >= 5
    assert len(prop.recovery_procedure_steps) >= 4
    assert prop.expected_vram_allocation_mib < 10000.0  # Fits easily
