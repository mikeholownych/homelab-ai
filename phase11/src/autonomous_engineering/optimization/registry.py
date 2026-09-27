"""
Autonomous Engineering System - Phase 11
Workstream B: Candidate Configuration Registry

Maintains immutable, reproducible specifications of model, inference, profile,
and context configurations with canonical content-addressed digests.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Dict, List, Optional


class ExecutionMode(str, Enum):
    PHYSICAL = "PHYSICAL"
    SIMULATED = "SIMULATED"
    HISTORICAL_REPLAY = "HISTORICAL_REPLAY"


class RegistryError(Exception):
    """Base exception for candidate registry errors."""


class DuplicateCandidateError(RegistryError):
    """Raised when registering a candidate with an existing ID."""


class CandidateNotFoundError(RegistryError):
    """Raised when candidate configuration is not found."""


class InvalidCandidateConfigurationError(RegistryError):
    """Raised when candidate configuration is incomplete or violates schema rules."""


@dataclass(frozen=True)
class CandidateConfiguration:
    """An immutable specification of an autonomous engineering system configuration."""
    candidate_id: str
    model_identifier: str
    model_revision: str
    quantization: str
    inference_backend: str
    runtime_parameters: Dict[str, Any]
    agent_profile_id: str
    agent_profile_version: str
    agent_profile_digest: str
    context_strategy_version: str
    reasoning_allocation_policy: str
    tool_adapter_version: str
    physical_resource_requirements: Dict[str, Any]
    evaluation_corpus_version: str
    execution_mode: ExecutionMode
    registered_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def compute_canonical_digest(self) -> str:
        """Computes deterministic 64-character SHA-256 canonical configuration digest."""
        payload = {
            "candidate_id": self.candidate_id,
            "model_identifier": self.model_identifier,
            "model_revision": self.model_revision,
            "quantization": self.quantization,
            "inference_backend": self.inference_backend,
            "runtime_parameters": self.runtime_parameters,
            "agent_profile_id": self.agent_profile_id,
            "agent_profile_version": self.agent_profile_version,
            "agent_profile_digest": self.agent_profile_digest,
            "context_strategy_version": self.context_strategy_version,
            "reasoning_allocation_policy": self.reasoning_allocation_policy,
            "tool_adapter_version": self.tool_adapter_version,
            "physical_resource_requirements": self.physical_resource_requirements,
            "evaluation_corpus_version": self.evaluation_corpus_version,
            "execution_mode": self.execution_mode.value,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class OptimizationCandidateRegistry:
    """
    Authoritative registry of evaluated optimization candidate configurations.
    Enforces immutability, complete specifications, and canonical digest generation.
    """

    def __init__(self) -> None:
        self._candidates: Dict[str, CandidateConfiguration] = {}

    def register_candidate(self, candidate: CandidateConfiguration) -> None:
        """Registers a new candidate configuration, validating all schema invariants."""
        if candidate.candidate_id in self._candidates:
            raise DuplicateCandidateError(
                f"Candidate '{candidate.candidate_id}' already registered in registry"
            )

        # Enforce non-empty mandatory fields
        if not candidate.model_identifier or not candidate.quantization:
            raise InvalidCandidateConfigurationError("Model identifier and quantization cannot be empty")
        if not candidate.agent_profile_id or not candidate.agent_profile_digest:
            raise InvalidCandidateConfigurationError("Agent profile ID and profile digest cannot be empty")
        if not candidate.context_strategy_version or not candidate.reasoning_allocation_policy:
            raise InvalidCandidateConfigurationError("Context strategy and reasoning allocation must be defined")

        self._candidates[candidate.candidate_id] = candidate

    def get_candidate(self, candidate_id: str) -> CandidateConfiguration:
        """Retrieves candidate configuration by ID."""
        candidate = self._candidates.get(candidate_id)
        if not candidate:
            raise CandidateNotFoundError(f"Candidate '{candidate_id}' not found in registry")
        return candidate

    def list_candidates(
        self,
        execution_mode: Optional[ExecutionMode] = None,
    ) -> List[CandidateConfiguration]:
        """Lists registered candidates, optionally filtered by execution mode."""
        if execution_mode:
            return [c for c in self._candidates.values() if c.execution_mode == execution_mode]
        return list(self._candidates.values())

    def register_protected_control(self) -> CandidateConfiguration:
        """Registers the immutable Phase 10 protected control baseline configuration."""
        control = CandidateConfiguration(
            candidate_id="control-b0-qwen3-coder-awq-tp1-v1",
            model_identifier="engineering/b0",
            model_revision="Qwen3-Coder-30B-A3B-Instruct",
            quantization="AWQ-4bit",
            inference_backend="vLLM-XPU-0.6.2",
            runtime_parameters={
                "temperature": 0.0,
                "top_p": 0.95,
                "max_tokens": 4096,
                "tensor_parallel_size": 1,
            },
            agent_profile_id="implementation-engineer",
            agent_profile_version="1.0.0",
            agent_profile_digest="3f2b6a98d01f84e8f96c3a1b8e9d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2f1e0d",
            context_strategy_version="symbol-dependency-v1",
            reasoning_allocation_policy="complexity-bounded-escalation-v1",
            tool_adapter_version="sandboxed-posix-v1",
            physical_resource_requirements={
                "target_device": "Intel Arc Pro B65",
                "vram_allocation_mb": 12800,
                "max_concurrency": 2,
            },
            evaluation_corpus_version="1.0.0",
            execution_mode=ExecutionMode.PHYSICAL,
        )
        self.register_candidate(control)
        return control
