"""Capability-Aware Heterogeneous Scheduler for Phase 13.

Routes engineering operations across Worker 1 (Lead 30B) and Worker 2 (Specialist 7B)
based on task requirements, context size, worker health, and verified capabilities,
with deterministic, fail-closed fallback mechanisms.
"""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Optional, Tuple

from autonomous_engineering.heterogeneous.specialist_contracts import (
    LEAD_ENGINEERING_CONTRACT,
    SPECIALIST_REGISTRY,
    SpecialistRoutingContract,
    TaskClass,
)


class WorkerStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNHEALTHY = "UNHEALTHY"


@dataclass
class WorkerState:
    worker_id: str
    model_name: str
    revision: str
    port: int
    gpu_id: int
    status: WorkerStatus = WorkerStatus.HEALTHY
    active_requests: int = 0
    max_concurrency: int = 1
    total_completed: int = 0
    total_failures: int = 0


@dataclass
class TaskDispatchResult:
    task_id: str
    assigned_worker: str
    assigned_model: str
    routed_as_specialist: bool
    fallback_triggered: bool
    fallback_reason: Optional[str]
    provenance_chain: List[str] = field(default_factory=list)


class CapabilityAwareScheduler:
    def __init__(self, worker1: WorkerState, worker2: WorkerState):
        self.worker1 = worker1  # Lead Engineering Worker (30B)
        self.worker2 = worker2  # Specialist Worker (7B in heterogeneous mode, or 30B in baseline)
        self.specialist_registry = SPECIALIST_REGISTRY
        self.dispatched_history: List[TaskDispatchResult] = []

    def route_task(
        self,
        task_id: str,
        task_class: TaskClass,
        context_token_count: int,
        requested_tools: List[str],
        specialist_profile_id: Optional[str] = None,
    ) -> TaskDispatchResult:
        """Determines the optimal worker and model profile for a given engineering task."""
        provenance = [f"INCOMING_TASK:{task_id}:{task_class.value}:tokens={context_token_count}"]

        # 1. Check if a specialist profile is eligible
        admissible_specialist: Optional[SpecialistRoutingContract] = None
        if specialist_profile_id and specialist_profile_id in self.specialist_registry:
            candidate = self.specialist_registry[specialist_profile_id]
            is_valid, reason = candidate.validate_task_admission(task_class, context_token_count, requested_tools)
            if is_valid:
                admissible_specialist = candidate
                provenance.append(f"SPECIALIST_ADMITTED:{candidate.profile_id}")
            else:
                provenance.append(f"SPECIALIST_REJECTED:{reason}")
        else:
            # Automatic capability matching for specialist
            for prof_id, contract in self.specialist_registry.items():
                if prof_id == "lead-engineering-authority-v1":
                    continue
                is_valid, _ = contract.validate_task_admission(task_class, context_token_count, requested_tools)
                if is_valid:
                    admissible_specialist = contract
                    provenance.append(f"SPECIALIST_MATCHED:{contract.profile_id}")
                    break

        # 2. Check specialist worker availability and health
        if admissible_specialist:
            # Check if Worker 2 is serving the expected specialist model
            if self.worker2.status != WorkerStatus.HEALTHY:
                provenance.append(f"FALLBACK:Worker 2 status is {self.worker2.status.value}")
                return self._fallback_to_lead(task_id, "Specialist worker unhealthy", provenance)

            if self.worker2.model_name != admissible_specialist.target_model:
                # If Worker 2 is not loaded with the specialist model
                provenance.append(f"SPECIALIST_UNAVAILABLE_ON_WORKER2:Expected {admissible_specialist.target_model}, found {self.worker2.model_name}")
                # If Worker 2 is running the baseline lead model, it can share load
                if self.worker2.model_name == self.worker1.model_name:
                    chosen_worker = self.worker2 if self.worker2.active_requests <= self.worker1.active_requests else self.worker1
                    provenance.append(f"ROUTED_TO_BASELINE_LEAD:{chosen_worker.worker_id}")
                    return TaskDispatchResult(
                        task_id=task_id,
                        assigned_worker=chosen_worker.worker_id,
                        assigned_model=chosen_worker.model_name,
                        routed_as_specialist=False,
                        fallback_triggered=False,
                        fallback_reason=None,
                        provenance_chain=provenance,
                    )
                else:
                    # Model identity mismatch / untrusted model on worker 2 -> fail closed to Worker 1
                    return self._fallback_to_lead(task_id, f"Untrusted or mismatched model on Worker 2: {self.worker2.model_name}", provenance)

            # Route to specialist on Worker 2
            provenance.append(f"DISPATCHED_TO_SPECIALIST:{self.worker2.worker_id}")
            self.worker2.active_requests += 1
            res = TaskDispatchResult(
                task_id=task_id,
                assigned_worker=self.worker2.worker_id,
                assigned_model=admissible_specialist.target_model,
                routed_as_specialist=True,
                fallback_triggered=False,
                fallback_reason=None,
                provenance_chain=provenance,
            )
            self.dispatched_history.append(res)
            return res

        # 3. Default route to Lead Engineering Worker (Worker 1)
        provenance.append(f"DISPATCHED_TO_LEAD:{self.worker1.worker_id}")
        self.worker1.active_requests += 1
        res = TaskDispatchResult(
            task_id=task_id,
            assigned_worker=self.worker1.worker_id,
            assigned_model=self.worker1.model_name,
            routed_as_specialist=False,
            fallback_triggered=False,
            fallback_reason=None,
            provenance_chain=provenance,
        )
        self.dispatched_history.append(res)
        return res

    def _fallback_to_lead(self, task_id: str, reason: str, provenance: List[str]) -> TaskDispatchResult:
        """Executes fail-closed fallback to Worker 1 preserving provenance."""
        provenance.append(f"FALLBACK_DISPATCHED:{self.worker1.worker_id}:reason={reason}")
        self.worker1.active_requests += 1
        res = TaskDispatchResult(
            task_id=task_id,
            assigned_worker=self.worker1.worker_id,
            assigned_model=self.worker1.model_name,
            routed_as_specialist=False,
            fallback_triggered=True,
            fallback_reason=reason,
            provenance_chain=provenance,
        )
        self.dispatched_history.append(res)
        return res

    def handle_specialist_validation_failure(self, task_id: str, failure_message: str) -> TaskDispatchResult:
        """Escalates a task to the lead worker after specialist fails validation."""
        provenance = [f"SPECIALIST_EXECUTION_FAILED:{task_id}:msg={failure_message}"]
        return self._fallback_to_lead(task_id, f"Specialist validation failed: {failure_message}", provenance)
