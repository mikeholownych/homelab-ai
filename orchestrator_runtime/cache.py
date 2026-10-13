"""High-performance in-memory deterministic response cache for the orchestrator runtime.

Caches identical completion requests when temperature is 0 (greedy sampling),
when cache is explicitly requested, or with fixed seeds. Provides sub-millisecond
response delivery with zero GPU compute overhead, LRU eviction, and TTL expiration.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any


def _canonical_json(value: Any) -> str:
    """Deterministic JSON serialization with sorted keys and compact separators."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass
class CacheEntry:
    key: str
    response: dict[str, Any]
    created_at: float
    ttl: float
    hit_count: int = 0
    last_accessed: float = 0.0


class ResponseCache:
    """Thread-safe LRU deterministic response cache with TTL expiration."""

    def __init__(
        self,
        max_entries: int = 1024,
        default_ttl: float = 3600.0,
        *,
        enabled: bool = True,
    ) -> None:
        self.max_entries = max(1, int(max_entries))
        self.default_ttl = max(0.01, float(default_ttl))
        self.enabled = bool(enabled)
        self._entries: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0

    def is_cacheable(self, request: dict[str, Any], headers: dict[str, str] | None = None) -> bool:
        """Determine if a request is eligible for caching based on determinism and headers."""
        if not self.enabled:
            return False

        # Streaming responses are not cached directly in current version
        if request.get("stream"):
            return False

        # Respect standard Cache-Control and X-AIHost-Cache bypass headers
        if headers:
            cc = headers.get("Cache-Control", "").lower()
            if "no-cache" in cc or "no-store" in cc:
                return False
            if headers.get("X-AIHost-Cache", "").lower() in ("bypass", "off"):
                return False
            if headers.get("X-AIHost-Cache", "").lower() in ("force", "on"):
                return True

        if request.get("cache") is True:
            return True

        # In standard LLM decoding, temperature == 0 (or 0.0) is greedy/deterministic
        temp = request.get("temperature")
        if temp is not None:
            try:
                if float(temp) <= 0.0001:
                    return True
            except (ValueError, TypeError):
                return False

        return False

    def compute_key(
        self,
        request: dict[str, Any],
        model_id: str | None = None,
        reasoning_effort: str | None = None,
    ) -> str:
        """Generate a deterministic 64-character SHA-256 cache key for the request."""
        target_model = model_id or request.get("model") or ""
        messages = request.get("messages") or []
        tools = request.get("tools") or []
        seed = request.get("seed")
        payload = {
            "model": target_model,
            "messages": messages,
            "tools": tools,
            "reasoning_effort": reasoning_effort,
            "seed": seed,
        }
        serialized = _canonical_json(payload)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        """Retrieve a cached response if present and not expired (LRU access)."""
        if not self.enabled:
            return None

        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return None

            # Check TTL
            if (now - entry.created_at) > entry.ttl:
                del self._entries[key]
                self._misses += 1
                return None

            # Update LRU ordering and metadata
            self._entries.move_to_end(key)
            entry.hit_count += 1
            entry.last_accessed = now
            self._hits += 1

            # Produce clean copy with fresh completion ID and timestamp
            cached_copy = copy.deepcopy(entry.response)
            cached_copy["id"] = "chatcmpl-cache-" + uuid.uuid4().hex[:20]
            cached_copy["created"] = int(time.time())
            return cached_copy

    def set(self, key: str, response: dict[str, Any], ttl: float | None = None) -> None:
        """Store a response in cache with LRU eviction when capacity is reached."""
        if not self.enabled:
            return

        now = time.monotonic()
        effective_ttl = float(ttl) if ttl is not None else self.default_ttl

        with self._lock:
            if key in self._entries:
                self._entries.move_to_end(key)
            else:
                while len(self._entries) >= self.max_entries:
                    self._entries.popitem(last=False)  # Evict least-recently used

            self._entries[key] = CacheEntry(
                key=key,
                response=copy.deepcopy(response),
                created_at=now,
                ttl=effective_ttl,
                hit_count=0,
                last_accessed=now,
            )

    def size(self) -> int:
        with self._lock:
            return len(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._hits = 0
            self._misses = 0

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total_lookups = self._hits + self._misses
            hit_rate = (self._hits / total_lookups) if total_lookups > 0 else 0.0
            return {
                "size": len(self._entries),
                "max_entries": self.max_entries,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": round(hit_rate, 4),
            }
