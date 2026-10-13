"""Smart model routing intelligence: prompt complexity analysis, EWMA latency tracking,
and multi-factor optimization (latency, load, cost, capability fit).
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class ComplexityReport:
    score: float  # 0.0 to 1.0
    tier: str     # "simple", "medium", "complex"
    factors: dict[str, Any] = field(default_factory=dict)


class PromptComplexityAnalyzer:
    """Fast, deterministic syntactic & semantic complexity estimator."""

    # Patterns indicating heavy code or algorithmic context
    CODE_PATTERNS = [
        re.compile(r"```[a-zA-Z0-9_\-+]*\n"),
        re.compile(r"\b(def|class|async\s+def|interface|type|struct|impl|fn)\b"),
        re.compile(r"\b(import|from\s+[a-zA-Z0-9_.]+\s+import|#include|package)\b"),
        re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|JOIN|GROUP\s+BY|ORDER\s+BY)\b", re.IGNORECASE),
        re.compile(r"\b(traceback|stack\s*trace|exception|error:|panic:)\b", re.IGNORECASE),
    ]

    # Patterns indicating multi-step reasoning, architectural planning, or deep analysis
    REASONING_PATTERNS = [
        re.compile(r"\b(step[- ]by[- ]step|think\s+through|verify|prove|derive|analyze\s+root\s+cause)\b", re.IGNORECASE),
        re.compile(r"\b(architecture|refactor|design\s+pattern|concurrency|deadlock|race\s+condition)\b", re.IGNORECASE),
    ]

    @classmethod
    def analyze(cls, request: dict[str, Any], prompt_tokens: int) -> ComplexityReport:
        messages = request.get("messages", [])
        tools = request.get("tools", [])

        # 1. Token length score (0 to 1, saturates at 16k tokens)
        token_score = min(1.0, max(0.0, prompt_tokens / 16384.0))

        # 2. Tool definition complexity
        tool_count = len(tools) if isinstance(tools, list) else 0
        tool_score = min(1.0, tool_count * 0.25)

        # 3. Message turns depth
        turn_count = len(messages) if isinstance(messages, list) else 0
        turn_score = min(1.0, turn_count / 15.0)

        # 4. Text content inspection (check latest user message + overall content)
        combined_text = ""
        user_text = ""
        if isinstance(messages, list):
            for m in messages:
                if isinstance(m, dict):
                    content = str(m.get("content", ""))
                    combined_text += " " + content
                    if m.get("role") == "user":
                        user_text = content  # latest user turn

        # Code density check
        code_matches = sum(len(p.findall(combined_text)) for p in cls.CODE_PATTERNS)
        code_score = min(1.0, code_matches * 0.2)

        # Reasoning intent check
        reasoning_matches = sum(len(p.findall(user_text)) for p in cls.REASONING_PATTERNS)
        reasoning_score = min(1.0, reasoning_matches * 0.3)

        # Composite weighted score
        # Token count: 25%, Tools: 20%, Turns: 15%, Code density: 25%, Reasoning intent: 15%
        composite = (
            0.25 * token_score +
            0.20 * tool_score +
            0.15 * turn_score +
            0.25 * code_score +
            0.15 * reasoning_score
        )
        score = round(max(0.0, min(1.0, composite)), 3)

        if score < 0.30:
            tier = "simple"
        elif score < 0.70:
            tier = "medium"
        else:
            tier = "complex"

        return ComplexityReport(
            score=score,
            tier=tier,
            factors={
                "prompt_tokens": prompt_tokens,
                "token_score": round(token_score, 2),
                "tool_count": tool_count,
                "tool_score": round(tool_score, 2),
                "turn_count": turn_count,
                "code_score": round(code_score, 2),
                "reasoning_score": round(reasoning_score, 2),
            },
        )


@dataclass
class LatencyMetric:
    ewma_duration: float = 0.5  # seconds
    ewma_ttft: float = 0.1      # seconds
    samples: int = 0
    last_updated: float = field(default_factory=time.monotonic)


class LatencyTracker:
    """Thread-safe EWMA latency estimator per worker and pool."""

    def __init__(self, alpha: float = 0.2) -> None:
        self.alpha = alpha  # smoothing factor
        self._lock = threading.RLock()
        self._workers: dict[str, LatencyMetric] = {}
        self._pools: dict[str, LatencyMetric] = {}

    def record(self, worker_id: str, pool: str, duration: float, ttft: float | None = None) -> None:
        now = time.monotonic()
        duration = max(0.001, float(duration))
        ttft = max(0.001, float(ttft)) if ttft is not None else None

        with self._lock:
            # Update worker
            w_metric = self._workers.setdefault(worker_id, LatencyMetric())
            if w_metric.samples == 0:
                w_metric.ewma_duration = duration
                if ttft is not None:
                    w_metric.ewma_ttft = ttft
            else:
                w_metric.ewma_duration = (self.alpha * duration) + ((1.0 - self.alpha) * w_metric.ewma_duration)
                if ttft is not None:
                    w_metric.ewma_ttft = (self.alpha * ttft) + ((1.0 - self.alpha) * w_metric.ewma_ttft)
            w_metric.samples += 1
            w_metric.last_updated = now

            # Update pool
            p_metric = self._pools.setdefault(pool, LatencyMetric())
            if p_metric.samples == 0:
                p_metric.ewma_duration = duration
                if ttft is not None:
                    p_metric.ewma_ttft = ttft
            else:
                p_metric.ewma_duration = (self.alpha * duration) + ((1.0 - self.alpha) * p_metric.ewma_duration)
                if ttft is not None:
                    p_metric.ewma_ttft = (self.alpha * ttft) + ((1.0 - self.alpha) * p_metric.ewma_ttft)
            p_metric.samples += 1
            p_metric.last_updated = now

    def worker_duration(self, worker_id: str) -> float:
        with self._lock:
            metric = self._workers.get(worker_id)
            return metric.ewma_duration if metric else 1.0

    def pool_duration(self, pool: str) -> float:
        with self._lock:
            metric = self._pools.get(pool)
            return metric.ewma_duration if metric else 1.0

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "workers": {
                    wid: {
                        "ewma_duration_ms": round(m.ewma_duration * 1000, 1),
                        "ewma_ttft_ms": round(m.ewma_ttft * 1000, 1),
                        "samples": m.samples,
                    }
                    for wid, m in self._workers.items()
                },
                "pools": {
                    pid: {
                        "ewma_duration_ms": round(m.ewma_duration * 1000, 1),
                        "ewma_ttft_ms": round(m.ewma_ttft * 1000, 1),
                        "samples": m.samples,
                    }
                    for pid, m in self._pools.items()
                },
            }


class CostModel:
    """Relative cost weighting and budget optimization."""

    DEFAULT_POOL_COSTS = {
        "lead": 1.0,     # baseline cost
        "aux": 0.5,      # smaller/auxiliary pool
        "deep": 3.0,     # large/deep thinking pool
        "candidate": 1.0,
    }

    def __init__(self, pool_weights: dict[str, float] | None = None) -> None:
        self.weights = dict(self.DEFAULT_POOL_COSTS)
        if pool_weights:
            self.weights.update(pool_weights)

    def cost_weight(self, pool: str) -> float:
        return self.weights.get(pool, 1.0)
