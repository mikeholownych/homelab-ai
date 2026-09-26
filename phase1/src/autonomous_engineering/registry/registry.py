"""Empirical Worker Capability Registry."""
from __future__ import annotations

from autonomous_engineering.core.types import WorkerHealthStatus
from autonomous_engineering.registry.models import EvidenceSource, WorkerCapabilityProfile


class WorkerCapabilityRegistry:
    """Manages empirical worker capability profiles and health states."""

    def __init__(self) -> None:
        self._profiles: dict[str, WorkerCapabilityProfile] = {}

    def register(self, profile: WorkerCapabilityProfile) -> None:
        self._profiles[profile.worker_id] = profile

    def get(self, worker_id: str) -> WorkerCapabilityProfile | None:
        return self._profiles.get(worker_id)

    def set_health(self, worker_id: str, status: WorkerHealthStatus) -> None:
        profile = self._profiles.get(worker_id)
        if profile:
            self._profiles[worker_id] = WorkerCapabilityProfile(
                profile_id=profile.profile_id,
                worker_id=profile.worker_id,
                hardware=profile.hardware,
                runtime=profile.runtime,
                empirical_skills=profile.empirical_skills,
                health_status=status,
            )

    def list_healthy_workers(self) -> list[WorkerCapabilityProfile]:
        return [
            p for p in self._profiles.values()
            if p.health_status == WorkerHealthStatus.HEALTHY
        ]

    def get_qualified_workers(
        self,
        skill_name: str,
        min_pass_rate: float = 0.5,
        require_deployed_evidence: bool = False,
    ) -> list[WorkerCapabilityProfile]:
        """Find healthy workers with verified empirical capability for a skill."""
        qualified = [
            p for p in self.list_healthy_workers()
            if p.has_skill(skill_name, min_pass_rate=min_pass_rate)
            and (
                not require_deployed_evidence
                or p.empirical_skills[skill_name].evidence_source == EvidenceSource.EMPIRICAL_DEPLOYED_MEASUREMENT
            )
        ]
        # Rank by highest empirical pass rate
        return sorted(
            qualified,
            key=lambda p: p.empirical_skills[skill_name].measured_pass_rate,
            reverse=True,
        )
