"""B65 Model Evaluation and Benchmark Metrics Models."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from autonomous_engineering.core.crypto import content_hash


@dataclass(frozen=True)
class EvaluationCandidate:
    candidate_id: str
    hardware_target: str  # "intel_arc_pro_b65"
    xpu_runtime: str  # "vllm_xpu", "ipex_llm"
    model_name: str
    model_revision: str
    quantization: str  # "fp8", "int4", "bf16"
    context_window: int
    is_control_baseline: bool = False

    @property
    def config_hash(self) -> str:
        return content_hash(
            {
                "candidate_id": self.candidate_id,
                "hardware_target": self.hardware_target,
                "xpu_runtime": self.xpu_runtime,
                "model_name": self.model_name,
                "model_revision": self.model_revision,
                "quantization": self.quantization,
                "context_window": self.context_window,
            }
        )


@dataclass(frozen=True)
class BenchmarkResult:
    candidate_id: str
    config_hash: str
    tasks_evaluated: int
    independently_accepted_count: int
    acceptance_rate: float
    first_pass_repair_rate: float
    mean_latency_ms: float
    mean_tokens_per_sec: float
    peak_vram_mb: float

    def beats_baseline(self, baseline: "BenchmarkResult") -> bool:
        """Determines if candidate demonstrates meaningful improvement over control baseline."""
        # Primary criterion: Independently accepted engineering outcomes
        if self.acceptance_rate > baseline.acceptance_rate + 0.05:
            return True
        if self.acceptance_rate >= baseline.acceptance_rate:
            # Secondary criterion: First pass repair rate
            return self.first_pass_repair_rate > baseline.first_pass_repair_rate + 0.05
        return False
