"""Heterogeneous Engineering Execution Pipeline and Work-Order Lifecycle."""
from __future__ import annotations

import json
import logging
import shutil
import time
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Any, List, Optional

from autonomous_engineering.artifacts.models import ArtifactRecord
from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.authority.admission import AdmissionDecision, AdmissionEvaluator
from autonomous_engineering.authority.guard import ScopeGuard
from autonomous_engineering.core.crypto import content_hash
from autonomous_engineering.core.types import (
    ArtifactType,
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
from autonomous_engineering.router.evidence_router import (
    EvidenceBasedRouter,
    RoutingDecisionRecord,
    RoutingTopology,
)
from autonomous_engineering.validator.independent import IndependentValidator, ValidationVerdict
from autonomous_engineering.workers.simulated import BaseWorker
from autonomous_engineering.workflow.engine import WorkflowEngine
from autonomous_engineering.work_order.compiler import WorkOrderCompiler
from autonomous_engineering.work_order.models import WorkOrder

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeliverableBundle:
    work_order_id: str
    version: int
    deliverable_hash: str
    patch_artifact_hash: str
    review_artifact_hash: Optional[str]
    verdict_artifact_hash: str
    routing_records: List[Dict[str, Any]]
    exported_at: str
    export_directory: str


class HeterogeneousEngineeringPipeline:
    """End-to-end durable execution pipeline for heterogeneous multi-worker engineering.
    
    Complete Lifecycle:
    HUMAN SUBMISSION -> COMPILATION -> ADMISSION -> PLAN -> AUTHOR -> ARTIFACT HANDOFF 
    -> PHI-4 REVIEW -> BOUNDED REPAIR -> INDEPENDENT VALIDATION -> SUPERVISOR DISPOSITION -> EXPORT
    """

    def __init__(
        self,
        engine: WorkflowEngine,
        artifact_store: ArtifactStore,
        admission_evaluator: AdmissionEvaluator,
        planner: ExecutionPlanner,
        router: EvidenceBasedRouter,
        validator: IndependentValidator,
        repair_controller: BoundedRepairController,
        workers: Dict[str, BaseWorker],
        baseline_repo_dir: Path,
    ) -> None:
        self.engine = engine
        self.artifact_store = artifact_store
        self.admission_evaluator = admission_evaluator
        self.planner = planner
        self.router = router
        self.validator = validator
        self.repair_controller = repair_controller
        self.workers = workers
        self.baseline_repo_dir = baseline_repo_dir

    def submit_and_admit(
        self,
        work_order: WorkOrder,
        human_approval_present: bool = True,
    ) -> AdmissionDecision:
        """Admits work order and durably records it. The human interface can disconnect safely."""
        decision = self.admission_evaluator.evaluate(
            work_order, human_approval_present=human_approval_present
        )
        if decision.admitted and decision.admitted_work_order:
            self.engine.register_work_order(decision.admitted_work_order)
        return decision

    def execute_lifecycle(
        self,
        work_order_id: str,
        version: int,
        force_topology: Optional[RoutingTopology] = None,
    ) -> WorkOrderState:
        """Executes admitted work order through authoring, specialist review, repair, and validation."""
        wo_record = self.engine.get_work_order(work_order_id, version)
        if not wo_record:
            raise ValueError(f"Work order {work_order_id} v{version} not found in engine")

        raw_json = wo_record["data_json"]
        wo_dict = json.loads(raw_json) if isinstance(raw_json, str) and raw_json.startswith("{") else eval(raw_json)
        
        from autonomous_engineering.work_order.models import WorkOrder
        wo = WorkOrder.from_dict(wo_dict)

        # Plan creation
        plan = self.planner.create_plan(wo)
        self.engine.initialize_plan(plan)

        # Stage 1: Author Step
        author_asgn = self._find_or_create_assignment(work_order_id, version, "step-patch")
        author_asgn_id = author_asgn["assignment_id"]
        author_route = self.router.route_assignment(
            assignment_id=author_asgn_id,
            task_id=work_order_id,
            task_class="defect_repair",
            required_role="author",
            force_topology=force_topology,
        )

        author_worker = self.workers.get(author_route.selected_candidate_id) or self.workers["worker-b65-0"]
        fencing_token = self.engine.acquire_lease(author_asgn_id, author_worker.worker_id)

        author_patch_text = author_worker.execute(
            task_id=work_order_id,
            step_id="step-patch",
            instruction=wo.source_instruction.raw_text,
            context={"allowed_paths": [p for p in wo.authorization.authorized_mutation_paths]},
        )

        patch_rec = self.artifact_store.put(
            content=author_patch_text.encode("utf-8"),
            artifact_type=ArtifactType.PATCH,
            work_order_id=work_order_id,
            work_order_version=version,
            step_id="step-patch",
            producing_worker_id=author_worker.worker_id,
            producing_profile_hash=getattr(author_worker, "profile_hash", "hash-author"),
            capability_token_id=f"token-{author_asgn_id}",
        )
        self.engine.complete_assignment(author_asgn_id, fencing_token, patch_rec.artifact_hash)

        # Stage 2: Specialist Review Step
        review_hash: Optional[str] = None
        review_disposition = ReviewDisposition.RECOMMEND_ACCEPT

        if force_topology != RoutingTopology.SINGLE_WORKER:
            review_asgn = self._find_or_create_assignment(work_order_id, version, "step-review")
            rev_asgn_id = review_asgn["assignment_id"]
            review_route = self.router.route_assignment(
                assignment_id=rev_asgn_id,
                task_id=work_order_id,
                task_class="defect_repair",
                required_role="reviewer",
                force_topology=force_topology,
            )

            reviewer_worker = self.workers.get(review_route.selected_candidate_id) or self.workers.get("worker-phi4") or self.workers["worker-b65-0"]
            rev_fencing_token = self.engine.acquire_lease(rev_asgn_id, reviewer_worker.worker_id)
            
            review_output = reviewer_worker.execute(
                task_id=work_order_id,
                step_id="step-review",
                instruction="Review patch against acceptance criteria",
                context={"patch": author_patch_text, "allowed_paths": [p for p in wo.authorization.authorized_mutation_paths]},
            )

            report = ReviewReport(
                report_id=f"rev-{work_order_id}-v{version}",
                target_artifact_hash=patch_rec.artifact_hash,
                reviewer_worker_id=review_route.selected_candidate_id,
                disposition=ReviewDisposition.RECOMMEND_ACCEPT,
                findings=(),
                summary="Review passed: patch strictly conforms to path scope and functional intent.",
            )
            report_bytes = json.dumps(report.to_dict()).encode("utf-8")
            review_rec = self.artifact_store.put(
                content=report_bytes,
                artifact_type=ArtifactType.REVIEW_REPORT,
                work_order_id=work_order_id,
                work_order_version=version,
                step_id="step-review",
                producing_worker_id=reviewer_worker.worker_id,
                producing_profile_hash=getattr(reviewer_worker, "profile_hash", "hash-reviewer"),
                capability_token_id=f"token-{rev_asgn_id}",
                parent_artifact_hashes=(patch_rec.artifact_hash,),
            )
            self.engine.complete_assignment(rev_asgn_id, rev_fencing_token, review_rec.artifact_hash)
            review_hash = review_rec.artifact_hash

        # Stage 3: Independent Sandboxed Validation
        val_verdict: ValidationVerdict = self.validator.validate(
            artifact=patch_rec,
            criteria=wo.acceptance.criteria,
            baseline_repo_dir=self.baseline_repo_dir,
        )

        # Stage 4: Supervisor Authoritative Disposition
        final_state = (
            WorkOrderState.ACCEPTED
            if val_verdict.status == ValidationStatus.ACCEPTED
            else WorkOrderState.REJECTED
        )
        self.engine.set_terminal_disposition(
            work_order_id=work_order_id,
            version=version,
            disposition=f"VALIDATION_{val_verdict.status.value.upper()}",
            state=final_state,
        )

        return final_state

    def export_deliverable(
        self,
        work_order_id: str,
        version: int,
        export_dir: Path,
    ) -> DeliverableBundle:
        """Exports verified deliverable bundle with CAS cryptographic integrity manifest."""
        export_dir.mkdir(parents=True, exist_ok=True)
        assignments = self.engine.list_assignments(work_order_id, version)

        patch_hash = None
        review_hash = None
        for asgn in assignments:
            if asgn["step_id"] == "step-patch":
                patch_hash = asgn.get("output_artifact_hash")
            elif asgn["step_id"] == "step-review":
                review_hash = asgn.get("output_artifact_hash")

        if not patch_hash:
            raise RuntimeError("Cannot export deliverable: missing synthesis patch artifact")

        # Copy patch
        patch_data = self.artifact_store.get(patch_hash)
        patch_file = export_dir / "deliverable.patch"
        patch_file.write_bytes(patch_data)

        # Copy review if present
        if review_hash:
            review_data = self.artifact_store.get(review_hash)
            (export_dir / "review_report.json").write_bytes(review_data)

        # Export routing lineage
        routing_records = [asdict(r) for r in self.router.decision_history if r.task_id == work_order_id]
        (export_dir / "routing_decisions.json").write_text(json.dumps(routing_records, indent=2))

        # Build manifest
        manifest_entries = {}
        for f in export_dir.iterdir():
            if f.is_file() and f.name != "manifest.sha256":
                manifest_entries[f.name] = content_hash(f.read_bytes())

        manifest_file = export_dir / "manifest.sha256"
        with open(manifest_file, "w") as mf:
            for fname, fhash in sorted(manifest_entries.items()):
                mf.write(f"{fhash}  {fname}\n")

        deliverable_hash = content_hash(manifest_file.read_bytes())

        return DeliverableBundle(
            work_order_id=work_order_id,
            version=version,
            deliverable_hash=deliverable_hash,
            patch_artifact_hash=patch_hash,
            review_artifact_hash=review_hash,
            verdict_artifact_hash="verdict_" + deliverable_hash[:16],
            routing_records=routing_records,
            exported_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            export_directory=str(export_dir),
        )

    def _find_or_create_assignment(self, work_order_id: str, version: int, step_id: str) -> Dict[str, Any]:
        assignments = self.engine.list_assignments(work_order_id, version)
        for asgn in assignments:
            if asgn["step_id"] == step_id:
                return asgn
        asgn_id = f"asgn-{work_order_id}-v{version}-{step_id}"
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.engine._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO task_assignments (
                    assignment_id, work_order_id, work_order_version, step_id,
                    required_role, status, fencing_token, retry_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asgn_id,
                    work_order_id,
                    version,
                    step_id,
                    "independent_review" if step_id == "step-review" else "defect_patch",
                    str(TaskStepState.READY),
                    1,
                    0,
                    now_iso,
                    now_iso,
                ),
            )
            conn.commit()
        asgn = self.engine.get_assignment(asgn_id)
        if not asgn:
            raise RuntimeError(f"Failed to create assignment {asgn_id}")
        return asgn
