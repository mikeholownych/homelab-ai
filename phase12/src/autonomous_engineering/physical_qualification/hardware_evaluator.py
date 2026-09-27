"""Physical hardware compatibility and memory qualification evaluator for Phase 12."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


class PhysicalCompatibilityStatus(str, Enum):
    PHYSICALLY_VERIFIED = "PHYSICALLY_VERIFIED"
    DOCUMENTED_COMPATIBLE = "DOCUMENTED_COMPATIBLE"
    COMPATIBILITY_UNVERIFIED = "COMPATIBILITY_UNVERIFIED"
    INCOMPATIBLE = "INCOMPATIBLE"
    MAINTENANCE_REQUIRED = "MAINTENANCE_REQUIRED"


class ArchitectureFamily(str, Enum):
    QWEN2_CAUSAL_LM = "Qwen2ForCausalLM"
    LLAMA_CAUSAL_LM = "LlamaForCausalLM"
    DEEPSEEK_MOE = "DeepseekForCausalLM"
    PHI = "PhiForCausalLM"
    QWEN3_5_MULTIMODAL = "qwen3_5"
    UNKNOWN = "unknown"


# Authoritative physical specifications of Dell Precision T5820 accelerators
PHYSICAL_B65_VRAM_MIB: int = 32656  # 31.8906 GiB / 34.24 GB decimal
MAX_ALLOCATABLE_PER_DEVICE_MIB: int = 31023  # Max allocatable memory per device
SYSTEM_RESERVATION_MIB: int = 1024  # OS, Level Zero driver, and kernel reservation
AGGREGATE_VRAM_MIB: int = 65312  # Total physical VRAM across 2 cards


@dataclass(frozen=True)
class HardwareEvaluationResult:

    model_identifier: str
    weights_memory_mib: float
    runtime_overhead_mib: float
    kv_cache_mib: float
    total_memory_required_mib: float
    per_device_limit_mib: float
    fits_single_device: bool
    fits_aggregate: bool
    tensor_parallel_required: int
    pcie_latency_penalty_pct: float
    status: PhysicalCompatibilityStatus
    reason: str
    estimated_concurrency_capacity: int


class PhysicalHardwareCompatibilityEvaluator:
    """Evaluates physical accelerator compatibility, memory scaling, and PCIe bus topology."""

    def __init__(
        self,
        card_count: int = 2,
        vram_per_card_mib: int = PHYSICAL_B65_VRAM_MIB,
        max_allocatable_mib: int = MAX_ALLOCATABLE_PER_DEVICE_MIB,
        system_reservation_mib: int = SYSTEM_RESERVATION_MIB,
    ):
        self.card_count = card_count
        self.vram_per_card_mib = vram_per_card_mib
        self.max_allocatable_mib = max_allocatable_mib
        self.system_reservation_mib = system_reservation_mib

    def estimate_kv_cache_mib(
        self,
        context_length: int,
        num_layers: int,
        kv_heads: int,
        head_dim: int,
        concurrency: int = 1,
    ) -> float:
        """Calculate exact KV cache memory in MiB.
        Formula: 2 (K+V) * num_layers * kv_heads * head_dim * 2 bytes (FP16/BF16) * context_length * concurrency
        """
        bytes_per_token_per_seq = 2 * num_layers * kv_heads * head_dim * 2
        total_bytes = bytes_per_token_per_seq * context_length * concurrency
        return total_bytes / (1024.0 * 1024.0)

    def evaluate_model_compatibility(
        self,
        model_identifier: str,
        weights_size_gb: float,
        architecture: ArchitectureFamily,
        quantization_method: str,
        context_length: int = 32768,
        num_layers: int = 28,
        kv_heads: int = 4,
        head_dim: int = 128,
        concurrency: int = 1,
        is_resident_active: bool = False,
    ) -> HardwareEvaluationResult:
        """Independently evaluate model compatibility against physical B65 device envelope."""

        # 1. Decimal GB to binary MiB conversion: 1 GB = 1024 MB
        weights_mib = weights_size_gb * 1024.0
        overhead_mib = float(self.system_reservation_mib)

        # 2. KV Cache estimation
        kv_mib = self.estimate_kv_cache_mib(
            context_length=context_length,
            num_layers=num_layers,
            kv_heads=kv_heads,
            head_dim=head_dim,
            concurrency=concurrency,
        )

        total_mib = weights_mib + overhead_mib + kv_mib
        usable_single_device = float(self.max_allocatable_mib)

        # 3. Check single device fit
        fits_single = total_mib <= usable_single_device

        # 4. Check aggregate dual-device fit (accounting for TP=2 overhead and per-card reservations)
        usable_aggregate = float(self.card_count * self.max_allocatable_mib)
        # In TP=2, weights are split in half, but overhead is per-card and KV cache is distributed
        tp2_per_card_mib = (weights_mib / 2.0) + overhead_mib + (kv_mib / 2.0)
        fits_aggregate = (tp2_per_card_mib <= usable_single_device) and (total_mib <= usable_aggregate)

        # 5. Check architecture & kernel compatibility on Intel XPU
        supported_quant_methods = ["awq", "awq-4bit", "fp8", "fp16", "int4"]
        is_quant_supported = quantization_method.lower() in supported_quant_methods

        # Calculate max concurrency capacity
        available_kv_headroom = usable_single_device - (weights_mib + overhead_mib)
        if available_kv_headroom > 0 and kv_mib > 0:
            single_seq_kv = kv_mib / concurrency
            estimated_concurrency = max(1, int(available_kv_headroom / single_seq_kv))
        else:
            estimated_concurrency = 0

        # Check for unsupported custom layers (e.g. experimental multimodal/mamba layers)
        if architecture == ArchitectureFamily.QWEN3_5_MULTIMODAL:
            return HardwareEvaluationResult(
                model_identifier=model_identifier,
                weights_memory_mib=weights_mib,
                runtime_overhead_mib=overhead_mib,
                kv_cache_mib=kv_mib,
                total_memory_required_mib=total_mib,
                per_device_limit_mib=usable_single_device,
                fits_single_device=fits_single,
                fits_aggregate=fits_aggregate,
                tensor_parallel_required=1,
                pcie_latency_penalty_pct=0.0,
                status=PhysicalCompatibilityStatus.COMPATIBILITY_UNVERIFIED,
                reason="Custom hybrid linear attention / vision kernels not compiled in vLLM XPU Level Zero runtime.",
                estimated_concurrency_capacity=0,
            )

        if not is_quant_supported:
            return HardwareEvaluationResult(
                model_identifier=model_identifier,
                weights_memory_mib=weights_mib,
                runtime_overhead_mib=overhead_mib,
                kv_cache_mib=kv_mib,
                total_memory_required_mib=total_mib,
                per_device_limit_mib=usable_single_device,
                fits_single_device=fits_single,
                fits_aggregate=fits_aggregate,
                tensor_parallel_required=1,
                pcie_latency_penalty_pct=0.0,
                status=PhysicalCompatibilityStatus.INCOMPATIBLE,
                reason=f"Quantization format '{quantization_method}' has no verified Intel XPU Level Zero kernel.",
                estimated_concurrency_capacity=0,
            )

        # 6. Evaluate resident vs alternative candidate
        if is_resident_active:
            return HardwareEvaluationResult(
                model_identifier=model_identifier,
                weights_memory_mib=weights_mib,
                runtime_overhead_mib=overhead_mib,
                kv_cache_mib=kv_mib,
                total_memory_required_mib=total_mib,
                per_device_limit_mib=usable_single_device,
                fits_single_device=fits_single,
                fits_aggregate=fits_aggregate,
                tensor_parallel_required=1,
                pcie_latency_penalty_pct=0.0,
                status=PhysicalCompatibilityStatus.PHYSICALLY_VERIFIED,
                reason="Resident model actively loaded and serving on physical hardware.",
                estimated_concurrency_capacity=estimated_concurrency,
            )

        # 7. Evaluate single-card candidate fit
        if fits_single:
            return HardwareEvaluationResult(
                model_identifier=model_identifier,
                weights_memory_mib=weights_mib,
                runtime_overhead_mib=overhead_mib,
                kv_cache_mib=kv_mib,
                total_memory_required_mib=total_mib,
                per_device_limit_mib=usable_single_device,
                fits_single_device=True,
                fits_aggregate=True,
                tensor_parallel_required=1,
                pcie_latency_penalty_pct=0.0,
                status=PhysicalCompatibilityStatus.MAINTENANCE_REQUIRED,
                reason="Candidate fits within single B65 GPU (32GB), but physical loading requires authorized worker swap.",
                estimated_concurrency_capacity=estimated_concurrency,
            )

        # 8. Evaluate multi-card TP=2 fit
        if fits_aggregate:
            # Modeled PCIe Gen4 x16 point-to-point latency penalty (35% - 45%)
            pcie_penalty = 38.5
            return HardwareEvaluationResult(
                model_identifier=model_identifier,
                weights_memory_mib=weights_mib,
                runtime_overhead_mib=overhead_mib,
                kv_cache_mib=kv_mib,
                total_memory_required_mib=total_mib,
                per_device_limit_mib=usable_single_device,
                fits_single_device=False,
                fits_aggregate=True,
                tensor_parallel_required=2,
                pcie_latency_penalty_pct=pcie_penalty,
                status=PhysicalCompatibilityStatus.MAINTENANCE_REQUIRED,
                reason="Model exceeds single B65 GPU. Fits across dual GPUs with TP=2, but incurs ~38.5% PCIe bus latency penalty and requires evicting both protected workers.",
                estimated_concurrency_capacity=max(1, estimated_concurrency),
            )

        # 9. Incompatible (Exceeds aggregate memory)
        return HardwareEvaluationResult(
            model_identifier=model_identifier,
            weights_memory_mib=weights_mib,
            runtime_overhead_mib=overhead_mib,
            kv_cache_mib=kv_mib,
            total_memory_required_mib=total_mib,
            per_device_limit_mib=usable_single_device,
            fits_single_device=False,
            fits_aggregate=False,
            tensor_parallel_required=0,
            pcie_latency_penalty_pct=0.0,
            status=PhysicalCompatibilityStatus.INCOMPATIBLE,
            reason=f"Model requires {total_mib:.1f} MiB, exceeding total aggregate system VRAM ({usable_aggregate:.1f} MiB).",
            estimated_concurrency_capacity=0,
        )
