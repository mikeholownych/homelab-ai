"""Startup hardware/bandwidth probe, adaptive bypass planner, and loopback worker builder.

Benchmarks host RAM, GPU VRAM, and NVMe random-read bandwidth at startup to decide
whether a model runs purely in VRAM (`bypass_vram`), VRAM+RAM (`bypass_ram`), or
activates three-tier NVMe MoE expert streaming (`nvme_stream` / `dense_spill`).
Enforces strict `127.0.0.1` loopback binding for all worker endpoints.
"""

from __future__ import annotations

import ipaddress
import mmap
import os
import statistics
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .gguf_index import DIRECT_IO_BLOCK_SIZE, MoEModelIndex, align_up
from .io_engine import open_direct_readonly
from .memory_arbiter import HostMemoryArbiter, parse_meminfo_bytes, size_cache_slots_for_budget

PlacementMode = Literal["bypass_vram", "bypass_ram", "nvme_stream", "dense_spill"]
GpuBackend = Literal["sycl", "vulkan", "cpu"]

VULKAN_SYCL_HOST_STAGING_ALIGNMENT = 64 * 1024  # 64 KiB conservative alignment for Vulkan/SYCL imports
DEVICE_STAGING_RING_WEIGHTS = 4  # 4-weight asynchronous H2D ring overlapping compute queues
DEFAULT_VRAM_RESERVE_BYTES = 1024 * 1024 * 1024  # 1 GiB driver/graph reserve per GPU


class SecurityBindError(ValueError):
    """Raised when a worker attempts to bind to a non-loopback address."""


def validate_loopback_bind(host: str) -> str:
    """Enforce strict IPv4 loopback (`127.0.0.1`) binding so workers stay behind orchestrator_gateway."""
    cleaned = (host or "").strip()
    if not cleaned:
        raise SecurityBindError("worker bind host must not be empty; required: 127.0.0.1")
    try:
        addr = ipaddress.ip_address(cleaned)
    except ValueError as exc:
        raise SecurityBindError(f"worker bind host {cleaned!r} must be literal 127.0.0.1") from exc
    if addr != ipaddress.IPv4Address("127.0.0.1"):
        raise SecurityBindError(
            f"worker bind host {cleaned!r} violates loopback-only policy; workers must bind strictly to 127.0.0.1"
        )
    return "127.0.0.1"


@dataclass(frozen=True)
class GpuDeviceInfo:
    """Live per-GPU memory and backend capability snapshot."""

    ordinal: int
    name: str
    backend: GpuBackend
    total_vram_bytes: int
    free_vram_bytes: int
    unified_memory: bool = False
    competing_processes: int = 0


@dataclass(frozen=True)
class NVMeBandwidthPoint:
    """Measured random-read throughput & latency for one (request_bytes, queue_depth) point."""

    request_bytes: int
    queue_depth: int
    median_bps: float
    min_bps: float
    max_bps: float
    p50_us: float
    p99_us: float


@dataclass(frozen=True)
class NVMeDriveProfile:
    """Startup NVMe random-read probe result including knee queue depth."""

    path: str
    direct_io: bool
    points: tuple[NVMeBandwidthPoint, ...]
    knee_queue_depth: int
    effective_read_bps: float


@dataclass(frozen=True)
class HardwareSnapshot:
    """Live machine resources observed at worker startup."""

    cpu_logical_cores: int
    ram_total_bytes: int
    ram_usable_bytes: int
    gpus: tuple[GpuDeviceInfo, ...]
    nvme: NVMeDriveProfile | None = None

    @property
    def total_vram_bytes(self) -> int:
        return sum(g.total_vram_bytes for g in self.gpus)

    @property
    def usable_vram_bytes(self) -> int:
        total = 0
        for g in self.gpus:
            reserve = DEFAULT_VRAM_RESERVE_BYTES if g.competing_processes > 0 else (512 * 1024 * 1024)
            total += max(0, g.free_vram_bytes - reserve)
        return total


