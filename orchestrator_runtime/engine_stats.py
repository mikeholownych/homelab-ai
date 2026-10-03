"""Engine-agnostic worker statistics.

The gateway already holds each worker's credential and polls it, so it is the right place to read an
inference engine's own Prometheus metrics and re-publish them in one neutral shape. Monitors then read
only the gateway and never need a worker key. Parsers are tolerant: a missing series is reported as
``None`` (unknown) and never as a fabricated zero.
"""
from __future__ import annotations

import re
from typing import Any

_SAMPLE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{[^}]*\})?\s+([-+0-9.eEInfNa]+)\s*(?:\d+)?$')

# neutral name -> candidate engine series (first present wins; labelled series are summed)
_VLLM = {
    "requests_running": ("vllm:num_requests_running",),
    "requests_waiting": ("vllm:num_requests_waiting",),
    "kv_cache_usage": ("vllm:kv_cache_usage_perc", "vllm:gpu_cache_usage_perc"),
    "prompt_tokens_total": ("vllm:prompt_tokens_total",),
    "generation_tokens_total": ("vllm:generation_tokens_total",),
    "prefix_cache_queries_total": ("vllm:prefix_cache_queries_total",),
    "prefix_cache_hits_total": ("vllm:prefix_cache_hits_total",),
}
_LLAMA = {
    "requests_running": ("llamacpp:requests_processing",),
    "requests_waiting": ("llamacpp:requests_deferred",),
    "kv_cache_usage": ("llamacpp:kv_cache_usage_ratio",),
    "prompt_tokens_total": ("llamacpp:prompt_tokens_total",),
    "generation_tokens_total": ("llamacpp:tokens_predicted_total",),
    "prompt_tokens_cached_total": ("llamacpp:prompt_tokens_cached_total",),
    "prompt_seconds_total": ("llamacpp:prompt_seconds_total",),
    "generation_seconds_total": ("llamacpp:tokens_predicted_seconds_total",),
}
_MAPS = {"vllm": _VLLM, "llama.cpp": _LLAMA}


def parse_prometheus(text: str) -> dict[str, float]:
    """Sum every labelled sample of each series name; comments and malformed lines are ignored."""
    totals: dict[str, float] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        match = _SAMPLE.match(line.strip())
        if not match:
            continue
        try:
            value = float(match.group(2))
        except ValueError:
            continue
        if value != value or value in (float("inf"), float("-inf")):
            continue
        totals[match.group(1)] = totals.get(match.group(1), 0.0) + value
    return totals


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value == value else None


def slots_summary(slots: Any) -> dict[str, float] | None:
    """llama.cpp ``/slots``: live per-request progress that the cumulative counters only report on completion.

    KV occupancy is the tokens currently held by each slot (prompt plus tokens decoded so far) over its
    context window; for an idle slot that is the retained context. Returns None for an unusable payload.
    """
    if not isinstance(slots, list) or not slots:
        return None
    used = capacity = gen_in_flight = prompt_in_flight = 0.0
    for slot in slots:
        if not isinstance(slot, dict):
            return None
        n_ctx = _number(slot.get("n_ctx"))
        if not n_ctx or n_ctx <= 0:
            return None
        next_token = slot.get("next_token")
        if isinstance(next_token, list):
            next_token = next_token[0] if next_token and isinstance(next_token[0], dict) else {}
        decoded = _number((next_token or {}).get("n_decoded")) or 0.0
        prompt = _number(slot.get("n_prompt_tokens")) or 0.0
        capacity += n_ctx
        used += prompt + decoded
        if slot.get("is_processing") is True:
            gen_in_flight += decoded
            prompt_in_flight += _number(slot.get("n_prompt_tokens_processed")) or 0.0
    return {
        "kv_cache_usage": min(1.0, used / capacity),
        "generation_tokens_in_flight": gen_in_flight,
        "prompt_tokens_in_flight": prompt_in_flight,
    }


def with_live_counters(stats: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    """Add monotonic ``*_tokens_live`` counters (completed + in flight).

    The two reads are not atomic, so the raw sum can dip when a request finishes between them. Consumers
    treat a decreasing counter as an engine restart, so within one counter epoch the value never goes
    backwards; when the completed total itself decreases the engine restarted and the guard resets.
    """
    for total, flight, live in (
        ("generation_tokens_total", "generation_tokens_in_flight", "generation_tokens_live"),
        ("prompt_tokens_total", "prompt_tokens_in_flight", "prompt_tokens_live"),
    ):
        completed, in_flight = stats.get(total), stats.get(flight)
        if completed is None or in_flight is None:
            continue
        value = completed + in_flight
        before, before_total = (previous or {}).get(live), (previous or {}).get(total)
        if before is not None and before_total is not None and completed >= before_total:
            value = max(value, before)
        stats[live] = value
    return stats


def extract(engine: str, metrics_text: str, slots: Any = None) -> dict[str, Any] | None:
    """Neutral stats for a known engine, or None when the engine is unknown or exposes nothing usable."""
    mapping = _MAPS.get(engine)
    if mapping is None:
        return None
    series = parse_prometheus(metrics_text)
    stats: dict[str, Any] = {}
    for neutral, candidates in mapping.items():
        stats[neutral] = next((series[c] for c in candidates if c in series), None)
    queries, hits = stats.get("prefix_cache_queries_total"), stats.get("prefix_cache_hits_total")
    stats["prefix_cache_hit_ratio"] = (hits / queries) if queries and hits is not None else None
    stats.pop("prefix_cache_queries_total", None)
    stats.pop("prefix_cache_hits_total", None)
    if all(v is None for v in stats.values()):
        return None
    if engine == "llama.cpp":
        cached, processed = stats.get("prompt_tokens_cached_total"), stats.get("prompt_tokens_total")
        if cached is not None and processed is not None and cached + processed > 0:
            stats["prefix_cache_hit_ratio"] = cached / (cached + processed)
        live = slots_summary(slots)
        if live is not None:
            if stats.get("kv_cache_usage") is None:
                stats["kv_cache_usage"] = live["kv_cache_usage"]
            stats["generation_tokens_in_flight"] = live["generation_tokens_in_flight"]
            stats["prompt_tokens_in_flight"] = live["prompt_tokens_in_flight"]
    return stats
