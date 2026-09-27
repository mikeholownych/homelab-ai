import pytest

from autonomous_engineering.resources.manager import (
    InsufficientVRAMError,
    ModelSwapProhibitedError,
    PhysicalInferenceResourceManager,
    WorkerHealthStatus,
    WorkerUnavailableError,
)


def test_t5820_cluster_topology_initialized():
    mgr = PhysicalInferenceResourceManager()
    workers = mgr.list_workers()
    assert len(workers) == 2

    w1 = mgr.get_worker("vllm-xpu-tp1-worker1")
    assert w1.gpu_index == 0
    assert w1.resident_model_identifier == "engineering/b0"
    assert w1.is_protected_resident is True

    w2 = mgr.get_worker("vllm-xpu-tp1-worker2")
    assert w2.gpu_index == 1
    assert w2.resident_model_identifier == "engineering/b0"
    assert w2.is_protected_resident is True


def test_worker_allocation_least_loaded():
    mgr = PhysicalInferenceResourceManager()

    # Allocate first worker
    w_first = mgr.allocate_worker_for_request("engineering/b0", required_context_tokens=16384)
    assert w_first.active_requests == 1

    # Allocate second worker - should pick the other idle worker
    w_second = mgr.allocate_worker_for_request("engineering/b0", required_context_tokens=16384)
    assert w_second.worker_id != w_first.worker_id
    assert w_second.active_requests == 1

    # Release first worker
    mgr.release_worker_request(w_first.worker_id)
    assert w_first.active_requests == 0


def test_model_swap_prohibited_on_protected_resident():
    mgr = PhysicalInferenceResourceManager(allow_model_swaps=False)

    with pytest.raises(ModelSwapProhibitedError):
        mgr.attempt_model_swap(
            worker_id="vllm-xpu-tp1-worker1",
            target_model="unauthorized/llama3",
            target_revision="v1",
            required_vram_bytes=1000000,
        )


def test_insufficient_vram_rejection_even_if_swaps_allowed():
    mgr = PhysicalInferenceResourceManager(allow_model_swaps=True)

    # 40 GiB exceeds the 31.89 GiB physical capacity of a B65 GPU
    excessive_vram = 45 * 1024 * 1024 * 1024

    with pytest.raises(InsufficientVRAMError):
        mgr.attempt_model_swap(
            worker_id="vllm-xpu-tp1-worker1",
            target_model="huge/model",
            target_revision="v1",
            required_vram_bytes=excessive_vram,
        )