@dataclass(frozen=True)
class PlacementPlan:
    """Adaptive three-tier placement and launch configuration derived for a model + hardware pair."""

    mode: PlacementMode
    nvme_streaming_enabled: bool
    backend: GpuBackend
    bind_host: str
    port: int
    total_required_bytes: int
    usable_vram_bytes: int
    usable_ram_bytes: int
    vram_dense_bytes: int
    ram_expert_cache_bytes: int
    ram_expert_cache_slots: int
    decode_threads: int
    prefill_threads: int
    io_cpus: tuple[int, ...]
    gpu_staging_alignment_bytes: int
    device_staging_ring_slots: int
    dense_layer_order: tuple[int, ...] = ()
    llama_args: tuple[str, ...] = ()
    llama_env: dict[str, str] = field(default_factory=dict)
    rationale: str = ""


def compute_knee_queue_depth(points: list[NVMeBandwidthPoint]) -> tuple[int, float]:
    """Return (knee_qd, effective_bps): smallest QD whose max run >= min run of fastest QD."""
    if not points:
        return 1, 0.0
    ordered = sorted(points, key=lambda p: p.queue_depth)
    fastest = max(ordered, key=lambda p: p.median_bps)
    for pt in ordered:
        if pt.max_bps >= fastest.min_bps:
            return pt.queue_depth, pt.median_bps
    return fastest.queue_depth, fastest.median_bps


