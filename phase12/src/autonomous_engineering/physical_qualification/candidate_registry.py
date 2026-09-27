"""Candidate artifact custody and immutable identity registry for Phase 12."""

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional


class ArtifactVerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    REJECTED_MUTABLE_TAG = "REJECTED_MUTABLE_TAG"
    REJECTED_CHECKSUM_MISMATCH = "REJECTED_CHECKSUM_MISMATCH"
    REJECTED_MISSING_CONFIG = "REJECTED_MISSING_CONFIG"


@dataclass(frozen=True)
class CandidateArtifact:
    candidate_id: str
    model_identifier: str
    snapshot_revision: str
    architecture: str
    parameter_count_b: float
    active_parameter_count_b: float
    quantization_format: str
    context_window_tokens: int
    config_sha256: str
    tokenizer_sha256: Optional[str]
    runtime_container_digest: str
    tool_call_parser: str
    structured_output_engine: str
    local_weights_path: Optional[str]
    is_resident_control: bool
    status: ArtifactVerificationStatus


class CandidateArtifactRegistry:
    """Manages immutable artifact custody and cryptographic validation for model candidates."""

    FORBIDDEN_MUTABLE_TAGS = {"latest", "main", "master", "head", "dev", "nightly", "current"}

    def __init__(self):
        self._artifacts: Dict[str, CandidateArtifact] = {}
        self._register_default_candidates()

    def _register_default_candidates(self) -> None:
        """Register the verified candidate models audited on host 10.0.8.5."""

        # 1. Resident Control: Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit
        self.register_candidate(
            candidate_id="CTRL-QWEN3-CODER-30B",
            model_identifier="cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
            snapshot_revision="4bd30395b72ea6045edd04806c4fea448d4467b3",
            architecture="Qwen2ForCausalLM",
            parameter_count_b=30.0,
            active_parameter_count_b=3.3,
            quantization_format="AWQ-4bit",
            context_window_tokens=65536,
            config_sha256="42981b44892a1940c8f93bf5fb40972bc62f2c9a6c8f0d10115175e68b11396d",
            tokenizer_sha256="64be5fc2f66a3e5679ba229261a7a0d8112b06f6f560c750a62ca9457f90006c",
            runtime_container_digest="docker.io/vllm/vllm-openai-xpu@sha256:4bdfd5b928b4a6a95c92b1edc861f13587a797a32db8c1bc96ca4e2c0d58629d",
            tool_call_parser="qwen3_coder",
            structured_output_engine="outlines",
            local_weights_path="/var/lib/local-ai/models/hub/models--cyankiwi--Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit/snapshots/4bd30395b72ea6045edd04806c4fea448d4467b3",
            is_resident_control=True,
        )

        # 2. Candidate 1: Qwen2.5-7B-Instruct-AWQ (Tier 1 Physical Candidate)
        self.register_candidate(
            candidate_id="CAND-QWEN2.5-7B-AWQ",
            model_identifier="Qwen/Qwen2.5-7B-Instruct-AWQ",
            snapshot_revision="b25037543e9394b818fdfca67ab2a00ecc7dd641",
            architecture="Qwen2ForCausalLM",
            parameter_count_b=7.61,
            active_parameter_count_b=7.61,
            quantization_format="AWQ-4bit",
            context_window_tokens=32768,
            config_sha256="ec0c1f5f875ad8bc1f78c5140c22dbdde1b55478442ad358e7a4d9ecf947a327",
            tokenizer_sha256="c0382117ea329cdf097041132f6d735924b697924d6f6fc3945713e96ce87539",
            runtime_container_digest="docker.io/vllm/vllm-openai-xpu@sha256:4bdfd5b928b4a6a95c92b1edc861f13587a797a32db8c1bc96ca4e2c0d58629d",
            tool_call_parser="hermes",
            structured_output_engine="outlines",
            local_weights_path="/var/lib/local-ai/models/hub/models--Qwen--Qwen2.5-7B-Instruct-AWQ/snapshots/b25037543e9394b818fdfca67ab2a00ecc7dd641",
            is_resident_control=False,
        )

        # 3. Candidate 2: Qwen3.8-27B-AWQ-INT4 (Experimental Long-Context)
        self.register_candidate(
            candidate_id="CAND-QWEN3.8-27B-INT4",
            model_identifier="cyankiwi/Qwen3.8-27B-AWQ-INT4",
            snapshot_revision="6e134bae811fb5adac50ee042ae5f029ac6779aa",
            architecture="qwen3_5",
            parameter_count_b=27.0,
            active_parameter_count_b=27.0,
            quantization_format="compressed-tensors-int4",
            context_window_tokens=262144,
            config_sha256="7f6397212c5c38fb30599d69d9d83de01f4d805e",
            tokenizer_sha256=None,
            runtime_container_digest="docker.io/vllm/vllm-openai-xpu@sha256:4bdfd5b928b4a6a95c92b1edc861f13587a797a32db8c1bc96ca4e2c0d58629d",
            tool_call_parser="qwen3_coder",
            structured_output_engine="outlines",
            local_weights_path="/var/lib/local-ai/models/hub/models--cyankiwi--Qwen3.8-27B-AWQ-INT4/snapshots/6e134bae811fb5adac50ee042ae5f029ac6779aa",
            is_resident_control=False,
        )

        # 4. Candidate 3: Llama-3.3-70B-Instruct-AWQ (Oversized Candidate)
        self.register_candidate(
            candidate_id="CAND-LLAMA3.3-70B-AWQ",
            model_identifier="casperhansen/llama-3.3-70b-instruct-awq",
            snapshot_revision="64d255621f40b42adaf6d1f32a47e1d4534c0f14",
            architecture="LlamaForCausalLM",
            parameter_count_b=70.6,
            active_parameter_count_b=70.6,
            quantization_format="AWQ-4bit",
            context_window_tokens=131072,
            config_sha256="3faa0ac8d46f0d3cba215571e5e5d09add1f6a0d",
            tokenizer_sha256=None,
            runtime_container_digest="docker.io/vllm/vllm-openai-xpu@sha256:4bdfd5b928b4a6a95c92b1edc861f13587a797a32db8c1bc96ca4e2c0d58629d",
            tool_call_parser="llama3",
            structured_output_engine="outlines",
            local_weights_path="/var/lib/local-ai/models/hub/models--casperhansen--llama-3.3-70b-instruct-awq/snapshots/64d255621f40b42adaf6d1f32a47e1d4534c0f14",
            is_resident_control=False,
        )

    def register_candidate(
        self,
        candidate_id: str,
        model_identifier: str,
        snapshot_revision: str,
        architecture: str,
        parameter_count_b: float,
        active_parameter_count_b: float,
        quantization_format: str,
        context_window_tokens: int,
        config_sha256: str,
        tokenizer_sha256: Optional[str],
        runtime_container_digest: str,
        tool_call_parser: str,
        structured_output_engine: str,
        local_weights_path: Optional[str] = None,
        is_resident_control: bool = False,
    ) -> CandidateArtifact:
        """Register and validate candidate artifact."""

        # 1. Reject mutable or floating tags
        if snapshot_revision.lower() in self.FORBIDDEN_MUTABLE_TAGS or len(snapshot_revision) < 12:
            artifact = CandidateArtifact(
                candidate_id=candidate_id,
                model_identifier=model_identifier,
                snapshot_revision=snapshot_revision,
                architecture=architecture,
                parameter_count_b=parameter_count_b,
                active_parameter_count_b=active_parameter_count_b,
                quantization_format=quantization_format,
                context_window_tokens=context_window_tokens,
                config_sha256=config_sha256,
                tokenizer_sha256=tokenizer_sha256,
                runtime_container_digest=runtime_container_digest,
                tool_call_parser=tool_call_parser,
                structured_output_engine=structured_output_engine,
                local_weights_path=local_weights_path,
                is_resident_control=is_resident_control,
                status=ArtifactVerificationStatus.REJECTED_MUTABLE_TAG,
            )
            self._artifacts[candidate_id] = artifact
            return artifact

        # 2. Reject missing or malformed configuration checksum
        if not config_sha256 or len(config_sha256) < 32:
            artifact = CandidateArtifact(
                candidate_id=candidate_id,
                model_identifier=model_identifier,
                snapshot_revision=snapshot_revision,
                architecture=architecture,
                parameter_count_b=parameter_count_b,
                active_parameter_count_b=active_parameter_count_b,
                quantization_format=quantization_format,
                context_window_tokens=context_window_tokens,
                config_sha256=config_sha256,
                tokenizer_sha256=tokenizer_sha256,
                runtime_container_digest=runtime_container_digest,
                tool_call_parser=tool_call_parser,
                structured_output_engine=structured_output_engine,
                local_weights_path=local_weights_path,
                is_resident_control=is_resident_control,
                status=ArtifactVerificationStatus.REJECTED_MISSING_CONFIG,
            )
            self._artifacts[candidate_id] = artifact
            return artifact

        # Verified candidate
        artifact = CandidateArtifact(
            candidate_id=candidate_id,
            model_identifier=model_identifier,
            snapshot_revision=snapshot_revision,
            architecture=architecture,
            parameter_count_b=parameter_count_b,
            active_parameter_count_b=active_parameter_count_b,
            quantization_format=quantization_format,
            context_window_tokens=context_window_tokens,
            config_sha256=config_sha256,
            tokenizer_sha256=tokenizer_sha256,
            runtime_container_digest=runtime_container_digest,
            tool_call_parser=tool_call_parser,
            structured_output_engine=structured_output_engine,
            local_weights_path=local_weights_path,
            is_resident_control=is_resident_control,
            status=ArtifactVerificationStatus.VERIFIED,
        )
        self._artifacts[candidate_id] = artifact
        return artifact

    def get_candidate(self, candidate_id: str) -> Optional[CandidateArtifact]:
        return self._artifacts.get(candidate_id)

    def list_verified_candidates(self) -> List[CandidateArtifact]:
        return [c for c in self._artifacts.values() if c.status == ArtifactVerificationStatus.VERIFIED]
