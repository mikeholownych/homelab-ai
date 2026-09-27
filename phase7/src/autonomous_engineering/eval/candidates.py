"""Phase 4 Candidate Model Manifests and Resource Specifications."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Any, List

from autonomous_engineering.core.crypto import content_hash


@dataclass(frozen=True)
class CandidateManifest:
    candidate_id: str
    model_repository: str
    model_revision: str
    architecture_type: str  # "dense" or "moe"
    parameter_count_total: float  # Billions
    parameter_count_active: float  # Billions
    quantization_format: str  # "awq-4bit", "fp8", "bf16"
    serving_runtime: str  # "vllm-xpu" or "ipex-llm"
    topology: str  # "tp1_single_card" or "tp2_dual_card"
    context_window_limit: int
    tool_call_parser: str
    vram_budget_gb: float
    host_ram_reserve_gb: float
    is_control_baseline: bool = False

    @property
    def manifest_hash(self) -> str:
        return content_hash(asdict(self))

    def validate_resource_envelope(self, max_vram_per_card_gb: float = 31.89) -> bool:
        """Validates that candidate respects B65 physical hardware limits."""
        if self.vram_budget_gb > max_vram_per_card_gb:
            return False
        if self.host_ram_reserve_gb < 8.0:
            return False
        if self.context_window_limit < 16384:
            return False
        return True


# 1. Control Baseline
CONTROL_QWEN3_CODER_30B_AWQ = CandidateManifest(
    candidate_id="control-qwen3-coder-30b-awq",
    model_repository="cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
    model_revision="26834d8d9b1c9a63b01859bf59ca6e001851e4bf",
    architecture_type="moe",
    parameter_count_total=30.0,
    parameter_count_active=3.3,
    quantization_format="awq-4bit",
    serving_runtime="vllm-xpu",
    topology="tp2_dual_card",
    context_window_limit=16384,
    tool_call_parser="qwen3_coder",
    vram_budget_gb=24.5,
    host_ram_reserve_gb=8.0,
    is_control_baseline=True,
)

# 2. Candidate A: Dense 32B AWQ-4bit
CANDIDATE_QWEN25_32B_AWQ = CandidateManifest(
    candidate_id="cand-qwen25-32b-awq",
    model_repository="Qwen/Qwen2.5-Coder-32B-Instruct",
    model_revision="b782dd3a48e792c3a5ef59a0f4438fa7be7f3d53",
    architecture_type="dense",
    parameter_count_total=32.5,
    parameter_count_active=32.5,
    quantization_format="awq-4bit",
    serving_runtime="vllm-xpu",
    topology="tp2_dual_card",
    context_window_limit=32768,
    tool_call_parser="qwen3_coder",
    vram_budget_gb=22.4,
    host_ram_reserve_gb=8.0,
    is_control_baseline=False,
)

# 3. Candidate B: MoE 16B FP8 (Lightweight fast MoE)
CANDIDATE_DEEPSEEK_LITE_FP8 = CandidateManifest(
    candidate_id="cand-deepseek-lite-fp8",
    model_repository="deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct",
    model_revision="86b72a0808b4eb99f7d2427a1fc9bbef37d2f9b1",
    architecture_type="moe",
    parameter_count_total=16.0,
    parameter_count_active=2.4,
    quantization_format="fp8",
    serving_runtime="vllm-xpu",
    topology="tp1_single_card",
    context_window_limit=16384,
    tool_call_parser="deepseek",
    vram_budget_gb=16.8,
    host_ram_reserve_gb=8.0,
    is_control_baseline=False,
)

# 4. Candidate C: Dense 14B FP8 (High-efficiency reasoning & reviewer)
CANDIDATE_PHI4_FP8 = CandidateManifest(
    candidate_id="cand-phi4-fp8",
    model_repository="microsoft/phi-4",
    model_revision="c0602f37c98038b3fa7eefbd9beaa9dc583f7380",
    architecture_type="dense",
    parameter_count_total=14.0,
    parameter_count_active=14.0,
    quantization_format="fp8",
    serving_runtime="vllm-xpu",
    topology="tp1_single_card",
    context_window_limit=16384,
    tool_call_parser="hermes",
    vram_budget_gb=15.2,
    host_ram_reserve_gb=8.0,
    is_control_baseline=False,
)

CANDIDATE_REGISTRY: Dict[str, CandidateManifest] = {
    CONTROL_QWEN3_CODER_30B_AWQ.candidate_id: CONTROL_QWEN3_CODER_30B_AWQ,
    CANDIDATE_QWEN25_32B_AWQ.candidate_id: CANDIDATE_QWEN25_32B_AWQ,
    CANDIDATE_DEEPSEEK_LITE_FP8.candidate_id: CANDIDATE_DEEPSEEK_LITE_FP8,
    CANDIDATE_PHI4_FP8.candidate_id: CANDIDATE_PHI4_FP8,
}


def get_candidate(candidate_id: str) -> CandidateManifest:
    if candidate_id not in CANDIDATE_REGISTRY:
        raise KeyError(f"Unknown candidate configuration: {candidate_id}")
    return CANDIDATE_REGISTRY[candidate_id]


def list_candidates() -> List[CandidateManifest]:
    return list(CANDIDATE_REGISTRY.values())
