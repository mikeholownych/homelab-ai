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


def extract(engine: str, metrics_text: str) -> dict[str, Any] | None:
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
    return stats
