import pytest

from autonomous_engineering.optimization.hardware_eval import (
    HardwareFitStatus,
    ModelHardwareCompatibilityEvaluator,
)


def test_resident_model_compatibility():
    evaluator = ModelHardwareCompatibilityEvaluator()
    assert evaluator.vram_per_card_mb == 32656

    # 30B AWQ ~10.5 GB weights, fits resident on 32656 MiB B65 without swap
    res = evaluator.evaluate_hardware_fit(
        model_identifier="engineering/b0",
        quantization="AWQ-4bit",
        weights_gb=10.5,
        context_window_tokens=32768,
    )
    assert res.fit_status == HardwareFitStatus.COMPATIBLE_RESIDENT
    assert res.requires_resident_model_swap is False
    assert res.maintenance_proposal is None
    assert res.device_vram_limit_mb == 32656.0
    assert res.vram_utilization_pct < 50.0


def test_candidate_requiring_swap_generates_maintenance_proposal():
    evaluator = ModelHardwareCompatibilityEvaluator()

    # 14B model fits within 32,656 MiB, but requires swap from engineering/b0
    res = evaluator.evaluate_hardware_fit(
        model_identifier="Qwen/Qwen2.5-Coder-14B-Instruct",
        quantization="FP8",
        weights_gb=14.0,
        context_window_tokens=32768,
    )
    assert res.fit_status == HardwareFitStatus.COMPATIBLE_REQUIRES_SWAP
    assert res.requires_resident_model_swap is True
    assert res.maintenance_proposal is not None
    assert "10.0.8.5" in res.maintenance_proposal.target_node
    assert res.maintenance_proposal.status == "PENDING_AUTHORIZATION"


def test_oversized_model_incompatible_exceeds_vram():
    evaluator = ModelHardwareCompatibilityEvaluator()

    # 70B FP16 ~140 GB weights exceeds physical 32,656 MiB limit
    res = evaluator.evaluate_hardware_fit(
        model_identifier="Llama-3-70B-Instruct",
        quantization="FP16",
        weights_gb=140.0,
        context_window_tokens=32768,
    )
    assert res.fit_status == HardwareFitStatus.INCOMPATIBLE_EXCEEDS_VRAM
    assert res.fits_aggregate_memory is False


def test_candidate_fits_aggregate_but_exceeds_single_device():
    evaluator = ModelHardwareCompatibilityEvaluator()

    # Model requiring ~40 GiB total memory: exceeds 32,656 MiB on 1 GPU, but fits 65,312 MiB across 2 GPUs
    res = evaluator.evaluate_hardware_fit(
        model_identifier="Qwen/Qwen2.5-Coder-32B-Instruct",
        quantization="FP16",
        weights_gb=32.0,  # ~36.8 GB with overhead + KV cache
        context_window_tokens=32768,
        target_tensor_parallel=1,
    )
    assert res.fit_status == HardwareFitStatus.INCOMPATIBLE_EXCEEDS_VRAM
    assert res.fits_aggregate_memory is True
    assert res.tensor_parallel_recommended == 2

    # When evaluated with TP=2, it fits within per-device limit (requires swap)
    res_tp2 = evaluator.evaluate_hardware_fit(
        model_identifier="Qwen/Qwen2.5-Coder-32B-Instruct",
        quantization="FP16",
        weights_gb=32.0,
        context_window_tokens=32768,
        target_tensor_parallel=2,
    )
    assert res_tp2.fit_status == HardwareFitStatus.COMPATIBLE_REQUIRES_SWAP
    assert res_tp2.tensor_parallel_recommended == 2


def test_raw_weight_fits_but_overhead_and_kv_cache_exceeds():
    evaluator = ModelHardwareCompatibilityEvaluator()

    # Raw weight: 27.5 GB * 1024 = 28,160 MiB (< 32,656 MiB)
    # With 15% runtime overhead: 28,160 * 1.15 = 32,384 MiB
    # With 32k KV cache: + 1,474.5 MiB = 33,858.5 MiB (> 32,656 MiB)
    res = evaluator.evaluate_hardware_fit(
        model_identifier="Borderline-Large-Model",
        quantization="AWQ-8bit",
        weights_gb=27.5,
        context_window_tokens=32768,
    )
    assert res.fit_status == HardwareFitStatus.INCOMPATIBLE_EXCEEDS_VRAM
    assert res.model_size_mb + res.kv_cache_headroom_mb > 32656.0


def test_kv_cache_concurrency_scaling():
    evaluator = ModelHardwareCompatibilityEvaluator()

    # Single sequence fits
    res_seq1 = evaluator.evaluate_hardware_fit(
        model_identifier="engineering/b0",
        quantization="AWQ-4bit",
        weights_gb=25.0,
        context_window_tokens=65536,
        max_concurrent_sequences=1,
    )
    # KV cache = 65.536 * 45 = 2,949 MiB -> Total = 29,440 + 2,949 = 32,389 MiB < 32,656 MiB
    assert res_seq1.fit_status == HardwareFitStatus.COMPATIBLE_RESIDENT

    # Concurrency=2 pushes KV cache to 5,898 MiB -> Total = 35,338 MiB > 32,656 MiB
    res_seq2 = evaluator.evaluate_hardware_fit(
        model_identifier="engineering/b0",
        quantization="AWQ-4bit",
        weights_gb=25.0,
        context_window_tokens=65536,
        max_concurrent_sequences=2,
    )
    assert res_seq2.fit_status == HardwareFitStatus.INCOMPATIBLE_EXCEEDS_VRAM
