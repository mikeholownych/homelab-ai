import pytest

from autonomous_engineering.optimization.hardware_eval import (
    HardwareFitStatus,
    ModelHardwareCompatibilityEvaluator,
)


def test_resident_model_compatibility():
    evaluator = ModelHardwareCompatibilityEvaluator(
        vram_per_card_mb=16384,
        cards_count=2,
        current_resident_model="engineering/b0",
    )

    # 30B AWQ ~15 GB weights total, fits resident without swap
    res = evaluator.evaluate_hardware_fit(
        model_identifier="engineering/b0",
        quantization="AWQ-4bit",
        weights_gb=10.5,
        context_window_tokens=32768,
    )
    assert res.fit_status == HardwareFitStatus.COMPATIBLE_RESIDENT
    assert res.requires_resident_model_swap is False
    assert res.maintenance_proposal is None


def test_candidate_requiring_swap_generates_maintenance_proposal():
    evaluator = ModelHardwareCompatibilityEvaluator(
        vram_per_card_mb=16384,
        cards_count=2,
        current_resident_model="engineering/b0",
    )

    # 14B model fits within 16GB VRAM, but requires swap
    res = evaluator.evaluate_hardware_fit(
        model_identifier="Qwen/Qwen2.5-Coder-14B-Instruct",
        quantization="FP8",
        weights_gb=9.0,
        context_window_tokens=32768,
    )
    assert res.fit_status == HardwareFitStatus.COMPATIBLE_REQUIRES_SWAP
    assert res.requires_resident_model_swap is True
    assert res.maintenance_proposal is not None
    assert "10.0.8.5" in res.maintenance_proposal.target_node
    assert res.maintenance_proposal.status == "PENDING_AUTHORIZATION"


def test_oversized_model_incompatible():
    evaluator = ModelHardwareCompatibilityEvaluator(
        vram_per_card_mb=16384,
        cards_count=2,
        current_resident_model="engineering/b0",
    )

    # 70B FP16 ~140 GB weights exceeds 16GB
    res = evaluator.evaluate_hardware_fit(
        model_identifier="Llama-3-70B-Instruct",
        quantization="FP16",
        weights_gb=70.0,
        context_window_tokens=32768,
    )
    assert res.fit_status == HardwareFitStatus.INCOMPATIBLE_EXCEEDS_VRAM
