"""Worker Capability Registry Models for Heterogeneous Hardware Configurations."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from autonomous_engineering.core.crypto import content_hash
from autonomous_engineering.core.types import WorkerHealthStatus


@dataclass(frozen=True)
class HardwareTarget:
    device_type: str  # "intel_arc_pro_b65"
    pci_slot: str
    vram_bytes: int
    driver_version: str


@dataclass(frozen=True)
class RuntimeConfig:
    engine: str  # "vllm_xpu", "ipex_llm"
    model_name: str
    model_revision: str
    quantization: str  # "fp8", "int4", "bf16"
    context_window: int
    chat_template: str
    tool_parser: str


@dataclass(frozen=True)
class EmpiricalSkillRecord:
    skill_name: str
    verified: bool
    measured_pass_rate: float
    sample_size: int
    last_evaluated: str


@dataclass(frozen=True)
class WorkerCapabilityProfile:
    profile_id: str
    worker_id: str
    hardware: HardwareTarget
    runtime: RuntimeConfig
    empirical_skills: dict[str, EmpiricalSkillRecord]
    health_status: WorkerHealthStatus = WorkerHealthStatus.HEALTHY

    @property
    def profile_hash(self) -> str:
        payload = {
            "profile_id": self.profile_id,
            "worker_id": self.worker_id,
            "hardware": {
                "device_type": self.hardware.device_type,
                "pci_slot": self.hardware.pci_slot,
                "vram_bytes": self.hardware.vram_bytes,
                "driver_version": self.hardware.driver_version,
            },
            "runtime": {
                "engine": self.runtime.engine,
                "model_name": self.runtime.model_name,
                "model_revision": self.runtime.model_revision,
                "quantization": self.runtime.quantization,
                "context_window": self.runtime.context_window,
                "chat_template": self.runtime.chat_template,
                "tool_parser": self.runtime.tool_parser,
            },
            "empirical_skills": {
                k: {
                    "skill_name": v.skill_name,
                    "verified": v.verified,
                    "measured_pass_rate": v.measured_pass_rate,
                    "sample_size": v.sample_size,
                    "last_evaluated": v.last_evaluated,
                }
                for k, v in sorted(self.empirical_skills.items())
            },
        }
        return content_hash(payload)

    def has_skill(self, skill_name: str, min_pass_rate: float = 0.5) -> bool:
        """Empirically verified skill check."""
        record = self.empirical_skills.get(skill_name)
        if not record:
            return False
        return record.verified and record.measured_pass_rate >= min_pass_rate
