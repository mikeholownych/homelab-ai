"""
Autonomous Engineering System - Phase 11
Workstream E: Model and Quantization Hardware Compatibility Evaluator

Assesses candidate models and quantization configurations against the physical
Intel Arc Pro B65 dual-GPU hardware platform on node 10.0.8.5, enforcing strict
VRAM containment and protected resident-model maintenance gating.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Dict, List, Optional


class HardwareFitStatus(str, Enum):
    COMPATIBLE_RESIDENT = "COMPATIBLE_RESIDENT"  # Runs directly within resident model
    COMPATIBLE_REQUIRES_SWAP = "COMPATIBLE_REQUIRES_SWAP"  # Fits hardware but requires authorized model swap
    INCOMPATIBLE_EXCEEDS_VRAM = "INCOMPATIBLE_EXCEEDS_VRAM"  # Exceeds per-card memory limits
    INCOMPATIBLE_BACKEND_UNSUPPORTED = "INCOMPATIBLE_BACKEND_UNSUPPORTED"


@dataclass(frozen=True)
class MaintenanceProposal:
    """A formal maintenance proposal required before performing any resident model swap."""
    proposal_id: str
    target_node: str
    current_resident_model: str
    proposed_candidate_model: str
    proposed_quantization: str
    vram_budget_mb: int
    rollback_target_model: str
    rollback_procedure: str
    status: str = "PENDING_AUTHORIZATION"
    created_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


PHYSICAL_B65_VRAM_MIB: int = 32656  # 31.890625 GiB physical per device
PHYSICAL_B65_MAX_ALLOC_MIB: float = 31023.20  # Max memory alloc size per device
DEFAULT_CARDS_COUNT: int = 2


@dataclass(frozen=True)
class HardwareEvaluationResult:
    """Hardware compatibility assessment for a model configuration."""
    model_identifier: str
    quantization: str
    fit_status: HardwareFitStatus
    model_size_mb: float
    kv_cache_headroom_mb: float
    total_vram_required_mb: float
    device_vram_limit_mb: float
    tensor_parallel_recommended: int
    requires_resident_model_swap: bool
    maintenance_proposal: Optional[MaintenanceProposal]
    compatibility_digest: str
    fits_aggregate_memory: bool = False
    vram_utilization_pct: float = 0.0


class ModelHardwareCompatibilityEvaluator:
    """
    Evaluates candidate models against the physical Dell Precision T5820 dual-Arc Pro B65 setup.
    Guarantees zero unauthorized physical model swaps on production serving infrastructure.
    Authoritative physical capacity: 32,656 MiB (31.89 GiB) per Intel Arc Pro B65 GPU.
    """

    def __init__(
        self,
        vram_per_card_mb: int = PHYSICAL_B65_VRAM_MIB,
        cards_count: int = DEFAULT_CARDS_COUNT,
        current_resident_model: str = "engineering/b0",
        runtime_overhead_pct: float = 15.0,
    ) -> None:
        self.vram_per_card_mb = vram_per_card_mb
        self.cards_count = cards_count
        self.current_resident_model = current_resident_model
        self.runtime_overhead_pct = runtime_overhead_pct

    def evaluate_hardware_fit(
        self,
        model_identifier: str,
        quantization: str,
        weights_gb: float,
        context_window_tokens: int = 32768,
        target_tensor_parallel: int = 1,
        max_concurrent_sequences: int = 1,
        is_binary_gib: bool = False,
    ) -> HardwareEvaluationResult:
        """
        Assesses physical hardware fit and computes memory requirements:
        1. Estimates model weights footprint + runtime overhead (default 15%).
        2. Estimates KV cache memory allocation for context window and concurrency.
        3. Validates against per-card limits (32,656 MiB physical B65 capacity).
        4. Detects multi-GPU aggregate fit when single-GPU capacity is exceeded.
        5. Detects if resident model swap is required and prepares maintenance proposal.
        """
        # Convert weight units (binary GiB = 1024 MiB, decimal GB = 1000 MB converted to MiB)
        if is_binary_gib:
            base_weights_mb = weights_gb * 1024.0
        else:
            base_weights_mb = weights_gb * 1024.0

        model_size_mb = base_weights_mb * (1.0 + self.runtime_overhead_pct / 100.0)

        # KV cache estimate: GQA 32k context (~1.5 MB per 1k tokens per sequence)
        kv_cache_per_seq_mb = (context_window_tokens / 1000.0) * 45.0
        kv_cache_mb = kv_cache_per_seq_mb * max_concurrent_sequences
        total_required_mb = model_size_mb + kv_cache_mb

        # Tensor parallel distribution
        per_card_required_mb = total_required_mb / target_tensor_parallel
        aggregate_capacity_mb = self.vram_per_card_mb * self.cards_count
        fits_aggregate = total_required_mb <= aggregate_capacity_mb

        requires_swap = (model_identifier != self.current_resident_model)
        maintenance_prop: Optional[MaintenanceProposal] = None

        if per_card_required_mb > self.vram_per_card_mb:
            fit_status = HardwareFitStatus.INCOMPATIBLE_EXCEEDS_VRAM
            rec_tp = 2 if fits_aggregate and target_tensor_parallel == 1 else target_tensor_parallel
        elif requires_swap:
            fit_status = HardwareFitStatus.COMPATIBLE_REQUIRES_SWAP
            rec_tp = target_tensor_parallel
            maintenance_prop = MaintenanceProposal(
                proposal_id=f"maint-swap-{hashlib.sha256(model_identifier.encode()).hexdigest()[:8]}",
                target_node="10.0.8.5 (Dell Precision T5820)",
                current_resident_model=self.current_resident_model,
                proposed_candidate_model=model_identifier,
                proposed_quantization=quantization,
                vram_budget_mb=int(total_required_mb),
                rollback_target_model=self.current_resident_model,
                rollback_procedure=(
                    f"Stop container; restart vLLM TP={target_tensor_parallel} with resident model {self.current_resident_model}; "
                    f"verify /v1/models response."
                ),
            )
        else:
            fit_status = HardwareFitStatus.COMPATIBLE_RESIDENT
            rec_tp = target_tensor_parallel

        utilization_pct = min(100.0, (per_card_required_mb / self.vram_per_card_mb) * 100.0)

        digest_payload = {
            "model": model_identifier,
            "quantization": quantization,
            "status": fit_status.value,
            "total_mb": round(total_required_mb, 2),
            "per_card_mb": round(per_card_required_mb, 2),
            "vram_limit_mb": self.vram_per_card_mb,
        }
        digest = hashlib.sha256(
            json.dumps(digest_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()

        return HardwareEvaluationResult(
            model_identifier=model_identifier,
            quantization=quantization,
            fit_status=fit_status,
            model_size_mb=round(model_size_mb, 2),
            kv_cache_headroom_mb=round(kv_cache_mb, 2),
            total_vram_required_mb=round(total_required_mb, 2),
            device_vram_limit_mb=float(self.vram_per_card_mb),
            tensor_parallel_recommended=rec_tp,
            requires_resident_model_swap=requires_swap,
            maintenance_proposal=maintenance_prop,
            compatibility_digest=digest,
            fits_aggregate_memory=fits_aggregate,
            vram_utilization_pct=round(utilization_pct, 2),
        )
