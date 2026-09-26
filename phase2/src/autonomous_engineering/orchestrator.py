"""Autonomous Engineering Orchestrator Control Plane."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from autonomous_engineering.artifacts.models import ArtifactRecord
from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.authority.admission import AdmissionDecision, AdmissionEvaluator
from autonomous_engineering.authority.guard import ScopeGuard, ScopeViolationError
from autonomous_engineering.authority.tokens import CapabilityToken
from autonomous_engineering.core.types import (
    ArtifactType,
    FailureClass,
    TaskStepState,
    ValidationStatus,
    WorkOrderState,
)
from autonomous_engineering.planning.models import ExecutionPlan, TaskStepDefinition
from autonomous_engineering.planning.planner import ExecutionPlanner
from autonomous_engineering.repair.controller import BoundedRepairController
from autonomous_engineering.review.models import (
    FindingSeverity,
    ReviewDisposition,
    ReviewFinding,
    ReviewReport,
)
from autonomous_engineering.router.router import CapabilityRouter, RoutingDecision
from autonomous_engineering.validator.independent import IndependentValidator, ValidationVerdict
from autonomous_engineering.workers.simulated import BaseWorker
from autonomous_engineering.workflow.engine import WorkflowEngine, WorkflowEngineError
from autonomous_engineering.work_order.models import WorkOrder


class OrchestrationError(RuntimeError):
    def __init__(self, message: str, failure_class: FailureClass | None = None) -> None:
        super().__init__(message)
        self.failure_class = failure_class


class OrchestratorControlPlane:
    """The authoritative execution control plane for autonomous engineering work orders.

    Invariants:
    - Sole authority for admission, capability issuance, and state transitions.
    - Workers and routers cannot grant permissions or declare tasks accepted.
    - Independent validator is isolated from worker manipulation.
    - Preserves all rejected attempts as diagnostic evidence.
    """

    def __init__(
        self,
        admission_evaluator: AdmissionEvaluator,
        planner: ExecutionPlanner,
        router: CapabilityRouter,
        engine: WorkflowEngine,
        artifact_store: ArtifactStore,
        validator: IndependentValidator,
        repair_controller: BoundedRepairController,
        workers: dict[str, BaseWorker],
        baseline_repo_dir: Path,
        enable_review_repair: bool = True,
    ) -> None:
        self.admission_evaluator = admission_evaluator
        self.planner = planner
        self.router = router
        self.engine = engine
        self.artifact_store = artifact_store
        self.validator = validator
        self.repair_controller = repair_controller
        self.workers = workers
        self.baseline_repo_dir = baseline_repo_dir
        self.enable_review_repair = enable_review_repair

    def execute_work_order(
        self,
        work_order: WorkOrder,
        human_approval_present: bool = True,
    ) -> WorkOrderState:
        """Execute a work order end-to-end through admission, planning, dispatch, and validation."""
        # 1. Admission Evaluation
        admission: AdmissionDecision = self.admission_evaluator.evaluate(
            work_order, human_approval_present=human_approval_present
        )
        if not admission.admitted:
            self.engine.register_work_order(work_order)
            self.engine.set_terminal_disposition(
                work_order.work_order_id,
                work_order.version,
                f"ADMISSION_DENIED: {admission.reason}",
                WorkOrderState.UNAUTHORIZED,
            )
            return WorkOrderState.UNAUTHORIZED

        admitted_wo = admission.admitted_work_order
        token = admission.token
        assert admitted_wo is not None and token is not None

        self.engine.register_work_order(admitted_wo)

        # 2. Planning
        plan = self.planner.create_plan(admitted_wo)
        self.engine.initialize_plan(plan)

        # 3. Execution of DAG Steps
        author_worker_id: str | None = None
        produced_patch_artifact: ArtifactRecord | None = None
        step_artifacts: dict[str, ArtifactRecord] = {}
        last_review_report: ReviewReport | None = None

        # Run investigation, synthesis, and review steps
        for step in plan.steps:
            if step.step_id == "step-validate":
                continue  # Validation step executed separately by independent validator

            # Check ready status
            assignment_info = self._find_assignment(admitted_wo.work_order_id, admitted_wo.version, step.step_id)
            if not assignment_info:
                raise OrchestrationError(f"Missing assignment for step {step.step_id}")

            assignment_id = assignment_info["assignment_id"]

            # Route to qualified worker
            exclude = {author_worker_id} if author_worker_id and step.required_role == "independent_review" else set()
            routing = self.router.route(step, exclude_worker_ids=exclude)
            worker = self.workers.get(routing.selected_worker_id)
            if not worker:
                raise OrchestrationError(f"Worker {routing.selected_worker_id} not registered")

            if step.required_role in ("defect_patch", "implementation", "test_development", "maintainability_refactor", "bounded_repair"):
                author_worker_id = worker.worker_id

            # Acquire durable lease with monotonic fencing token
            fencing_token = self.engine.acquire_lease(assignment_id, worker.worker_id)

            # Input artifacts for this step
            input_arts = tuple(
                step_artifacts[dep_id] for dep_id in step.dependencies if dep_id in step_artifacts
            )

            # Worker execution under ScopeGuard
            try:
                result = worker.execute(
                    assignment_id=assignment_id,
                    step=step,
                    token=token,
                    fencing_token=fencing_token,
                    input_artifacts=input_arts,
                    repo_dir=self.baseline_repo_dir,
                )
            except ScopeViolationError as exc:
                self.engine.set_terminal_disposition(
                    admitted_wo.work_order_id,
                    admitted_wo.version,
                    f"FAILED_SECURITY_VIOLATION: {exc}",
                    WorkOrderState.FAILED_SECURITY_VIOLATION,
                )
                return WorkOrderState.FAILED_SECURITY_VIOLATION

            # Commit completion to durable engine
            self.engine.complete_assignment(
                assignment_id=assignment_id,
                fencing_token=fencing_token,
                output_artifact_hash=result.output_artifact.artifact_hash,
            )

            step_artifacts[step.step_id] = result.output_artifact
            if step.output_artifact_type == ArtifactType.PATCH:
                produced_patch_artifact = result.output_artifact
            elif step.output_artifact_type == ArtifactType.REVIEW_REPORT:
                try:
                    raw_report = json.loads(self.artifact_store.get(result.output_artifact.artifact_hash).decode("utf-8"))
                    findings = tuple(
                        ReviewFinding(
                            finding_id=f["finding_id"],
                            severity=FindingSeverity(f["severity"]),
                            file_path=f["file_path"],
                            line_number=f.get("line_number"),
                            description=f["description"],
                            suggested_action=f["suggested_action"],
                        )
                        for f in raw_report.get("findings", [])
                    )
                    last_review_report = ReviewReport(
                        report_id=raw_report["report_id"],
                        target_artifact_hash=raw_report["target_artifact_hash"],
                        reviewer_worker_id=raw_report["reviewer_worker_id"],
                        disposition=ReviewDisposition(raw_report["disposition"]),
                        findings=findings,
                        summary=raw_report["summary"],
                        is_advisory=raw_report.get("is_advisory", True),
                    )
                except Exception:
                    pass

            self.engine.advance_ready_tasks(plan)

        if not produced_patch_artifact:
            self.engine.set_terminal_disposition(
                admitted_wo.work_order_id,
                admitted_wo.version,
                "FAILED_NO_PATCH_PRODUCED",
                WorkOrderState.REJECTED,
            )
            return WorkOrderState.REJECTED

        # Optional Pre-Validation Bounded Repair triggered by review recommendation
        if (
            self.enable_review_repair
            and last_review_report
            and last_review_report.disposition in (ReviewDisposition.RECOMMEND_REVISE, ReviewDisposition.BLOCK)
        ):
            repair_wo = self.repair_controller.prepare_repair_work_order(
                current_wo=admitted_wo,
                failed_artifact=produced_patch_artifact,
                review_report=last_review_report,
            )
            if repair_wo:
                self.engine.supersede_work_order(admitted_wo.work_order_id, admitted_wo.version)
                return self.execute_work_order(repair_wo, human_approval_present=human_approval_present)

        # 4. Independent Validation
        val_assignment = self._find_assignment(admitted_wo.work_order_id, admitted_wo.version, "step-validate")
        if val_assignment:
            self.engine.acquire_lease(val_assignment["assignment_id"], "system-validator")

        verdict: ValidationVerdict = self.validator.validate(
            artifact=produced_patch_artifact,
            criteria=admitted_wo.acceptance.criteria,
            baseline_repo_dir=self.baseline_repo_dir,
        )

        if val_assignment:
            self.engine.complete_assignment(
                assignment_id=val_assignment["assignment_id"],
                fencing_token=val_assignment["fencing_token"] + 1,
                output_artifact_hash=getattr(verdict, "record_hash", "") or verdict.verdict_hash,
            )

        if verdict.status == ValidationStatus.ACCEPTED:
            self.engine.set_terminal_disposition(
                admitted_wo.work_order_id,
                admitted_wo.version,
                "ACCEPTED",
                WorkOrderState.ACCEPTED,
            )
            return WorkOrderState.ACCEPTED

        # Validation failed -> trigger Bounded Repair Controller
        repair_wo = self.repair_controller.prepare_repair_work_order(
            current_wo=admitted_wo,
            failed_artifact=produced_patch_artifact,
            verdict=verdict,
            review_report=last_review_report,
        )

        if not repair_wo:
            # Budget exhausted
            self.engine.set_terminal_disposition(
                admitted_wo.work_order_id,
                admitted_wo.version,
                "FAILED_BUDGET_EXHAUSTED",
                WorkOrderState.FAILED_BUDGET_EXHAUSTED,
            )
            return WorkOrderState.FAILED_BUDGET_EXHAUSTED

        # Supersede current version and execute repair work order
        self.engine.supersede_work_order(admitted_wo.work_order_id, admitted_wo.version)
        return self.execute_work_order(repair_wo, human_approval_present=human_approval_present)

    def _find_assignment(
        self, work_order_id: str, version: int, step_id: str
    ) -> dict[str, Any] | None:
        assignments = self.engine.list_assignments(work_order_id, version)
        for a in assignments:
            if a["step_id"] == step_id:
                return a
        return None
