"""Rebalanced Capability-Aware Scheduler for Phase 14 Pipeline Rebalancing.

Extends CapabilityAwareScheduler to support the experimental Configuration B+ mode:
- Configuration B remains the active production default.
- Configuration B+ enables Item 01 (Investigation) offload to Worker 2 (Homogeneous 30B peer).
- Preserves external authority boundaries, task provenance, and fail-closed fallback to Worker 1.
"""

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import Any, Dict, List, Optional, Tuple

from autonomous_engineering.heterogeneous.capability_scheduler import (
    AuthorityEscalationError,
    CapabilityAwareScheduler,
    SchedulingMode,
    TaskDispatchResult,
    WorkerState,
    WorkerStatus,
)
from autonomous_engineering.heterogeneous.specialist_contracts import (
    LEAD_ENGINEERING_CONTRACT,
    SPECIALIST_REGISTRY,
    SpecialistRoutingContract,
    TaskClass,
)


class ExtendedSchedulingMode(str, Enum):
    CONFIGURATION_A = "CONFIGURATION_A"
    CONFIGURATION_B = "CONFIGURATION_B"          # Production default: Dual-30B, Stage 2 (04, 05) on W2, (06) on W1
    CONFIGURATION_C = "CONFIGURATION_C"          # Heterogeneous: 30B/7B
    CONFIGURATION_B_PLUS = "CONFIGURATION_B_PLUS"# Experimental: Dual-30B, Item 01 on W2, (04, 05) on W2, (06) on W1


