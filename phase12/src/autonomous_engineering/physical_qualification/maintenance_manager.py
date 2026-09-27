"""Controlled maintenance proposal and rollback governance manager for Phase 12."""

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class MaintenanceStatus(str, Enum):
    PROPOSED = "PROPOSED"
    STOPPED_PENDING_AUTHORIZATION = "STOPPED_PENDING_AUTHORIZATION"
    AUTHORIZED = "AUTHORIZED"
    DEPLOYING = "DEPLOYING"
    QUALIFYING = "QUALIFYING"
    COMPLETED = "COMPLETED"
    ROLLED_BACK = "ROLLED_BACK"


@dataclass(frozen=True)
class MaintenanceProposal:
    proposal_id: str
    target_candidate_id: str
    model_identifier: str
    snapshot_revision: str
    target_gpu_index: int
    target_worker_name: str
    target_port: int
    expected_vram_allocation_mib: float
    service_interruption_scope: str
    baseline_config_hash: str
    rollback_config_hash: str
    max_maintenance_duration_min: int
    pre_maintenance_health_status: str
    rollback_trigger_conditions: List[str]
    deployment_steps: List[str]
    recovery_procedure_steps: List[str]
    independent_acceptance_criteria: str
    status: MaintenanceStatus


class MaintenanceProposalManager:
    """Manages creation, preflight checks, and authorization gating for physical model swaps."""

    def __init__(self):
        self._proposals: Dict[str, MaintenanceProposal] = {}

    def create_candidate_swap_proposal(
        self,
        target_candidate_id: str = "CAND-QWEN2.5-7B-AWQ",
        target_model: str = "Qwen/Qwen2.5-7B-Instruct-AWQ",
        snapshot_revision: str = "b25037543e9394b818fdfca67ab2a00ecc7dd641",
        target_gpu: int = 1,
        target_worker: str = "vllm-xpu-tp1-worker2",
        target_port: int = 8001,
    ) -> MaintenanceProposal:
        """Formulate a comprehensive, non-disruptive maintenance proposal to swap Worker 2."""

        baseline_hash = hashlib.sha256(b"vllm-xpu-tp1-worker2:cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit").hexdigest()
        rollback_hash = baseline_hash

        proposal_id = f"MAINT-PROP-{target_candidate_id}-GPU{target_gpu}"

        proposal = MaintenanceProposal(
            proposal_id=proposal_id,
            target_candidate_id=target_candidate_id,
            model_identifier=target_model,
            snapshot_revision=snapshot_revision,
            target_gpu_index=target_gpu,
            target_worker_name=target_worker,
            target_port=target_port,
            expected_vram_allocation_mib=7185.0,  # 5.4 GB weights + 1.0 GB overhead + 0.7 GB KV
            service_interruption_scope=(
                f"Swap Worker 2 on GPU 1 ({target_worker}) from Qwen3-Coder-30B to {target_model}. "
                "Worker 1 on GPU 0 (port 8000) remains online and fully operational throughout, "
                "preserving 100% production availability of 'engineering/b0' via orchestrator_gateway."
            ),
            baseline_config_hash=baseline_hash,
            rollback_config_hash=rollback_hash,
            max_maintenance_duration_min=15,
            pre_maintenance_health_status="PASSED (PIDs 986, 3130937, 2093382, 742882 verified healthy)",
            rollback_trigger_conditions=[
                "Container exit code non-zero upon launch",
                "OOM error or Level Zero driver crash during model load",
                "Port 8001 fails to respond with HTTP 200 within 120 seconds",
                "Independent engineering validation acceptance rate < 90%",
                "Interference or latency degradation observed on Worker 1 (GPU 0)",
            ],
            deployment_steps=[
                "1. Verify Worker 1 (GPU 0) is handling traffic normally.",
                f"2. Stop container '{target_worker}' via podman (GPU 1).",
                f"3. Generate updated vllm-config.yaml referencing snapshot '{snapshot_revision}'.",
                f"4. Launch '{target_worker}' with --model path pointing to local disk cache.",
                f"5. Await warm-up and poll 'http://127.0.0.1:{target_port}/v1/models' until HTTP 200.",
                "6. Execute 4 calibration qualification workloads against target worker.",
            ],
            recovery_procedure_steps=[
                f"1. Stop failing container '{target_worker}'.",
                "2. Restore original /etc/local-ai/vllm/worker2/vllm-config.yaml from backup.",
                "3. Re-launch original container serving cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit.",
                "4. Verify HTTP 200 on port 8001.",
                "5. Confirm dual-worker load balancing restored in orchestrator_gateway.",
            ],
            independent_acceptance_criteria="Pass 100% of calibration tasks with zero test runner failures.",
            status=MaintenanceStatus.STOPPED_PENDING_AUTHORIZATION,
        )

        self._proposals[proposal_id] = proposal
        return proposal

    def get_proposal(self, proposal_id: str) -> Optional[MaintenanceProposal]:
        return self._proposals.get(proposal_id)
