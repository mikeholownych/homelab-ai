"""
Autonomous Engineering System - Phase 9
Workstream E: Physical Inference Resource Management

Tracks physical hardware resources on the Dell T5820 / 10.0.8.5 cluster,
enforces worker isolation, memory boundaries, and protects resident models from unauthorized swaps.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class WorkerHealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    UNRESPONSIVE = "UNRESPONSIVE"


class ResourceError(Exception):
    """Base exception for physical resource management."""


class ModelSwapProhibitedError(ResourceError):
    """Raised when an operation attempts to swap out a protected resident model."""


class InsufficientVRAMError(ResourceError):
    """Raised when memory requirement exceeds single-GPU addressable boundary."""


class WorkerUnavailableError(ResourceError):
    """Raised when all qualified workers are unhealthy or capacity exhausted."""


@dataclass
class PhysicalWorkerState:
    """
    Tracks operational metrics and residency for a physical inference worker.
    """
    worker_id: str
    gpu_index: int
    pcie_bus: str
    port: int
    resident_model_identifier: str
    resident_model_revision: str
    total_vram_bytes: int
    used_vram_bytes: int
    max_context_window: int
    active_requests: int
    queue_depth: int
    health_status: WorkerHealthStatus
    is_protected_resident: bool
    last_health_check_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def free_vram_bytes(self) -> int:
        return max(0, self.total_vram_bytes - self.used_vram_bytes)


class PhysicalInferenceResourceManager:
    """
    Manages physical worker allocations, prevents cross-GPU memory leakage,
    and enforces immutable residency of protected models.
    """

    def __init__(self, allow_model_swaps: bool = False) -> None:
        self.allow_model_swaps = allow_model_swaps
        self._workers: Dict[str, PhysicalWorkerState] = {}
        self._initialize_t5820_cluster()

    def get_worker(self, worker_id: str) -> Optional[PhysicalWorkerState]:
        return self._workers.get(worker_id)

    def list_workers(self) -> List[PhysicalWorkerState]:
        return list(self._workers.values())

    def allocate_worker_for_request(
        self,
        model_identifier: str,
        required_context_tokens: int,
    ) -> PhysicalWorkerState:
        """
        Selects an available, healthy worker hosting the resident model.
        Fails closed if the model is not resident or worker is unhealthy.
        """
        eligible: List[PhysicalWorkerState] = []
        for w in self._workers.values():
            if w.health_status != WorkerHealthStatus.HEALTHY:
                continue
            if w.resident_model_identifier != model_identifier:
                continue
            if required_context_tokens > w.max_context_window:
                continue
            eligible.append(w)

        if not eligible:
            raise WorkerUnavailableError(
                f"No healthy worker hosting '{model_identifier}' with context >= {required_context_tokens}"
            )

        # Least-loaded selection: min(active_requests + queue_depth)
        selected = min(eligible, key=lambda w: (w.active_requests, w.queue_depth))
        selected.active_requests += 1
        return selected

    def release_worker_request(self, worker_id: str) -> None:
        """Releases an active request slot on completion."""
        worker = self._workers.get(worker_id)
        if worker and worker.active_requests > 0:
            worker.active_requests -= 1

    def attempt_model_swap(
        self,
        worker_id: str,
        target_model: str,
        target_revision: str,
        required_vram_bytes: int,
    ) -> None:
        """
        Enforces policy on model swapping. Protected resident models cannot be swapped.
        """
        worker = self._workers.get(worker_id)
        if not worker:
            raise WorkerUnavailableError(f"Worker {worker_id} not found")

        if worker.is_protected_resident and not self.allow_model_swaps:
            raise ModelSwapProhibitedError(
                f"Model swap prohibited: worker {worker_id} hosts protected resident model '{worker.resident_model_identifier}'"
            )

        if required_vram_bytes > worker.total_vram_bytes:
            raise InsufficientVRAMError(
                f"Model requires {required_vram_bytes} bytes, but GPU {worker.gpu_index} has {worker.total_vram_bytes} bytes total"
            )

        # Update residency if authorized
        worker.resident_model_identifier = target_model
        worker.resident_model_revision = target_revision
        worker.used_vram_bytes = required_vram_bytes

    def record_health_check(self, worker_id: str, is_healthy: bool) -> None:
        """Updates health status for a worker."""
        worker = self._workers.get(worker_id)
        if worker:
            worker.health_status = WorkerHealthStatus.HEALTHY if is_healthy else WorkerHealthStatus.UNRESPONSIVE
            worker.last_health_check_utc = datetime.now(timezone.utc).isoformat()

    def get_aggregate_cluster_telemetry(self) -> Dict[str, Any]:
        """Provides an authoritative telemetry snapshot of physical GPU cluster state."""
        return {
            "node": "10.0.8.5",
            "host_platform": "Dell Precision T5820",
            "worker_count": len(self._workers),
            "allow_model_swaps": self.allow_model_swaps,
            "workers": [
                {
                    "worker_id": w.worker_id,
                    "gpu_index": w.gpu_index,
                    "resident_model": w.resident_model_identifier,
                    "active_requests": w.active_requests,
                    "health": w.health_status.value,
                    "free_vram_mb": w.free_vram_bytes // (1024 * 1024),
                }
                for w in self._workers.values()
            ],
        }

    def _initialize_t5820_cluster(self) -> None:
        """Configures the dual Arc Pro B65 TP=1 cluster."""
        total_b65_bytes = 34240757760  # 31.89 GiB addressable GDDR6
        used_qwen_bytes = 26306674688  # ~24.5 GiB AWQ resident

        # Worker 1 on GPU 0
        self._workers["vllm-xpu-tp1-worker1"] = PhysicalWorkerState(
            worker_id="vllm-xpu-tp1-worker1",
            gpu_index=0,
            pcie_bus="0000:51:00.0",
            port=8000,
            resident_model_identifier="engineering/b0",
            resident_model_revision="qwen3-coder-30b-awq-v1",
            total_vram_bytes=total_b65_bytes,
            used_vram_bytes=used_qwen_bytes,
            max_context_window=65536,
            active_requests=0,
            queue_depth=0,
            health_status=WorkerHealthStatus.HEALTHY,
            is_protected_resident=True,
        )

        # Worker 2 on GPU 1
        self._workers["vllm-xpu-tp1-worker2"] = PhysicalWorkerState(
            worker_id="vllm-xpu-tp1-worker2",
            gpu_index=1,
            pcie_bus="0000:93:00.0",
            port=8001,
            resident_model_identifier="engineering/b0",
            resident_model_revision="qwen3-coder-30b-awq-v1",
            total_vram_bytes=total_b65_bytes,
            used_vram_bytes=used_qwen_bytes,
            max_context_window=65536,
            active_requests=0,
            queue_depth=0,
            health_status=WorkerHealthStatus.HEALTHY,
            is_protected_resident=True,
        )
