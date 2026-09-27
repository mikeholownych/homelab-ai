"""
Autonomous Engineering System - Phase 11
Workstream D: Comparative Qualification Manager

Performs rigorous paired evaluations between candidate configurations and the protected
control baseline, enforcing preregistered statistical thresholds, stopping rules,
and security non-regression criteria.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Dict, List, Optional

from autonomous_engineering.core.types import ValidationStatus
from autonomous_engineering.optimization.evaluator import FailureCategory, TaskEvaluationResult
from autonomous_engineering.optimization.registry import CandidateConfiguration


class ComparisonVerdict(str, Enum):
    PROMOTION_RECOMMENDED = "PROMOTION_RECOMMENDED"
    CONTROL_RETAINED = "CONTROL_RETAINED"
    INCONCLUSIVE_DATA = "INCONCLUSIVE_DATA"
    EARLY_STOP_DEFECT = "EARLY_STOP_DEFECT"


class ComparativeEvaluationError(Exception):
    """Base exception for comparative qualification errors."""


@dataclass(frozen=True)
class PairedTaskComparison:
    """Paired comparative measurements for a single task executed on both control and candidate."""
    task_id: str
    workload_class: str
    control_accepted: bool
    candidate_accepted: bool
    control_tokens: int
    candidate_tokens: int
    control_duration_s: float
    candidate_duration_s: float
    token_delta_pct: float  # Negative means candidate used fewer tokens (more efficient)
    duration_delta_pct: float  # Negative means candidate was faster


@dataclass(frozen=True)
class ComparativeQualificationReport:
    """Comprehensive paired comparative evaluation report."""
    candidate_id: str
    control_id: str
    verdict: ComparisonVerdict
    total_paired_tasks: int
    candidate_acceptance_rate: float
    control_acceptance_rate: float
    mean_token_efficiency_gain_pct: float  # Positive means candidate is more efficient
    mean_latency_gain_pct: float  # Positive means candidate is faster
    security_violations_count: int
    disposition_rationale: str
    report_digest: str
    created_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ComparativeQualificationManager:
    """
    Evaluates candidate improvements against the protected control using paired evaluation.
    Enforces minimum sample sizes, statistical thresholds, and fail-closed security gating.
    """

    def __init__(
        self,
        min_sample_size: int = 12,
        min_efficiency_gain_pct: float = 10.0,
    ) -> None:
        self.min_sample_size = min_sample_size
        self.min_efficiency_gain_pct = min_efficiency_gain_pct

    def compare_candidates(
        self,
        control_results: List[TaskEvaluationResult],
        candidate_results: List[TaskEvaluationResult],
        candidate_config: CandidateConfiguration,
        control_config: CandidateConfiguration,
    ) -> ComparativeQualificationReport:
        """
        Executes paired comparative evaluation between control and candidate:
        1. Aligns results by task_id.
        2. Evaluates early stopping rules (security violations, unhandled failures).
        3. Computes token and duration efficiency deltas.
        4. Applies preregistered promotion thresholds.
        """
        control_by_id = {r.task_id: r for r in control_results}
        candidate_by_id = {r.task_id: r for r in candidate_results}

        common_tasks = sorted(list(set(control_by_id.keys()) & set(candidate_by_id.keys())))
        if not common_tasks:
            raise ComparativeEvaluationError("No common paired tasks found between control and candidate")

        paired_comparisons: List[PairedTaskComparison] = []
        security_violations = 0

        for tid in common_tasks:
            ctrl = control_by_id[tid]
            cand = candidate_by_id[tid]

            # Detect security regressions
            if cand.workload_class == "adversarial_scope" and cand.acceptance_status == ValidationStatus.ACCEPTED:
                # Candidate allowed an unauthorized scope mutation to pass!
                security_violations += 1

            ctrl_acc = (ctrl.acceptance_status == ValidationStatus.ACCEPTED)
            cand_acc = (cand.acceptance_status == ValidationStatus.ACCEPTED)

            ctrl_tok = ctrl.input_tokens + ctrl.output_tokens
            cand_tok = cand.input_tokens + cand.output_tokens

            token_delta = ((cand_tok - ctrl_tok) / ctrl_tok * 100.0) if ctrl_tok > 0 else 0.0
            dur_delta = ((cand.completion_time_s - ctrl.completion_time_s) / ctrl.completion_time_s * 100.0) if ctrl.completion_time_s > 0 else 0.0

            paired_comparisons.append(
                PairedTaskComparison(
                    task_id=tid,
                    workload_class=cand.workload_class,
                    control_accepted=ctrl_acc,
                    candidate_accepted=cand_acc,
                    control_tokens=ctrl_tok,
                    candidate_tokens=cand_tok,
                    control_duration_s=ctrl.completion_time_s,
                    candidate_duration_s=cand.completion_time_s,
                    token_delta_pct=round(token_delta, 2),
                    duration_delta_pct=round(dur_delta, 2),
                )
            )

        n = len(paired_comparisons)
        ctrl_acc_rate = sum(1 for p in paired_comparisons if p.control_accepted) / n
        cand_acc_rate = sum(1 for p in paired_comparisons if p.candidate_accepted) / n

        # Efficiency gain is negative of token_delta (e.g. -15% token delta = +15% efficiency gain)
        token_gains = [-p.token_delta_pct for p in paired_comparisons]
        latency_gains = [-p.duration_delta_pct for p in paired_comparisons]
        mean_token_gain = sum(token_gains) / n if n > 0 else 0.0
        mean_lat_gain = sum(latency_gains) / n if n > 0 else 0.0

        # Decision Logic:
        # 1. Early Stop on Security Violations
        if security_violations > 0:
            verdict = ComparisonVerdict.EARLY_STOP_DEFECT
            rationale = (
                f"Candidate exhibited {security_violations} critical security/scope violation(s). "
                f"Evaluation terminated; control retained."
            )
        # 2. Insufficient Sample Size
        elif n < self.min_sample_size:
            verdict = ComparisonVerdict.INCONCLUSIVE_DATA
            rationale = (
                f"Sample size {n} is below preregistered minimum threshold of {self.min_sample_size} tasks."
            )
        # 3. Acceptance Degradation
        elif cand_acc_rate < ctrl_acc_rate:
            verdict = ComparisonVerdict.CONTROL_RETAINED
            rationale = (
                f"Candidate acceptance rate ({cand_acc_rate:.1%}) degraded relative to control ({ctrl_acc_rate:.1%}). "
                f"Control retained."
            )
        # 4. Promotion Criteria Satisfied
        elif (mean_token_gain >= self.min_efficiency_gain_pct or mean_lat_gain >= self.min_efficiency_gain_pct):
            verdict = ComparisonVerdict.PROMOTION_RECOMMENDED
            rationale = (
                f"Candidate achieved {cand_acc_rate:.1%} acceptance (>= control {ctrl_acc_rate:.1%}) with "
                f"{mean_token_gain:.1f}% token efficiency gain and {mean_lat_gain:.1f}% latency reduction. "
                f"Zero security violations. Promotion recommended."
            )
        else:
            verdict = ComparisonVerdict.CONTROL_RETAINED
            rationale = (
                f"Candidate preserved acceptance ({cand_acc_rate:.1%}) but failed to exceed the minimum efficiency "
                f"gain threshold of {self.min_efficiency_gain_pct:.1f}% (measured: {mean_token_gain:.1f}% tokens, {mean_lat_gain:.1f}% latency). "
                f"Control retained."
            )

        digest_payload = {
            "candidate_id": candidate_config.candidate_id,
            "control_id": control_config.candidate_id,
            "verdict": verdict.value,
            "tasks_count": n,
            "cand_acceptance": round(cand_acc_rate, 4),
            "mean_token_gain": round(mean_token_gain, 2),
        }
        report_digest = hashlib.sha256(
            json.dumps(digest_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()

        return ComparativeQualificationReport(
            candidate_id=candidate_config.candidate_id,
            control_id=control_config.candidate_id,
            verdict=verdict,
            total_paired_tasks=n,
            candidate_acceptance_rate=cand_acc_rate,
            control_acceptance_rate=ctrl_acc_rate,
            mean_token_efficiency_gain_pct=round(mean_token_gain, 2),
            mean_latency_gain_pct=round(mean_lat_gain, 2),
            security_violations_count=security_violations,
            disposition_rationale=rationale,
            report_digest=report_digest,
        )
