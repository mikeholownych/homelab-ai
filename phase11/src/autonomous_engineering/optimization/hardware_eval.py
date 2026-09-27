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


class ModelHardwareCompatibilityEvaluator:
    """
    Evaluates candidate models against the physical Dell Precision T5820 dual-Arc Pro B65 setup.
    Guarantees zero unauthorized physical model swaps on production serving infrastructure.
    """

    def __init__(
        self,
        vram_per_card_mb: int = 16384,
        cards_count: int = 2,
        current_resident_model: str = "engineering/b0",
    ) -> None:
        self.vram_per_card_mb = vram_per_card_mb
        self.cards_count = cards_count
        self.current_resident_model = current_resident_model

    def evaluate_hardware_fit(
        self,
        model_identifier: str,
        quantization: str,
        weights_gb: float,
        context_window_tokens: int = 32768,
    ) -> HardwareEvaluationResult:
        """
        Assesses physical hardware fit and computes memory requirements:
        1. Estimates model weights footprint + 15% runtime overhead.
        2. Estimates KV cache memory allocation for context window.
        3. Validates against 16GB per-card limits.
        4. Detects if resident model swap is required and prepares maintenance proposal.
        """
        model_size_mb = weights_gb * 1024 * 1.15
        # KV cache estimate for standard GQA 32k context (~1.5 MB per 1k tokens)
        kv_cache_mb = (context_window_tokens / 1000.0) * 45.0
        total_required_mb = model_size_mb + kv_cache_mb

        requires_swap = (model_identifier != self.current_resident_model)
        maintenance_prop: Optional[MaintenanceProposal] = None

        if total_required_mb > self.vram_per_card_mb:
            fit_status = HardwareFitStatus.INCOMPATIBLE_EXCEEDS_VRAM
        elif requires_swap:
            fit_status = HardwareFitStatus.COMPATIBLE_REQUIRES_SWAP
            maintenance_prop = MaintenanceProposal(
                proposal_id=f"maint-swap-{hashlib.sha256(model_identifier.encode()).hexdigest()[:8]}",
                target_node="10.0.8.5 (Dell Precision T5820)",
                current_resident_model=self.current_resident_model,
                proposed_candidate_model=model_identifier,
                proposed_quantization=quantization,
                vram_budget_mb=int(total_required_mb),
                rollback_target_model=self.current_resident_model,
                rollback_procedure=(
                    f"Stop container; restart vLLM TP=1 with resident model {self.current_resident_model}; "
                    f"verify /v1/models response."
                ),
            )
        else:
            fit_status = HardwareFitStatus.COMPATIBLE_RESIDENT

        digest_payload = {
            "model": model_identifier,
            "quantization": quantization,
            "status": fit_status.value,
            "total_mb": round(total_required_mb, 2),
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
            tensor_parallel_recommended=1,
            requires_resident_model_swap=requires_swap,
            maintenance_proposal=maintenance_prop,
            compatibility_digest=digest,
        )
