import pytest
from autonomous_engineering.physical_qualification.hardware_evaluator import (
    PhysicalHardwareCompatibilityEvaluator,
    PhysicalCompatibilityStatus,
    ArchitectureFamily,
    PHYSICAL_B65_VRAM_MIB,
    MAX_ALLOCATABLE_PER_DEVICE_MIB,
    SYSTEM_RESERVATION_MIB,
)


def test_hardware_evaluator_baseline_limits():
    evaluator = PhysicalHardwareCompatibilityEvaluator()
    assert evaluator.vram_per_card_mib == 32656
    assert evaluator.max_allocatable_mib == 31023
    assert evaluator.system_reservation_mib == 1024
    assert evaluator.card_count == 2


def test_resident_model_compatibility():
    evaluator = PhysicalHardwareCompatibilityEvaluator()
    res = evaluator.evaluate_model_compatibility(
        model_identifier="cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
        weights_size_gb=16.8,
        architecture=ArchitectureFamily.QWEN2_CAUSAL_LM,
        quantization_method="AWQ-4bit",
        context_length=65536,
        is_resident_active=True,
    )
    assert res.status == PhysicalCompatibilityStatus.PHYSICALLY_VERIFIED
    assert res.fits_single_device is True
    assert res.tensor_parallel_required == 1


def test_candidate_7b_single_card_fit():
    evaluator = PhysicalHardwareCompatibilityEvaluator()
    res = evaluator.evaluate_model_compatibility(
        model_identifier="Qwen/Qwen2.5-7B-Instruct-AWQ",
        weights_size_gb=5.3,
        architecture=ArchitectureFamily.QWEN2_CAUSAL_LM,
        quantization_method="AWQ-4bit",
        context_length=32768,
        is_resident_active=False,
    )
    # Fits single card, but requires worker swap
    assert res.status == PhysicalCompatibilityStatus.MAINTENANCE_REQUIRED
    assert res.fits_single_device is True
    assert res.tensor_parallel_required == 1
    assert res.estimated_concurrency_capacity >= 10


def test_candidate_70b_tp2_pcie_penalty():
    evaluator = PhysicalHardwareCompatibilityEvaluator()
    res = evaluator.evaluate_model_compatibility(
        model_identifier="casperhansen/llama-3.3-70b-instruct-awq",
        weights_size_gb=38.6,
        architecture=ArchitectureFamily.LLAMA_CAUSAL_LM,
        quantization_method="AWQ-4bit",
        context_length=65536,
        is_resident_active=False,
    )
    # Exceeds single card, fits aggregate TP=2 with PCIe penalty
    assert res.status == PhysicalCompatibilityStatus.MAINTENANCE_REQUIRED
    assert res.fits_single_device is False
    assert res.fits_aggregate is True
    assert res.tensor_parallel_required == 2
    assert res.pcie_latency_penalty_pct > 30.0


def test_oversized_model_incompatible():
    evaluator = PhysicalHardwareCompatibilityEvaluator()
    res = evaluator.evaluate_model_compatibility(
        model_identifier="Dense-70B-FP16",
        weights_size_gb=140.0,
        architecture=ArchitectureFamily.LLAMA_CAUSAL_LM,
        quantization_method="FP16",
        context_length=32768,
    )
    assert res.status == PhysicalCompatibilityStatus.INCOMPATIBLE
    assert res.fits_single_device is False
    assert res.fits_aggregate is False


def test_unsupported_quantization_rejected():
    evaluator = PhysicalHardwareCompatibilityEvaluator()
    res = evaluator.evaluate_model_compatibility(
        model_identifier="Weird-Model",
        weights_size_gb=10.0,
        architecture=ArchitectureFamily.QWEN2_CAUSAL_LM,
        quantization_method="UNSUPPORTED_QUANT_XYZ",
    )
    assert res.status == PhysicalCompatibilityStatus.INCOMPATIBLE
    assert "no verified Intel XPU Level Zero kernel" in res.reason


def test_custom_multimodal_architecture_unverified():
    evaluator = PhysicalHardwareCompatibilityEvaluator()
    res = evaluator.evaluate_model_compatibility(
        model_identifier="cyankiwi/Qwen3.8-27B-AWQ-INT4",
        weights_size_gb=14.8,
        architecture=ArchitectureFamily.QWEN3_5_MULTIMODAL,
        quantization_method="int4",
    )
    assert res.status == PhysicalCompatibilityStatus.COMPATIBILITY_UNVERIFIED
    assert "linear attention" in res.reason
