"""
Autonomous Engineering System - Phase 9
Workstream D: Capability-Aware Model Scheduling

Implements a two-stage scheduling pipeline:
1. Hard Eligibility Gate: filters out candidates failing qualification, context, tool, or resource checks.
2. End-to-End Cost Optimization: ranks eligible candidates by expected total cost of an accepted outcome.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from autonomous_engineering.capabilities.registry import (
    ModelCapabilityRecord,
    ModelCapabilityRegistry,
    QualificationKey,
)
from autonomous_engineering.classifier.classifier import WorkloadRequirements
from autonomous_engineering.profiles.registry import (
    AgentProfile,
    VersionedAgentProfileRegistry,
)
from autonomous_engineering.resources.manager import (
    PhysicalInferenceResourceManager,
    PhysicalWorkerState,
)


class SchedulingPolicyVersion(str, Enum):
    V1_EXPECTED_COST_MINIMIZER = "v1-expected-cost-minimizer"


class SchedulingError(Exception):
    """Base exception for scheduler failures."""


class NoQualifiedCandidateError(SchedulingError):
    """Raised when no model configuration satisfies all hard eligibility gates."""


@dataclass(frozen=True)
class CandidateEvaluation:
    """Detailed record of eligibility and cost scoring for a model-profile candidate."""
    profile_id: str
    profile_digest: str
    model_identifier: str
    model_revision: str
    is_eligible: bool
    disqualification_reasons: List[str]
    estimated_inference_latency_sec: float
    estimated_queue_wait_sec: float
    model_reload_cost: float
    context_construction_cost: float
    expected_repairs: float
    validation_cost: float
    total_expected_cost: float


@dataclass(frozen=True)
class SchedulingDecision:
    """
    Authoritative, reproducible scheduling decision record.
    """
    decision_id: str
    work_order_id: str
    workload_id: str
    policy_version: SchedulingPolicyVersion
    selected_profile_id: str
    selected_profile_digest: str
    selected_model_identifier: str
    selected_model_revision: str
    assigned_worker_id: str
    total_expected_cost: float
    candidate_evaluations: List[CandidateEvaluation]
    decided_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class CapabilityAwareModelScheduler:
    """
    Schedules specialized agent operations by filtering hard capability constraints
    and optimizing expected end-to-end engineering costs.
    """

    def __init__(
        self,
        profile_registry: VersionedAgentProfileRegistry,
        capability_registry: ModelCapabilityRegistry,
        resource_manager: PhysicalInferenceResourceManager,
        qualification_suite_version: str = "v1",
        policy_version: SchedulingPolicyVersion = SchedulingPolicyVersion.V1_EXPECTED_COST_MINIMIZER,
    ) -> None:
        self.profile_registry = profile_registry
        self.capability_registry = capability_registry
        self.resource_manager = resource_manager
        self.qualification_suite_version = qualification_suite_version
        self.policy_version = policy_version

    def schedule_operation(
        self,
        work_order_id: str,
        requirements: WorkloadRequirements,
        target_specialization: str,
        inference_config_digest: str = "default-awq-config-v1",
    ) -> SchedulingDecision:
        """
        Executes two-stage scheduling:
        1. Hard constraint filtering across all candidate model-profile pairs.
        2. Expected cost optimization on eligible candidates.
        Fails closed with NoQualifiedCandidateError if no candidate is eligible.
        """
        # 1. Resolve agent profile for the specialization
        profile = self._resolve_profile_for_specialization(target_specialization)
        profile_digest = profile.compute_digest()

        # 2. Evaluate all known models
        evaluations: List[CandidateEvaluation] = []
        eligible_candidates: List[CandidateEvaluation] = []

        all_workers = self.resource_manager.list_workers()
        known_models = set(w.resident_model_identifier for w in all_workers)
        # Also include any models registered in capability registry
        for cap in [self.capability_registry.get_model_capability("engineering/b0"),
                    self.capability_registry.get_model_capability("reviewer/phi4-calibrated")]:
            if cap:
                known_models.add(cap.model_identifier)

        for model_id in sorted(list(known_models)):
            eval_record = self._evaluate_candidate(
                profile=profile,
                profile_digest=profile_digest,
                model_identifier=model_id,
                requirements=requirements,
                inference_config_digest=inference_config_digest,
            )
            evaluations.append(eval_record)
            if eval_record.is_eligible:
                eligible_candidates.append(eval_record)

        if not eligible_candidates:
            disqualifications = {
                e.model_identifier: e.disqualification_reasons for e in evaluations
            }
            raise NoQualifiedCandidateError(
                f"No qualified candidate available for work order {work_order_id} (profile={profile.profile_id}, workload={requirements.task_class}). Exclusions: {disqualifications}"
            )

        # 3. Cost optimization: select candidate with minimum total expected cost
        best_candidate = min(eligible_candidates, key=lambda c: c.total_expected_cost)

        # 4. Allocate a healthy worker for this model
        worker = self.resource_manager.allocate_worker_for_request(
            best_candidate.model_identifier,
            requirements.context_demand_tokens,
        )

        decision = SchedulingDecision(
            decision_id=f"sched-{work_order_id}-{target_specialization}",
            work_order_id=work_order_id,
            workload_id=requirements.workload_id,
            policy_version=self.policy_version,
            selected_profile_id=best_candidate.profile_id,
            selected_profile_digest=best_candidate.profile_digest,
            selected_model_identifier=best_candidate.model_identifier,
            selected_model_revision=best_candidate.model_revision,
            assigned_worker_id=worker.worker_id,
            total_expected_cost=best_candidate.total_expected_cost,
            candidate_evaluations=evaluations,
        )

        return decision

    def _resolve_profile_for_specialization(self, specialization: str) -> AgentProfile:
        """Finds active profile matching the requested specialization or profile_id."""
        for p in [
            "repo-investigator",
            "systems-architect",
            "implementation-engineer",
            "test-engineer",
            "security-reviewer",
            "performance-analyst",
            "integration-reviewer",
            "incident-investigator",
        ]:
            prof = self.profile_registry.get_profile(p, "1.0.0")
            if prof.profile_id == specialization or specialization in prof.profile_id:
                return prof
        # Fallback to repo-investigator
        return self.profile_registry.get_profile("repo-investigator", "1.0.0")

    def _evaluate_candidate(
        self,
        profile: AgentProfile,
        profile_digest: str,
        model_identifier: str,
        requirements: WorkloadRequirements,
        inference_config_digest: str,
    ) -> CandidateEvaluation:
        """Evaluates hard constraints and computes cost function for a model candidate."""
        disqualifications: List[str] = []
        cap = self.capability_registry.get_model_capability(model_identifier)

        if not cap:
            return CandidateEvaluation(
                profile_id=profile.profile_id,
                profile_digest=profile_digest,
                model_identifier=model_identifier,
                model_revision="unknown",
                is_eligible=False,
                disqualification_reasons=["Model not registered in capability registry"],
                estimated_inference_latency_sec=9999.0,
                estimated_queue_wait_sec=9999.0,
                model_reload_cost=9999.0,
                context_construction_cost=9999.0,
                expected_repairs=999.0,
                validation_cost=999.0,
                total_expected_cost=99999.0,
            )

        # 1. Hard Gate: Context Capacity
        if cap.context_capacity < requirements.context_demand_tokens:
            disqualifications.append(
                f"Context capacity ({cap.context_capacity}) < required ({requirements.context_demand_tokens})"
            )

        # 2. Hard Gate: Tool Compatibility
        required_tools = set(profile.permitted_tool_capabilities) & set(requirements.required_tools)
        if required_tools and not cap.supports_tool_calling:
            disqualifications.append("Model lacks required tool calling support")

        # 3. Hard Gate: Qualification Verification (5-tuple key)
        key = QualificationKey(
            profile_digest=profile_digest,
            model_revision=cap.model_revision,
            inference_config_digest=inference_config_digest,
            workload_class=requirements.task_class,
            qualification_suite_version=self.qualification_suite_version,
        )
        is_qual = self.capability_registry.is_qualified(key)
        if not is_qual:
            disqualifications.append(
                f"Model configuration not qualified for workload '{requirements.task_class}'"
            )

        # 4. Check worker availability and residency
        workers = [
            w for w in self.resource_manager.list_workers()
            if w.resident_model_identifier == model_identifier
        ]
        is_resident = len(workers) > 0
        if not is_resident and not self.resource_manager.allow_model_swaps:
            disqualifications.append(
                f"Model '{model_identifier}' is not currently resident and model swaps are prohibited"
            )

        # Compute cost components
        cert = self.capability_registry.get_qualification_certificate(key)
        historical_repair = cert.average_repair_count if cert else 1.0

        # Estimated latency based on token demand and speed
        tokens_to_gen = min(cap.output_capacity, profile.max_reasoning_budget)
        speed = max(1.0, cap.measured_tokens_per_sec)
        infer_latency = round((cap.measured_ttft_ms / 1000.0) + (tokens_to_gen / speed), 2)

        # Queue delay
        queue_depth = sum(w.active_requests for w in workers) if workers else 0
        queue_wait = queue_depth * (infer_latency * 0.5)

        # Reload cost: 0 if resident, high penalty if swap needed
        reload_cost = 0.0 if is_resident else 120.0

        # Context cost
        context_cost = round((requirements.context_demand_tokens / 16384.0) * 1.5, 2)

        # Validation cost
        validation_cost = 2.0 * len(requirements.mandatory_validation_suites)

        # Total expected cost:
        # Cost = Latency + Wait + Reload + Context + (Repairs * (Latency + Validation)) + Base Validation
        total_cost = round(
            infer_latency
            + queue_wait
            + reload_cost
            + context_cost
            + (historical_repair * (infer_latency + validation_cost))
            + validation_cost,
            2,
        )

        is_eligible = len(disqualifications) == 0

        return CandidateEvaluation(
            profile_id=profile.profile_id,
            profile_digest=profile_digest,
            model_identifier=model_identifier,
            model_revision=cap.model_revision,
            is_eligible=is_eligible,
            disqualification_reasons=disqualifications,
            estimated_inference_latency_sec=infer_latency,
            estimated_queue_wait_sec=queue_wait,
            model_reload_cost=reload_cost,
            context_construction_cost=context_cost,
            expected_repairs=historical_repair,
            validation_cost=validation_cost,
            total_expected_cost=total_cost if is_eligible else 99999.0,
        )
