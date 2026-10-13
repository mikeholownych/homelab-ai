"""High-performance in-memory deterministic response cache for the orchestrator runtime.

Caches identical completion requests when temperature is 0 (greedy sampling),
when cache is explicitly requested, or with fixed seeds. Provides sub-millisecond
response delivery with zero GPU compute overhead, LRU eviction, and TTL expiration.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any


def _canonical_json(value: Any) -> str:
    """Deterministic JSON serialization with sorted keys and compact separators."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def extract_prompt_text(request: dict[str, Any]) -> str:
    """Extract canonical concatenated prompt text from messages for semantic comparison."""
    messages = request.get("messages") or []
    parts = []
    for m in messages:
        if isinstance(m, dict):
            role = m.get("role", "")
            content = m.get("content", "")
            if isinstance(content, str):
                parts.append(f"{role}:{content}")
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        parts.append(f"{role}:{part.get('text', '')}")
    return "\n".join(parts)


def compute_shingles(text: str, n: int = 3) -> set[str]:
    """Compute word n-gram shingles for fast textual similarity."""
    tokens = re.findall(r"\w+", text.lower())
    if not tokens:
        return set()
    if len(tokens) < n:
        return {"_".join(tokens)}
    return {"_".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def jaccard_similarity(s1: set[str], s2: set[str]) -> float:
    """Compute Jaccard similarity coefficient between two shingle sets."""
    if not s1 or not s2:
        return 1.0 if s1 == s2 else 0.0
    intersection = len(s1 & s2)
    union = len(s1 | s2)
    return intersection / union if union > 0 else 0.0


@dataclass
class CacheEntry:
    key: str
    response: dict[str, Any]
    created_at: float
    ttl: float
    hit_count: int = 0
    last_accessed: float = 0.0
    model_id: str = ""
    shingles: set[str] = field(default_factory=set)
    tools_hash: str = ""
    reasoning_effort: str | None = None


class ResponseCache:
    """Thread-safe LRU deterministic response cache with TTL expiration and semantic matching."""

    def __init__(
        self,
        max_entries: int = 1024,
        default_ttl: float = 3600.0,
        *,
        enabled: bool = True,
        semantic_enabled: bool = True,
        semantic_threshold: float = 0.95,
    ) -> None:
        self.max_entries = max(1, int(max_entries))
        self.default_ttl = max(0.01, float(default_ttl))
        self.enabled = bool(enabled)
        self.semantic_enabled = bool(semantic_enabled)
        self.semantic_threshold = max(0.5, min(1.0, float(semantic_threshold)))
        self._entries: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.RLock()
        self._hits = 0
        self._semantic_hits = 0
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

    def get_semantic(
        self,
        request: dict[str, Any],
        model_id: str | None = None,
        reasoning_effort: str | None = None,
        threshold: float | None = None,
    ) -> tuple[dict[str, Any] | None, float]:
        """Search for a semantically equivalent cached response using Jaccard shingle similarity."""
        if not self.enabled or not self.semantic_enabled:
            return None, 0.0

        min_sim = float(threshold) if threshold is not None else self.semantic_threshold
        target_model = model_id or request.get("model") or ""
        target_tools_hash = hashlib.sha256(_canonical_json(request.get("tools") or []).encode("utf-8")).hexdigest()
        query_text = extract_prompt_text(request)
        query_shingles = compute_shingles(query_text)

        if not query_shingles:
            return None, 0.0

        best_entry: CacheEntry | None = None
        best_sim = 0.0
        now = time.monotonic()

        with self._lock:
            for entry in reversed(self._entries.values()):
                if entry.model_id and entry.model_id != target_model:
                    continue
                if entry.tools_hash and entry.tools_hash != target_tools_hash:
                    continue
                if entry.reasoning_effort is not None and entry.reasoning_effort != reasoning_effort:
                    continue
                if (now - entry.created_at) > entry.ttl:
                    continue
                if not entry.shingles:
                    continue
                sim = jaccard_similarity(query_shingles, entry.shingles)
                if sim >= min_sim and sim > best_sim:
                    best_sim = sim
                    best_entry = entry
                    if sim >= 0.999:
                        break

            if best_entry is not None:
                self._entries.move_to_end(best_entry.key)
                best_entry.hit_count += 1
                best_entry.last_accessed = now
                self._hits += 1
                self._semantic_hits += 1
                cached_copy = copy.deepcopy(best_entry.response)
                cached_copy["id"] = "chatcmpl-semcache-" + uuid.uuid4().hex[:20]
                cached_copy["created"] = int(time.time())
                return cached_copy, best_sim

            return None, 0.0

    def set(
        self,
        key: str,
        response: dict[str, Any],
        ttl: float | None = None,
        request: dict[str, Any] | None = None,
        model_id: str | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        """Store a response in cache with LRU eviction and semantic shingle indexing."""
        if not self.enabled:
            return

        now = time.monotonic()
        effective_ttl = float(ttl) if ttl is not None else self.default_ttl

        shingles: set[str] = set()
        tools_hash = ""
        target_model = model_id or ""
        if request is not None:
            target_model = target_model or request.get("model") or ""
            prompt_text = extract_prompt_text(request)
            shingles = compute_shingles(prompt_text)
            tools_hash = hashlib.sha256(_canonical_json(request.get("tools") or []).encode("utf-8")).hexdigest()

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
                model_id=target_model,
                shingles=shingles,
                tools_hash=tools_hash,
                reasoning_effort=reasoning_effort,
            )

    def size(self) -> int:
        with self._lock:
            return len(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._hits = 0
            self._semantic_hits = 0
            self._misses = 0

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total_lookups = self._hits + self._misses
            hit_rate = (self._hits / total_lookups) if total_lookups > 0 else 0.0
            return {
                "size": len(self._entries),
                "max_entries": self.max_entries,
                "hits": self._hits,
                "semantic_hits": self._semantic_hits,
                "misses": self._misses,
                "hit_rate": round(hit_rate, 4),
                "semantic_enabled": self.semantic_enabled,
                "semantic_threshold": self.semantic_threshold,
            }
