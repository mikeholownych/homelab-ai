"""Direct-I/O NVMe expert streaming engine with reusable 4 KiB-aligned staging ring.

Coordinates Tier-0 VRAM residency checks, Tier-1 bounded RAM expert caching,
and Tier-2 unbuffered aligned direct I/O (O_DIRECT / pread worker ring) with
explicit drain-before-free barriers, speculative next-layer prefetch evaluation,
and Prometheus telemetry hooks.
"""

from __future__ import annotations

import errno
import mmap
import os
import stat
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .gguf_index import (
    DIRECT_IO_BLOCK_SIZE,
    EXPERT_ROLES,
    ByteRange,
    DirectReadExtent,
    MoEModelIndex,
    align_up,
)
from .memory_arbiter import ExpertCache, ExpertCacheKey, HostMemoryArbiter, size_cache_slots_for_budget

if TYPE_CHECKING:
    from orchestrator_runtime.metrics import MetricsRegistry

DEFAULT_STAGING_RING_DEPTH = 8  # 8 experts * 3 roles = 24 concurrent role reads
MADV_NOHUGEPAGE = 15  # Linux asm-generic/mman-common.h


class DirectIOError(OSError):
    """Raised when direct unbuffered storage I/O fails and fallback is disallowed."""


def open_direct_readonly(
    path: Path | str,
    *,
    strict_direct: bool = True,
) -> tuple[int, bool]:
    """Open a regular model file read-only with O_DIRECT | O_CLOEXEC.

    Returns (fd, is_direct). When `strict_direct=True`, failures opening with
    O_DIRECT propagate explicitly rather than silently falling back to page-cached I/O.
    """
    base_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    o_direct = getattr(os, "O_DIRECT", 0)

    is_direct = False
    fd = -1
    if o_direct:
        try:
            fd = os.open(str(path), base_flags | o_direct)
            is_direct = True
        except OSError as exc:
            if strict_direct or exc.errno not in (errno.EINVAL, errno.EOPNOTSUPP, errno.EPERM):
                raise DirectIOError(exc.errno or errno.EIO, f"O_DIRECT open failed for {path}: {exc.strerror}") from exc

    if fd < 0:
        if strict_direct and o_direct:
            raise DirectIOError(errno.EINVAL, f"O_DIRECT unavailable for {path}")
        fd = os.open(str(path), base_flags)
        is_direct = False

    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise DirectIOError(errno.EINVAL, f"expert source is not a regular file: {path}")
    except Exception:
        os.close(fd)
        raise

    return fd, is_direct


def advise_drop_page_cache(fd: int, ranges: tuple[ByteRange, ...]) -> int:
    """Advise the Linux kernel to drop page-cache pages for coalesced expert byte ranges."""
    fadvise = getattr(os, "posix_fadvise", None)
    dontneed = getattr(os, "POSIX_FADV_DONTNEED", None)
    if fadvise is None or dontneed is None:
        return 0
    dropped = 0
    for byte_range in ranges:
        length = byte_range.end - byte_range.start
        if length > 0:
            try:
                fadvise(fd, byte_range.start, length, dontneed)
                dropped += length
            except OSError:
                continue
    return dropped


class AlignedStagingRing:
    """Fixed-depth pool of 4 KiB-aligned reusable buffers for direct NVMe reads."""

    def __init__(self, depth: int, slot_bytes: int) -> None:
        if depth <= 0 or slot_bytes <= 0:
            raise ValueError("staging ring depth and slot_bytes must be positive")
        self.depth = int(depth)
        self.slot_bytes = align_up(int(slot_bytes), DIRECT_IO_BLOCK_SIZE)
        self._lock = threading.Lock()
        self._available = threading.Condition(self._lock)
        self._buffers: list[mmap.mmap] = []
        self._free_indices: list[int] = []
        self._closed = False

        for idx in range(self.depth):
            buf = mmap.mmap(-1, self.slot_bytes, prot=mmap.PROT_READ | mmap.PROT_WRITE)
            madvise = getattr(buf, "madvise", None)
            if callable(madvise):
                try:
                    madvise(MADV_NOHUGEPAGE)
                except OSError:
                    pass
            self._buffers.append(buf)
            self._free_indices.append(idx)

    def acquire(self) -> tuple[int, mmap.mmap]:
        with self._available:
            while not self._free_indices and not self._closed:
                self._available.wait()
            if self._closed:
                raise RuntimeError("staging ring is closed")
            idx = self._free_indices.pop()
            return idx, self._buffers[idx]

    def release(self, idx: int) -> None:
        with self._available:
            if idx not in self._free_indices:
                self._free_indices.append(idx)
                self._available.notify()

    def close(self) -> None:
        """Close all staging mappings only after every slot has been returned."""
        with self._available:
            self._closed = True
            self._available.notify_all()
            if len(self._free_indices) != self.depth:
                raise RuntimeError(
                    f"cannot close staging ring with {self.depth - len(self._free_indices)} in-flight slots"
                )
            for buf in self._buffers:
                buf.close()
            self._buffers.clear()
            self._free_indices.clear()


