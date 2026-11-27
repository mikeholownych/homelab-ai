"""Dual-term Linux host memory arbiter and bounded Tier-1 RAM routed-expert cache.

Enforces admission-before-first-touch across both cgroup v2 limits and Linux
MemAvailable minus kernel watermark-boost headroom, with synchronous cache
pressure reclaim, active lease refcounting, and count-decay / LRU / LFU eviction.
"""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .gguf_index import DIRECT_IO_BLOCK_SIZE, FileIdentity, align_up

EvictionPolicy = Literal["count_decay", "lru", "lfu"]

DEFAULT_CGROUP_RESERVE_BYTES = 512 * 1024 * 1024
DEFAULT_HOST_HEADROOM_BYTES = 512 * 1024 * 1024


def _default_read_text(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def parse_meminfo_bytes(meminfo_text: str) -> dict[str, int]:
    """Parse `/proc/meminfo` fields into byte counts."""
    parsed: dict[str, int] = {}
    for line in meminfo_text.splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        parts = rest.strip().split()
        if not parts:
            continue
        try:
            value = int(parts[0])
        except ValueError:
            continue
        if len(parts) >= 2 and parts[1] == "kB":
            value *= 1024
        parsed[key.strip()] = value
    return parsed


def compute_watermark_boost_headroom(
    meminfo_text: str,
    zoneinfo_text: str,
    boost_factor_text: str,
    page_size: int = 4096,
) -> int:
    """Compute bytes Linux MemAvailable can drop when kernel zones reach peak watermark_boost."""
    factor_match = re.search(r"\d+", boost_factor_text or "")
    if not factor_match or page_size <= 0:
        return 0
    factor = int(factor_match.group(0))
    if factor <= 0:
        return 0

    meminfo = parse_meminfo_bytes(meminfo_text or "")
    if meminfo.get("HugePages_Total", 0) > 0:
        return 0
    active_file = meminfo.get("Active(file)")
    inactive_file = meminfo.get("Inactive(file)")
    reclaimable = meminfo.get("KReclaimable", meminfo.get("SReclaimable"))
    if active_file is None or inactive_file is None or reclaimable is None:
        return 0
    hugepage_bytes = meminfo.get("Hugepagesize", 0)
    pageblock_pages = (hugepage_bytes // page_size) if hugepage_bytes > 0 else 0

    low_now = 0
    low_full = 0
    in_zone = False
    has_boost = False
    boost = low = high = managed = 0

    def close_zone() -> None:
        nonlocal low_now, low_full, in_zone, has_boost, boost, low, high, managed
        if not in_zone:
            return
        largest = boost
        if has_boost and low >= boost and high >= boost and managed >= 4 * pageblock_pages:
            base_high = high - boost
            scaled = (base_high * factor) // 10000
            if scaled > 0:
                largest = max(largest, max(pageblock_pages, scaled))
        low_now += low
        low_full += (low - min(low, boost)) + largest
        in_zone = False
        has_boost = False
        boost = low = high = managed = 0

    for line in (zoneinfo_text or "").splitlines():
        if line.startswith("Node"):
            close_zone()
            in_zone = True
            continue
        if not in_zone:
            continue
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        key, raw = parts[0], parts[1]
        if key in ("boost", "low", "high", "managed"):
            try:
                val = int(raw)
            except ValueError:
                continue
            if key == "boost":
                boost = val
                has_boost = True
            elif key == "low":
                low = val
            elif key == "high":
                high = val
            else:
                managed = val
    close_zone()

    if low_full <= low_now:
        return 0
    file_pages = (active_file + inactive_file) // page_size
    kernel_pages = reclaimable // page_size

    def kept_pages(wmark_low: int) -> int:
        return min(file_pages // 2, wmark_low) + min(kernel_pages // 2, wmark_low)

    return max(0, (kept_pages(low_full) - kept_pages(low_now)) * page_size)


def read_cgroup_v2_limits(
    reader: Callable[[str], str | None] = _default_read_text,
    *,
    cgroup_root: str = "/sys/fs/cgroup",
    proc_cgroup_path: str = "/proc/self/cgroup",
) -> tuple[int | None, int | None, int]:
    """Return tightest cgroup v2 (memory_max, memory_current, reclaimable_file_bytes)."""
    proc_text = reader(proc_cgroup_path)
    rel_path = ""
    if proc_text:
        for line in proc_text.splitlines():
            parts = line.strip().split(":", 2)
            if len(parts) == 3 and parts[0] == "0":
                rel_path = parts[2].lstrip("/")
                break

    # Walk from leaf cgroup up to root, capturing tightest finite memory.max and leaf usage.
    segments = [seg for seg in rel_path.split("/") if seg]
    tightest_max: int | None = None
    leaf_current: int | None = None
    leaf_file: int = 0

    for depth in range(len(segments), -1, -1):
        sub = "/".join(segments[:depth])
        base = f"{cgroup_root}/{sub}" if sub else cgroup_root
        max_txt = reader(f"{base}/memory.max")
        if max_txt is not None:
            val_str = max_txt.strip()
            if val_str and val_str != "max":
                try:
                    parsed_max = int(val_str)
                    if tightest_max is None or parsed_max < tightest_max:
                        tightest_max = parsed_max
                except ValueError:
                    pass
        if depth == len(segments):
            cur_txt = reader(f"{base}/memory.current")
            if cur_txt is not None:
                try:
                    leaf_current = int(cur_txt.strip())
                except ValueError:
                    leaf_current = None
            stat_txt = reader(f"{base}/memory.stat")
            if stat_txt:
                for line in stat_txt.splitlines():
                    parts = line.split()
                    if len(parts) == 2 and parts[0] == "file":
                        try:
                            leaf_file = int(parts[1])
                        except ValueError:
                            leaf_file = 0
                        break
    return tightest_max, leaf_current, leaf_file


@dataclass(frozen=True)
class MemoryRoom:
    """Snapshot of dual-term host memory admission headroom."""

    cgroup_max_bytes: int | None
    cgroup_current_bytes: int | None
    cgroup_surplus_bytes: int
    system_available_bytes: int
    watermark_boost_headroom_bytes: int
    system_floor_bytes: int
    system_surplus_bytes: int
    pending_bytes: int
    effective_surplus_bytes: int
    binding_term: Literal["cgroup", "system", "both", "none"]


class AllocationTicket:
    """RAII admission guard debiting pending bytes until commit() or cancel()."""

    def __init__(self, arbiter: HostMemoryArbiter, amount: int) -> None:
        self._arbiter = arbiter
        self.amount = amount
        self._closed = False

    def commit(self) -> None:
        if not self._closed:
            self._closed = True
            self._arbiter._release_pending(self.amount)

    def cancel(self) -> None:
        if not self._closed:
            self._closed = True
            self._arbiter._release_pending(self.amount)

    def __enter__(self) -> AllocationTicket:
        return self

    def __exit__(self, exc_type: object, _exc: object, _tb: object) -> None:
        if exc_type is None:
            self.commit()
        else:
            self.cancel()


class HostMemoryArbiter:
    """Dual-term Linux memory arbiter preventing page-cache & expert-cache cgroup OOMs."""

    def __init__(
        self,
        *,
        cgroup_reserve_bytes: int = DEFAULT_CGROUP_RESERVE_BYTES,
        host_headroom_bytes: int = DEFAULT_HOST_HEADROOM_BYTES,
        reclaimable_file: bool = True,
        page_size: int = 4096,
        reader: Callable[[str], str | None] = _default_read_text,
    ) -> None:
        self.cgroup_reserve_bytes = max(0, int(cgroup_reserve_bytes))
        self.host_headroom_bytes = max(0, int(host_headroom_bytes))
        self.reclaimable_file = reclaimable_file
        self.page_size = page_size
        self._reader = reader
        self._lock = threading.Lock()
        self._pending_bytes = 0
        self._reclaimers: list[Callable[[int], int]] = []

    def register_reclaimer(self, callback: Callable[[int], int]) -> None:
        """Register a pressure reclaimer returning bytes actually freed."""
        with self._lock:
            self._reclaimers.append(callback)

    def _release_pending(self, amount: int) -> None:
        with self._lock:
            self._pending_bytes = max(0, self._pending_bytes - amount)

    def measure(self, extra_bytes: int = 0) -> MemoryRoom:
        """Measure live cgroup v2 and Linux MemAvailable room minus watermark-boost headroom."""
        with self._lock:
            pending = self._pending_bytes

        cg_max, cg_cur, cg_file = read_cgroup_v2_limits(self._reader)
        meminfo_text = self._reader("/proc/meminfo") or ""
        zoneinfo_text = self._reader("/proc/zoneinfo") or ""
        boost_text = self._reader("/proc/sys/vm/watermark_boost_factor") or "0"

        meminfo = parse_meminfo_bytes(meminfo_text)
        mem_available = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
        boost_headroom = compute_watermark_boost_headroom(
            meminfo_text, zoneinfo_text, boost_text, page_size=self.page_size
        )
        system_floor = max(self.host_headroom_bytes, self.cgroup_reserve_bytes) + boost_headroom
        system_surplus = max(0, mem_available - system_floor - pending - extra_bytes)

        if cg_max is not None and cg_cur is not None:
            effective_usage = max(0, cg_cur - (cg_file if self.reclaimable_file else 0))
            cg_surplus = max(0, cg_max - self.cgroup_reserve_bytes - effective_usage - pending - extra_bytes)
            effective_surplus = min(cg_surplus, system_surplus)
            if cg_surplus == 0 and system_surplus == 0:
                binding: Literal["cgroup", "system", "both", "none"] = "both"
            elif cg_surplus <= system_surplus:
                binding = "cgroup"
            else:
                binding = "system"
        else:
            cg_surplus = system_surplus
            effective_surplus = system_surplus
            binding = "system" if mem_available > 0 else "none"

        return MemoryRoom(
            cgroup_max_bytes=cg_max,
            cgroup_current_bytes=cg_cur,
            cgroup_surplus_bytes=cg_surplus,
            system_available_bytes=mem_available,
            watermark_boost_headroom_bytes=boost_headroom,
            system_floor_bytes=system_floor,
            system_surplus_bytes=system_surplus,
            pending_bytes=pending,
            effective_surplus_bytes=effective_surplus,
            binding_term=binding,
        )

    def admit(self, requested_bytes: int, *, allow_reclaim: bool = True) -> AllocationTicket | None:
        """Reserve `requested_bytes` before first touch; triggers reclaimers if short."""
        if requested_bytes <= 0:
            return AllocationTicket(self, 0)

        room = self.measure(extra_bytes=0)
        if room.effective_surplus_bytes < requested_bytes and allow_reclaim:
            deficit = requested_bytes - room.effective_surplus_bytes
            with self._lock:
                reclaimers = list(self._reclaimers)
            for reclaimer in reclaimers:
                freed = reclaimer(deficit)
                deficit -= max(0, freed)
                if deficit <= 0:
                    break
            room = self.measure(extra_bytes=0)

        with self._lock:
            # Re-verify under lock with current pending bytes.
            if room.effective_surplus_bytes < requested_bytes:
                return None
            self._pending_bytes += requested_bytes
            return AllocationTicket(self, requested_bytes)


@dataclass(frozen=True)
class ExpertCacheKey:
    """Content-bound cache key incorporating file identity and physical byte extent."""

    layer_id: int
    expert_idx: int
    shard_identities: tuple[tuple[int, int, int, int, int], ...]

    @classmethod
    def make(cls, layer_id: int, expert_idx: int, shards: tuple[FileIdentity, ...]) -> ExpertCacheKey:
        sig = tuple((s.dev, s.ino, s.size, s.mtime_ns, s.ctime_ns) for s in shards)
        return cls(layer_id=layer_id, expert_idx=expert_idx, shard_identities=sig)


@dataclass
class _CacheSlot:
    key: ExpertCacheKey
    layer_id: int
    expert_idx: int
    payload: dict[str, bytes]
    size_bytes: int
    last_touch: int
    frequency: float = 1.0
    leases: int = 0
    inflight: bool = False
    vram_mirrored: bool = False
    prewarmed_unused: bool = False


@dataclass
class ExpertCacheStats:
    """Runtime accounting counters for Tier-1 RAM expert cache."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    reclaimed_slots: int = 0
    reclaimed_bytes: int = 0
    admitted_slots: int = 0
    rejected_admissions: int = 0
    resident_slots: int = 0
    resident_bytes: int = 0
    max_slots: int = 0


def estimate_slot_overhead_bytes(slot_payload_bytes: int, page_size: int = 4096) -> int:
    """Include page rounding + 5-level page-table cost so auto-sizing avoids mid-run OOM."""
    if slot_payload_bytes <= 0:
        return 0
    aligned = align_up(slot_payload_bytes, page_size)
    pages = aligned // page_size
    tables = 1
    entries_per_table = max(1, page_size // 8)
    for _ in range(4):
        pages = (pages + entries_per_table - 1) // entries_per_table + 1
        tables += pages
    return aligned + tables * page_size


def size_cache_slots_for_budget(
    budget_bytes: int,
    slot_payload_bytes: int,
    *,
    n_layers: int,
    n_experts: int,
    page_size: int = 4096,
    entry_metadata_bytes: int = 256,
    guard_bytes: int = 64 * 1024,
) -> int:
    """Binary-search maximum cache slots fitting cleanly inside `budget_bytes` including metadata."""
    if budget_bytes <= guard_bytes or slot_payload_bytes <= 0 or n_layers <= 0 or n_experts <= 0:
        return 0
    max_possible = n_layers * n_experts
    slot_cost = estimate_slot_overhead_bytes(slot_payload_bytes, page_size=page_size)
    freq_table_bytes = n_layers * n_experts * 48

    def total_cost(slots: int) -> int:
        if slots == 0:
            return 0
        return slots * (slot_cost + entry_metadata_bytes) + freq_table_bytes + guard_bytes

    low, high = 0, min(max_possible, budget_bytes // max(1, slot_cost))
    while low < high:
        mid = low + (high - low + 1) // 2
        if total_cost(mid) <= budget_bytes:
            low = mid
        else:
            high = mid - 1
    return low


class ExpertCache:
    """Thread-safe bounded Tier-1 RAM cache for routed MoE experts."""

    def __init__(
        self,
        max_slots: int,
        slot_stride_bytes: int,
        *,
        policy: EvictionPolicy = "count_decay",
        decay_factor: float = 0.5,
        decay_interval: int = 64,
        arbiter: HostMemoryArbiter | None = None,
    ) -> None:
        if max_slots < 0:
            raise ValueError("max_slots must be non-negative")
        self.max_slots = int(max_slots)
        self.slot_stride_bytes = max(DIRECT_IO_BLOCK_SIZE, int(slot_stride_bytes)) if slot_stride_bytes > 0 else 0
        self.policy: EvictionPolicy = policy
        self.decay_factor = decay_factor
        self.decay_interval = max(1, int(decay_interval))
        self._arbiter = arbiter
        self._lock = threading.RLock()
        self._slots: dict[ExpertCacheKey, _CacheSlot] = {}
        self._freq_history: dict[tuple[int, int], float] = {}
        self._clock = 0
        self._step_count = 0
        self.stats = ExpertCacheStats(max_slots=self.max_slots)
        if self._arbiter is not None:
            self._arbiter.register_reclaimer(self.reclaim)

    def _tick(self) -> int:
        self._clock += 1
        self._step_count += 1
        if self.policy == "count_decay" and (self._step_count % self.decay_interval == 0):
            for key in list(self._freq_history):
                self._freq_history[key] *= self.decay_factor
            for slot in self._slots.values():
                slot.frequency *= self.decay_factor
        return self._clock

    def lookup(self, key: ExpertCacheKey, *, acquire_lease: bool = False) -> dict[str, bytes] | None:
        """Look up an expert in Tier-1 RAM cache, updating touch/frequency counters on hit."""
        with self._lock:
            now = self._tick()
            slot = self._slots.get(key)
            if slot is None or slot.inflight:
                self.stats.misses += 1
                return None
            slot.last_touch = now
            slot.prewarmed_unused = False
            hist_key = (slot.layer_id, slot.expert_idx)
            new_freq = self._freq_history.get(hist_key, slot.frequency) + 1.0
            self._freq_history[hist_key] = new_freq
            slot.frequency = new_freq
            if acquire_lease:
                slot.leases += 1
            self.stats.hits += 1
            return slot.payload

    def release_lease(self, key: ExpertCacheKey) -> None:
        with self._lock:
            slot = self._slots.get(key)
            if slot is not None and slot.leases > 0:
                slot.leases -= 1

    def mark_vram_mirrored(self, key: ExpertCacheKey, mirrored: bool = True) -> None:
        """Mark an expert as mirrored in Tier-0 VRAM so Tier-1 evicts its backup copy first."""
        with self._lock:
            slot = self._slots.get(key)
            if slot is not None:
                slot.vram_mirrored = mirrored

    def _eviction_rank(self, slot: _CacheSlot) -> tuple[int, float, int]:
        """Lower rank tuple is evicted first: prewarmed_unused -> vram_mirrored -> cold victim."""
        if slot.prewarmed_unused:
            tier = 0
        elif slot.vram_mirrored:
            tier = 1
        else:
            tier = 2
        if self.policy == "lru":
            return (tier, 0.0, slot.last_touch)
        # Both lfu and count_decay rank by frequency ascending, breaking ties by oldest touch.
        return (tier, slot.frequency, slot.last_touch)

    def _select_victim(self) -> ExpertCacheKey | None:
        candidates = [
            (self._eviction_rank(slot), key)
            for key, slot in self._slots.items()
            if slot.leases == 0 and not slot.inflight
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    def put(
        self,
        key: ExpertCacheKey,
        payload: dict[str, bytes],
        *,
        prewarmed: bool = False,
        acquire_lease: bool = False,
    ) -> bool:
        """Admit an expert payload into Tier-1 RAM cache, evicting cold unleased slots as needed."""
        with self._lock:
            if self.max_slots == 0:
                self.stats.rejected_admissions += 1
                return False
            now = self._tick()
            size_bytes = max(self.slot_stride_bytes, sum(len(buf) for buf in payload.values()))

            if key in self._slots:
                existing = self._slots[key]
                existing.payload = payload
                existing.last_touch = now
                existing.inflight = False
                existing.prewarmed_unused = prewarmed
                if acquire_lease:
                    existing.leases += 1
                return True

            if len(self._slots) >= self.max_slots:
                victim_key = self._select_victim()
                if victim_key is None:
                    self.stats.rejected_admissions += 1
                    return False
                victim = self._slots.pop(victim_key)
                self.stats.evictions += 1
                self.stats.resident_bytes = max(0, self.stats.resident_bytes - victim.size_bytes)

            ticket: AllocationTicket | None = None
            if self._arbiter is not None:
                ticket = self._arbiter.admit(size_bytes, allow_reclaim=False)
                if ticket is None:
                    self.stats.rejected_admissions += 1
                    return False

            hist_key = (key.layer_id, key.expert_idx)
            freq = self._freq_history.get(hist_key, 0.0) + (0.0 if prewarmed else 1.0)
            self._freq_history[hist_key] = freq
            self._slots[key] = _CacheSlot(
                key=key,
                layer_id=key.layer_id,
                expert_idx=key.expert_idx,
                payload=payload,
                size_bytes=size_bytes,
                last_touch=now,
                frequency=freq,
                leases=1 if acquire_lease else 0,
                prewarmed_unused=prewarmed,
            )
            if ticket is not None:
                ticket.commit()
            self.stats.admitted_slots += 1
            self.stats.resident_slots = len(self._slots)
            self.stats.resident_bytes += size_bytes
            return True

    def reclaim(self, target_bytes: int) -> int:
        """Synchronously evict cold unleased slots under memory pressure until `target_bytes` freed."""
        freed = 0
        with self._lock:
            while freed < target_bytes:
                victim_key = self._select_victim()
                if victim_key is None:
                    break
                victim = self._slots.pop(victim_key)
                freed += victim.size_bytes
                self.stats.reclaimed_slots += 1
                self.stats.reclaimed_bytes += victim.size_bytes
                self.stats.resident_bytes = max(0, self.stats.resident_bytes - victim.size_bytes)
            self.stats.resident_slots = len(self._slots)
        return freed

    def clear(self) -> None:
        with self._lock:
            self._slots.clear()
            self.stats.resident_slots = 0
            self.stats.resident_bytes = 0