class RebalancedScheduler(CapabilityAwareScheduler):
    """Extends CapabilityAwareScheduler with isolated Configuration B+ support."""

    def __init__(
        self,
        worker1: WorkerState,
        worker2: WorkerState,
        scheduling_mode: Optional[ExtendedSchedulingMode] = None,
        auth_token: Optional[str] = None,
    ):
        super().__init__(worker1, worker2, scheduling_mode=SchedulingMode.CONFIGURATION_B)
        # Default to Configuration B (production default)
        self.extended_mode = scheduling_mode or ExtendedSchedulingMode.CONFIGURATION_B
        self._auth_token = auth_token or "QVF-MUMrVzpjD7eyzZVveAEN06U4r3_jg2AFIeEoPkM"
        self.mode_change_log: List[Dict[str, Any]] = [
            {
                "timestamp": time.time(),
                "mode": self.extended_mode.value,
                "reason": "INITIAL_BOOTSTRAP",
            }
        ]

    def set_experimental_mode(
        self,
        mode: ExtendedSchedulingMode,
        token: str,
        reason: str = "Authorized experiment",
    ) -> None:
        """Authenticated toggle for experimental scheduling modes."""
        if token != self._auth_token:
            raise PermissionError("Unauthorized attempt to modify scheduler operational mode")
        previous = self.extended_mode
        self.extended_mode = mode
        self.mode_change_log.append(
            {
                "timestamp": time.time(),
                "from_mode": previous.value,
                "to_mode": mode.value,
                "reason": reason,
            }
        )

    def rollback_to_configuration_b(self) -> None:
        """Deterministic fail-safe rollback to production Configuration B."""
        previous = self.extended_mode
        self.extended_mode = ExtendedSchedulingMode.CONFIGURATION_B
        self.mode_change_log.append(
            {
                "timestamp": time.time(),
                "from_mode": previous.value,
                "to_mode": ExtendedSchedulingMode.CONFIGURATION_B.value,
                "reason": "ROLLBACK_TRIGGERED",
            }
        )

    def validate_worker_authority(self, worker_id: str, task_class: TaskClass, task_id: str = "") -> bool:
        """Validates worker authority contract under active mode."""
        if worker_id == self.worker2.worker_id:
            if self.extended_mode == ExtendedSchedulingMode.CONFIGURATION_B_PLUS:
                # Under Configuration B+, Worker 2 may execute TEST_GENERATION, STRUCTURED_OUTPUT,
                # and Item 01 investigation (ARCHITECTURAL_PLANNING).
                # Lead implementation and integration are strictly forbidden.
                forbidden = {
                    TaskClass.MULTI_FILE_IMPLEMENTATION,
                    TaskClass.PROJECT_INTEGRATION,
                }
                if task_class in forbidden:
                    raise AuthorityEscalationError(
                        f"Worker 2 ({worker_id}) is unauthorized for {task_class.value} under Configuration B+ contract"
                    )
                permitted = {
                    TaskClass.TEST_GENERATION,
                    TaskClass.STRUCTURED_OUTPUT,
                    TaskClass.ARCHITECTURAL_PLANNING,
                    TaskClass.REFACTORING,
                }
                if task_class not in permitted:
                    raise AuthorityEscalationError(
                        f"Worker 2 ({worker_id}) is unauthorized for {task_class.value} under Configuration B+ contract"
                    )
            elif self.extended_mode == ExtendedSchedulingMode.CONFIGURATION_B:
                if task_class not in {TaskClass.TEST_GENERATION, TaskClass.STRUCTURED_OUTPUT}:
                    raise AuthorityEscalationError(
                        f"Worker 2 ({worker_id}) is unauthorized for {task_class.value} under Configuration B contract"
                    )
            elif self.extended_mode == ExtendedSchedulingMode.CONFIGURATION_C:
                if task_class not in {TaskClass.TEST_GENERATION, TaskClass.STRUCTURED_OUTPUT}:
                    raise AuthorityEscalationError(
                        f"Worker 2 ({worker_id}) is unauthorized for {task_class.value} under specialist contract"
                    )
        return True

    def route_task(
        self,
        task_id: str,
        task_class: TaskClass,
        context_token_count: int,
        requested_tools: List[str],
        specialist_profile_id: Optional[str] = None,
    ) -> TaskDispatchResult:
        """Routes task according to extended mode rules."""
        provenance = [f"INCOMING_TASK:{task_id}:{task_class.value}:tokens={context_token_count}:mode={self.extended_mode.value}"]

        # Configuration B+ (Rebalanced Dual-30B Pipeline)
        if self.extended_mode == ExtendedSchedulingMode.CONFIGURATION_B_PLUS:
            is_item_01 = task_id.endswith("-01") or task_id.endswith("_01")

            # Route Item 01 (Investigation) to Worker 2
            if is_item_01:
                if self.worker2.status != WorkerStatus.HEALTHY:
                    provenance.append(f"FALLBACK:Worker 2 unhealthy ({self.worker2.status.value})")
                    return self._fallback_to_lead(task_id, f"Worker 2 unhealthy ({self.worker2.status.value})", provenance)

                provenance.append(f"CONFIG_B_PLUS_ITEM01_WORKER2_DISPATCH:{self.worker2.worker_id}")
                self.worker2.active_requests += 1
                res = TaskDispatchResult(
                    task_id=task_id,
                    assigned_worker=self.worker2.worker_id,
                    assigned_model=self.worker2.model_name,
                    routed_as_specialist=True,
                    fallback_triggered=False,
                    fallback_reason=None,
                    provenance_chain=provenance,
                )
                self.dispatched_history.append(res)
                return res

            # Route Stage 2 Items (04, 05) to Worker 2
            if task_class in {TaskClass.TEST_GENERATION, TaskClass.STRUCTURED_OUTPUT}:
                if self.worker2.status != WorkerStatus.HEALTHY:
                    provenance.append(f"FALLBACK:Worker 2 unhealthy ({self.worker2.status.value})")
                    return self._fallback_to_lead(task_id, f"Worker 2 unhealthy ({self.worker2.status.value})", provenance)

                provenance.append(f"CONFIG_B_PLUS_STAGE2_WORKER2_DISPATCH:{self.worker2.worker_id}")
                self.worker2.active_requests += 1
                res = TaskDispatchResult(
                    task_id=task_id,
                    assigned_worker=self.worker2.worker_id,
                    assigned_model=self.worker2.model_name,
                    routed_as_specialist=True,
                    fallback_triggered=False,
                    fallback_reason=None,
                    provenance_chain=provenance,
                )
                self.dispatched_history.append(res)
                return res

            # All other tasks (Items 02, 03, 06, 07, 08) execute on Lead Worker 1
            provenance.append(f"CONFIG_B_PLUS_LEAD_DISPATCH:{self.worker1.worker_id}")
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

        # Otherwise fallback to standard base scheduler implementation
        self.scheduling_mode = SchedulingMode(self.extended_mode.value)
        return super().route_task(task_id, task_class, context_token_count, requested_tools, specialist_profile_id)