def should_issue_prefetch(
    hit_probability: float,
    estimated_read_us: float,
    layer_gap_us: float,
) -> bool:
    """Speculative prefetch admission rule: P(hit) > remaining_read_fraction at layer boundary."""
    if hit_probability <= 0.0 or estimated_read_us <= 0.0 or layer_gap_us <= 0.0:
        return False
    if layer_gap_us >= estimated_read_us:
        return True
    remaining_fraction = (estimated_read_us - layer_gap_us) / estimated_read_us
    return hit_probability > remaining_fraction


@dataclass
class ExpertFetchResult:
    """Outcome of resolving one routed expert across VRAM -> RAM -> NVMe tiers."""

    layer_id: int
    expert_idx: int
    tier: str  # "vram" | "ram" | "nvme"
    payload: dict[str, bytes]
    read_bytes: int
    read_latency_seconds: float
    role_latencies_seconds: dict[str, float] = field(default_factory=dict)


class NVMeMoEStreamEngine:
    """Three-tier MoE expert streamer over indexed GGUF extents with Prometheus instrumentation."""

    def __init__(
        self,
        model_index: MoEModelIndex,
        *,
        worker_id: str,
        model_name: str,
        cache: ExpertCache | None = None,
        arbiter: HostMemoryArbiter | None = None,
        metrics: MetricsRegistry | None = None,
        strict_direct: bool = True,
        ring_depth: int = DEFAULT_STAGING_RING_DEPTH,
        io_workers: int = 4,
        vram_resident_experts: set[tuple[int, int]] | None = None,
    ) -> None:
        if not model_index.is_moe:
            raise ValueError("NVMeMoEStreamEngine requires an indexed MoE model with routed layers")
        self.model_index = model_index
        self.worker_id = worker_id
        self.model_name = model_name
        self.metrics = metrics
        self.strict_direct = strict_direct
        self._vram_resident: set[tuple[int, int]] = set(vram_resident_experts or ())
        self._lock = threading.Lock()
        self._closed = False
        self._inflight_futures: set[Future[Any]] = set()
        self._ewma_bandwidth_bps: float = 0.0
        self._ewma_io_wait_ratio: float = 0.0

        # Open shard descriptors with O_DIRECT and drop OS page cache for cold expert ranges.
        self._fds: list[int] = []
        self.direct_io_active: list[bool] = []
        try:
            for idx, shard in enumerate(model_index.shards):
                fd, is_direct = open_direct_readonly(shard.path, strict_direct=strict_direct)
                self._fds.append(fd)
                self.direct_io_active.append(is_direct)
                advise_drop_page_cache(fd, model_index.coalesced_expert_ranges.get(idx, ()))
        except Exception:
            for fd in self._fds:
                os.close(fd)
            self._fds.clear()
            raise

        max_role = max(model_index.max_role_read_bytes.values(), default=DIRECT_IO_BLOCK_SIZE)
        self._ring = AlignedStagingRing(depth=max(1, ring_depth * len(EXPERT_ROLES)), slot_bytes=max_role)
        self._executor = ThreadPoolExecutor(max_workers=max(1, io_workers), thread_name_prefix="nvme-moe-io")

        if cache is not None:
            self.cache = cache
        else:
            slot_stride = model_index.max_expert_slot_bytes
            budget = arbiter.measure().effective_surplus_bytes if arbiter is not None else 64 * 1024 * 1024
            slots = size_cache_slots_for_budget(
                budget,
                slot_stride,
                n_layers=len(model_index.routed_layers),
                n_experts=model_index.n_experts,
            )
            self.cache = ExpertCache(max_slots=slots, slot_stride_bytes=slot_stride, arbiter=arbiter)

        # Initialize zero-safe Prometheus series so dashboards never render "No data" when idle.
        if self.metrics is not None:
            self.metrics.nvme_stream_bandwidth_bytes_per_sec.set(
                0.0, worker_id=self.worker_id, model=self.model_name
            )
            self.metrics.nvme_io_wait_ratio.set(
                0.0, worker_id=self.worker_id, model=self.model_name
            )
            self.metrics.moe_streaming_mode.set(
                1.0, worker_id=self.worker_id, mode="nvme_stream", model=self.model_name
            )

    def _read_extent_direct(self, extent: DirectReadExtent) -> tuple[bytes, float]:
        """Execute a single 4 KiB-aligned direct read into a reusable aligned mmap staging buffer."""
        fd = self._fds[extent.source_idx]
        slot_idx, buf = self._ring.acquire()
        t0 = time.monotonic()
        try:
            view = memoryview(buf)[: extent.aligned_bytes]
            nread = os.preadv(fd, [view], extent.aligned_offset)
            if nread < extent.data_offset + extent.logical_bytes:
                raise DirectIOError(
                    errno.EIO,
                    f"short NVMe read at offset {extent.aligned_offset}: "
                    f"got {nread} bytes, need {extent.data_offset + extent.logical_bytes}",
                )
            payload = bytes(view[extent.data_offset : extent.data_offset + extent.logical_bytes])
            elapsed = max(1e-9, time.monotonic() - t0)
            return payload, elapsed
        finally:
            view.release()
            self._ring.release(slot_idx)

    def fetch_expert(
        self,
        layer_id: int,
        expert_idx: int,
        *,
        layer_wall_seconds: float | None = None,
    ) -> ExpertFetchResult:
        """Resolve an expert from Tier-0 VRAM, Tier-1 RAM cache, or Tier-2 NVMe direct I/O."""
        if self._closed:
            raise RuntimeError("NVMeMoEStreamEngine is closed")

        key = ExpertCacheKey.make(layer_id, expert_idx, self.model_index.shards)

        # Tier 0: VRAM resident expert check.
        if (layer_id, expert_idx) in self._vram_resident:
            if self.metrics is not None:
                self.metrics.moe_expert_cache_hits_total.inc(
                    worker_id=self.worker_id, tier="vram", model=self.model_name
                )
            return ExpertFetchResult(
                layer_id=layer_id,
                expert_idx=expert_idx,
                tier="vram",
                payload={},
                read_bytes=0,
                read_latency_seconds=0.0,
            )

        # Tier 1: Host RAM expert cache check.
        cached = self.cache.lookup(key)
        if cached is not None:
            if self.metrics is not None:
                self.metrics.moe_expert_cache_hits_total.inc(
                    worker_id=self.worker_id, tier="ram", model=self.model_name
                )
            return ExpertFetchResult(
                layer_id=layer_id,
                expert_idx=expert_idx,
                tier="ram",
                payload=cached,
                read_bytes=0,
                read_latency_seconds=0.0,
            )

        # Tier 2: Direct unbuffered NVMe stream across up, gate, down roles concurrently.
        layout = self.model_index.routed_layers[layer_id]
        t_start = time.monotonic()
        futures: dict[str, Future[tuple[bytes, float]]] = {}
        total_aligned_bytes = 0
        for role in EXPERT_ROLES:
            extent = layout.extent_for(expert_idx, role)
            total_aligned_bytes += extent.aligned_bytes
            fut = self._executor.submit(self._read_extent_direct, extent)
            with self._lock:
                self._inflight_futures.add(fut)
            futures[role] = fut

        payload: dict[str, bytes] = {}
        role_latencies: dict[str, float] = {}
        try:
            for role, fut in futures.items():
                data, role_s = fut.result()
                payload[role] = data
                role_latencies[role] = role_s
        finally:
            with self._lock:
                for fut in futures.values():
                    self._inflight_futures.discard(fut)

        total_latency = max(1e-9, time.monotonic() - t_start)
        self.cache.put(key, payload)

        # Update rolling EWMA bandwidth and I/O wait telemetry.
        inst_bps = total_aligned_bytes / total_latency
        with self._lock:
            self._ewma_bandwidth_bps = (
                inst_bps if self._ewma_bandwidth_bps <= 0 else 0.7 * self._ewma_bandwidth_bps + 0.3 * inst_bps
            )
            if layer_wall_seconds is not None and layer_wall_seconds > 0:
                inst_wait = min(1.0, total_latency / layer_wall_seconds)
                self._ewma_io_wait_ratio = (
                    inst_wait if self._ewma_io_wait_ratio <= 0 else 0.7 * self._ewma_io_wait_ratio + 0.3 * inst_wait
                )
            bw = self._ewma_bandwidth_bps
            io_wait = self._ewma_io_wait_ratio

        if self.metrics is not None:
            self.metrics.moe_expert_cache_misses_total.inc(
                worker_id=self.worker_id, model=self.model_name
            )
            for role, rlat in role_latencies.items():
                self.metrics.nvme_expert_read_latency_seconds.observe(
                    rlat, worker_id=self.worker_id, role=role, model=self.model_name
                )
            self.metrics.nvme_expert_read_latency_seconds.observe(
                total_latency, worker_id=self.worker_id, role="expert", model=self.model_name
            )
            self.metrics.nvme_stream_bandwidth_bytes_per_sec.set(
                bw, worker_id=self.worker_id, model=self.model_name
            )
            self.metrics.nvme_io_wait_ratio.set(
                io_wait, worker_id=self.worker_id, model=self.model_name
            )

        return ExpertFetchResult(
            layer_id=layer_id,
            expert_idx=expert_idx,
            tier="nvme",
            payload=payload,
            read_bytes=total_aligned_bytes,
            read_latency_seconds=total_latency,
            role_latencies_seconds=role_latencies,
        )

    def prefetch_async(
        self,
        layer_id: int,
        expert_idx: int,
        *,
        hit_probability: float,
        estimated_read_us: float,
        layer_gap_us: float,
    ) -> Future[ExpertFetchResult] | None:
        """Conditionally schedule an async Tier-2 prefetch if expected gain exceeds stall penalty."""
        if self._closed or not should_issue_prefetch(hit_probability, estimated_read_us, layer_gap_us):
            return None
        key = ExpertCacheKey.make(layer_id, expert_idx, self.model_index.shards)
        if (layer_id, expert_idx) in self._vram_resident or key in self.cache._slots:
            return None
        fut = self._executor.submit(self.fetch_expert, layer_id, expert_idx)
        with self._lock:
            self._inflight_futures.add(fut)
        fut.add_done_callback(lambda f: self._discard_future(f))
        return fut

    def _discard_future(self, fut: Future[Any]) -> None:
        with self._lock:
            self._inflight_futures.discard(fut)

    def drain(self) -> None:
        """Wait for every in-flight NVMe read to finish before releasing buffers or closing."""
        while True:
            with self._lock:
                pending = list(self._inflight_futures)
            if not pending:
                break
            for fut in pending:
                try:
                    fut.result()
                except Exception:
                    pass

    @property
    def bandwidth_bytes_per_sec(self) -> float:
        with self._lock:
            return self._ewma_bandwidth_bps

    @property
    def io_wait_ratio(self) -> float:
        with self._lock:
            return self._ewma_io_wait_ratio

    def __enter__(self) -> NVMeMoEStreamEngine:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def close(self) -> None:
        """Drain all in-flight I/O, shut down worker pool, close staging ring and shard FDs."""
        if self._closed:
            return
        self._closed = True
        self.drain()
        self._executor.shutdown(wait=True)
        self._ring.close()
        for fd in self._fds:
            os.close(fd)
        self._fds.clear()
        self.cache.clear()