def probe_nvme_random_read(
    target_path: Path | str,
    *,
    request_sizes: tuple[int, ...] = (64 * 1024, 256 * 1024),
    queue_depths: tuple[int, ...] = (1, 2, 4, 8),
    reads_per_point: int = 16,
    repeats: int = 2,
    strict_direct: bool = False,
    temp_probe_bytes: int = 8 * 1024 * 1024,
) -> NVMeDriveProfile:
    """Non-destructively benchmark random 4 KiB-aligned reads on the target NVMe file or directory."""
    path = Path(target_path)
    cleanup_file: Path | None = None
    if path.is_dir():
        probe_file = Path(tempfile.mkstemp(prefix=".homelab-nvme-probe-", dir=str(path))[1])
        cleanup_file = probe_file
        size_aligned = align_up(max(temp_probe_bytes, max(request_sizes) * 4), DIRECT_IO_BLOCK_SIZE)
        with open(probe_file, "wb") as fh:
            chunk = os.urandom(min(1024 * 1024, size_aligned))
            written = 0
            while written < size_aligned:
                take = min(len(chunk), size_aligned - written)
                fh.write(chunk[:take])
                written += take
            fh.flush()
            os.fsync(fh.fileno())
        measure_path = probe_file
    else:
        measure_path = path

    points: list[NVMeBandwidthPoint] = []
    direct_used = False
    try:
        fd, direct_used = open_direct_readonly(measure_path, strict_direct=strict_direct)
        try:
            file_size = os.fstat(fd).st_size
            for req_bytes in request_sizes:
                req_aligned = align_up(req_bytes, DIRECT_IO_BLOCK_SIZE)
                max_blocks = max(1, (file_size - req_aligned) // DIRECT_IO_BLOCK_SIZE)
                for qd in queue_depths:
                    run_bps: list[float] = []
                    latencies_us: list[float] = []
                    for rep in range(max(1, repeats)):
                        # Deterministic LCG stride across aligned blocks to avoid sequential prefetch bias.
                        offsets = [
                            (((i * 2654435761 + rep * 40503) % max_blocks) * DIRECT_IO_BLOCK_SIZE)
                            for i in range(max(1, reads_per_point))
                        ]

                        def _do_read(off: int) -> float:
                            buf = mmap.mmap(-1, req_aligned)
                            try:
                                view = memoryview(buf)
                                t0 = time.monotonic()
                                nread = os.preadv(fd, [view], off)
                                if nread <= 0:
                                    return 1e-6
                                return max(1e-9, time.monotonic() - t0)
                            finally:
                                view.release()
                                buf.close()

                        t_wall = time.monotonic()
                        with ThreadPoolExecutor(max_workers=qd) as pool:
                            durs = list(pool.map(_do_read, offsets))
                        elapsed = max(1e-9, time.monotonic() - t_wall)
                        run_bps.append((req_aligned * len(offsets)) / elapsed)
                        latencies_us.extend(d * 1e6 for d in durs)

                    lat_sorted = sorted(latencies_us)
                    p50 = lat_sorted[len(lat_sorted) // 2]
                    p99 = lat_sorted[min(len(lat_sorted) - 1, int(len(lat_sorted) * 0.99))]
                    points.append(
                        NVMeBandwidthPoint(
                            request_bytes=req_aligned,
                            queue_depth=qd,
                            median_bps=statistics.median(run_bps),
                            min_bps=min(run_bps),
                            max_bps=max(run_bps),
                            p50_us=p50,
                            p99_us=p99,
                        )
                    )
        finally:
            os.close(fd)
    finally:
        if cleanup_file is not None and cleanup_file.exists():
            cleanup_file.unlink(missing_ok=True)

    # Select knee from largest request size (closest to MoE expert role reads).
    largest_size = max(p.request_bytes for p in points) if points else 0
    largest_points = [p for p in points if p.request_bytes == largest_size]
    knee_qd, eff_bps = compute_knee_queue_depth(largest_points)
    return NVMeDriveProfile(
        path=str(path),
        direct_io=direct_used,
        points=tuple(points),
        knee_queue_depth=knee_qd,
        effective_read_bps=eff_bps,
    )


def bit_reversed_layer_order(n_layers: int) -> tuple[int, ...]:
    """Order dense layers by bit-reversed index so VRAM/RAM/NVMe prefixes spread evenly across depth."""
    if n_layers <= 0:
        return ()
    bits = (n_layers - 1).bit_length()

    def rev(val: int) -> int:
        out = 0
        for b in range(bits):
            out = (out << 1) | ((val >> b) & 1)
        return out

    return tuple(sorted(range(n_layers), key=rev))


def probe_live_host_snapshot(
    *,
    gpus: tuple[GpuDeviceInfo, ...],
    arbiter: HostMemoryArbiter | None = None,
    nvme_profile: NVMeDriveProfile | None = None,
) -> HardwareSnapshot:
    """Assemble live host CPU, dual-term RAM headroom, and GPU memory snapshot."""
    arb = arbiter or HostMemoryArbiter()
    room = arb.measure()
    meminfo_raw = arb._reader("/proc/meminfo") or ""
    meminfo = parse_meminfo_bytes(meminfo_raw)
    ram_total = meminfo.get("MemTotal", room.system_available_bytes)
    cpu_cores = max(1, os.cpu_count() or 1)
    return HardwareSnapshot(
        cpu_logical_cores=cpu_cores,
        ram_total_bytes=ram_total,
        ram_usable_bytes=room.effective_surplus_bytes,
        gpus=gpus,
        nvme=nvme_profile,
    )


def plan_model_placement(
    model_index: MoEModelIndex,
    hardware: HardwareSnapshot,
    *,
    bind_host: str = "127.0.0.1",
    port: int = 8001,
    backend: GpuBackend = "sycl",
    context_tokens: int = 65536,
    kv_cache_bytes_estimate: int | None = None,
    compute_scratch_bytes: int = 2 * 1024 * 1024 * 1024,
) -> PlacementPlan:
    """Compute adaptive three-tier placement and llama.cpp worker launch arguments."""
    verified_host = validate_loopback_bind(bind_host)

    if kv_cache_bytes_estimate is None:
        # Conservative FP16 KV estimate: ~256 KiB/token scaled by layer count relative to 64 layers.
        layer_scale = max(1, model_index.n_layers) / 64.0
        kv_bytes = int(context_tokens * 256 * 1024 * layer_scale)
    else:
        kv_bytes = max(0, int(kv_cache_bytes_estimate))

    total_required = model_index.total_tensor_bytes + kv_bytes + compute_scratch_bytes
    usable_vram = hardware.usable_vram_bytes
    usable_ram = hardware.ram_usable_bytes

    # Thread pool sizing: reserve 1-2 highest logical CPUs for direct NVMe I/O & completion interrupts.
    cores = max(1, hardware.cpu_logical_cores)
    if cores >= 4:
        io_cpus = (cores - 1,)
        prefill_threads = cores - 1
        decode_threads = max(2, min(cores - 1, max(4, cores // 2)))
    else:
        io_cpus = (cores - 1,)
        prefill_threads = max(1, cores - 1)
        decode_threads = max(1, cores - 1)

    base_args = [
        "--host",
        verified_host,
        "--port",
        str(port),
        "-c",
        str(context_tokens),
        "-t",
        str(decode_threads),
        "-tb",
        str(prefill_threads),
        "-fa",
        "on",
        "--metrics",
    ]
    env: dict[str, str] = {}
    if backend == "sycl":
        if len(hardware.gpus) >= 2:
            ordinals = ",".join(str(g.ordinal) for g in hardware.gpus)
            env["ONEAPI_DEVICE_SELECTOR"] = f"level_zero:{ordinals}"
        elif len(hardware.gpus) == 1:
            env["ONEAPI_DEVICE_SELECTOR"] = f"level_zero:{hardware.gpus[0].ordinal}"
        env["SYCL_PI_LEVEL_ZERO_USE_IMMEDIATE_COMMANDLISTS"] = "1"
    elif backend == "vulkan":
        if hardware.gpus:
            env["GGML_VK_VISIBLE_DEVICES"] = ",".join(str(g.ordinal) for g in hardware.gpus)

    if len(hardware.gpus) >= 2:
        split_weights = ",".join(str(max(1, g.free_vram_bytes // (1024 * 1024 * 1024))) for g in hardware.gpus)
        base_args.extend(["--split-mode", "layer", "--tensor-split", split_weights])

    # Mode 1: Full VRAM resident -> bypass NVMe streaming and RAM expert cache completely.
    if total_required <= usable_vram:
        args = [*base_args, "-ngl", "999"]
        return PlacementPlan(
            mode="bypass_vram",
            nvme_streaming_enabled=False,
            backend=backend,
            bind_host=verified_host,
            port=port,
            total_required_bytes=total_required,
            usable_vram_bytes=usable_vram,
            usable_ram_bytes=usable_ram,
            vram_dense_bytes=model_index.total_tensor_bytes,
            ram_expert_cache_bytes=0,
            ram_expert_cache_slots=0,
            decode_threads=decode_threads,
            prefill_threads=prefill_threads,
            io_cpus=io_cpus,
            gpu_staging_alignment_bytes=VULKAN_SYCL_HOST_STAGING_ALIGNMENT,
            device_staging_ring_slots=DEVICE_STAGING_RING_WEIGHTS,
            llama_args=tuple(args),
            llama_env=env,
            rationale=(
                f"total_required ({total_required} B) <= usable_vram ({usable_vram} B); "
                "bypassing NVMe streaming for full VRAM residency"
            ),
        )

    # Mode 2: Fits in combined VRAM + RAM -> hybrid GPU/CPU memory residency, bypass NVMe streaming.
    if total_required <= usable_vram + usable_ram:
        vram_budget = min(model_index.total_tensor_bytes, max(0, usable_vram - kv_bytes - compute_scratch_bytes))
        args = [*base_args, "-ngl", "99"]
        if model_index.is_moe:
            args.append("--cpu-moe")
        return PlacementPlan(
            mode="bypass_ram",
            nvme_streaming_enabled=False,
            backend=backend,
            bind_host=verified_host,
            port=port,
            total_required_bytes=total_required,
            usable_vram_bytes=usable_vram,
            usable_ram_bytes=usable_ram,
            vram_dense_bytes=vram_budget,
            ram_expert_cache_bytes=max(0, model_index.total_tensor_bytes - vram_budget),
            ram_expert_cache_slots=0,
            decode_threads=decode_threads,
            prefill_threads=prefill_threads,
            io_cpus=io_cpus,
            gpu_staging_alignment_bytes=VULKAN_SYCL_HOST_STAGING_ALIGNMENT,
            device_staging_ring_slots=DEVICE_STAGING_RING_WEIGHTS,
            llama_args=tuple(args),
            llama_env=env,
            rationale=(
                f"total_required ({total_required} B) exceeds usable_vram ({usable_vram} B) "
                f"but fits within VRAM+RAM ({usable_vram + usable_ram} B); bypassing NVMe streaming"
            ),
        )

    # Mode 3: Exceeds VRAM + RAM and has routed MoE experts -> activate three-tier NVMe streaming.
    if model_index.is_moe:
        slot_stride = model_index.max_expert_slot_bytes
        ram_slots = size_cache_slots_for_budget(
            usable_ram,
            slot_stride,
            n_layers=len(model_index.routed_layers),
            n_experts=model_index.n_experts,
        )
        ram_cache_bytes = ram_slots * slot_stride
        args = [*base_args, "-ngl", "99", "--cpu-moe", "--no-mmap"]
        env["HOMELAB_AI_NVME_MOE_STREAM"] = "1"
        env["HOMELAB_AI_NVME_MOE_CACHE_BYTES"] = str(ram_cache_bytes)
        env["HOMELAB_AI_NVME_MOE_IO_CPUS"] = ",".join(str(c) for c in io_cpus)
        env["HOMELAB_AI_GPU_STAGING_ALIGN_BYTES"] = str(VULKAN_SYCL_HOST_STAGING_ALIGNMENT)
        env["HOMELAB_AI_GPU_STAGING_RING_SLOTS"] = str(DEVICE_STAGING_RING_WEIGHTS)
        return PlacementPlan(
            mode="nvme_stream",
            nvme_streaming_enabled=True,
            backend=backend,
            bind_host=verified_host,
            port=port,
            total_required_bytes=total_required,
            usable_vram_bytes=usable_vram,
            usable_ram_bytes=usable_ram,
            vram_dense_bytes=min(model_index.dense_bytes, max(0, usable_vram - kv_bytes)),
            ram_expert_cache_bytes=ram_cache_bytes,
            ram_expert_cache_slots=ram_slots,
            decode_threads=decode_threads,
            prefill_threads=prefill_threads,
            io_cpus=io_cpus,
            gpu_staging_alignment_bytes=VULKAN_SYCL_HOST_STAGING_ALIGNMENT,
            device_staging_ring_slots=DEVICE_STAGING_RING_WEIGHTS,
            llama_args=tuple(args),
            llama_env=env,
            rationale=(
                f"MoE model ({total_required} B) exceeds VRAM+RAM ({usable_vram + usable_ram} B); "
                f"activating three-tier NVMe streaming with {ram_slots} Tier-1 RAM slots ({ram_cache_bytes} B)"
            ),
        )

    # Mode 4: Dense model exceeding VRAM + RAM -> bit-reversed dense layer spill across tiers.
    layer_order = bit_reversed_layer_order(model_index.n_layers)
    args = [*base_args, "-ngl", "99", "--no-mmap"]
    env["HOMELAB_AI_NVME_DENSE_SPILL"] = "1"
    env["HOMELAB_AI_GPU_STAGING_RING_SLOTS"] = str(DEVICE_STAGING_RING_WEIGHTS)
    return PlacementPlan(
        mode="dense_spill",
        nvme_streaming_enabled=True,
        backend=backend,
        bind_host=verified_host,
        port=port,
        total_required_bytes=total_required,
        usable_vram_bytes=usable_vram,
        usable_ram_bytes=usable_ram,
        vram_dense_bytes=min(model_index.total_tensor_bytes, max(0, usable_vram - kv_bytes)),
        ram_expert_cache_bytes=0,
        ram_expert_cache_slots=0,
        decode_threads=decode_threads,
        prefill_threads=prefill_threads,
        io_cpus=io_cpus,
        gpu_staging_alignment_bytes=VULKAN_SYCL_HOST_STAGING_ALIGNMENT,
        device_staging_ring_slots=DEVICE_STAGING_RING_WEIGHTS,
        dense_layer_order=layer_order,
        llama_args=tuple(args),
        llama_env=env,
        rationale=(
            f"Dense model ({total_required} B) exceeds VRAM+RAM ({usable_vram + usable_ram} B); "
            "activating bit-reversed dense layer spill"
        ),
    )
