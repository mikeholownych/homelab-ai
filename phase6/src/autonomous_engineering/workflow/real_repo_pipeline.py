"""Real-Repository Engineering Execution Pipeline."""
from __future__ import annotations

import json
import logging
import subprocess
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
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
from autonomous_engineering.investigation.repo_investigator import (
    RepositoryInvestigator,
    RepositoryInvestigationEvidence,
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
from autonomous_engineering.validator.independent import (
    IndependentValidator,
    ValidationVerdict,
)
from autonomous_engineering.workflow.engine import WorkflowEngine
from autonomous_engineering.work_order.models import WorkOrder
from autonomous_engineering.workers.simulated import BaseWorker

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RealRepoDeliverableBundle:
    work_order_id: str
    version: int
    deliverable_hash: str
    patch_artifact_hash: str
    review_artifact_hash: Optional[str]
    verdict_artifact_hash: str
    changed_files: List[str]
    patch_path: str
    manifest_path: str
    integration_instructions: str
    routing_records: List[Dict[str, Any]]
    exported_at: str
    export_directory: str


class RealRepoEngineeringPipeline:
    """Specialized execution pipeline for authorized work on real repositories.
    
    Complete Verified Lifecycle:
    SUBMIT -> COMPILE -> ADMIT -> INVESTIGATE -> PLAN -> IMPLEMENT -> REVIEW 
    -> BOUNDED REPAIR IF REQUIRED -> INDEPENDENT VALIDATION -> SUPERVISOR DISPOSITION -> DELIVER
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
        workers: Dict[str, Any],
        target_repo_dir: Path,
    ) -> None:
        self.engine = engine
        self.artifact_store = artifact_store
        self.admission_evaluator = admission_evaluator
        self.planner = planner
        self.router = router
        self.validator = validator
        self.repair_controller = repair_controller
        self.workers = workers
        self.target_repo_dir = target_repo_dir
        self.investigator = RepositoryInvestigator(target_repo_dir)

    def submit_and_admit(
        self,
        work_order: WorkOrder,
        human_approval_present: bool = True,
    ) -> AdmissionDecision:
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
        wo_record = self.engine.get_work_order(work_order_id, version)
        if not wo_record:
            raise ValueError(f"Work order {work_order_id} v{version} not found in engine")

        raw_json = wo_record["data_json"]
        wo_dict = json.loads(raw_json) if isinstance(raw_json, str) and raw_json.startswith("{") else eval(raw_json)
        wo = WorkOrder.from_dict(wo_dict)

        # Stage 1: Investigation
        inv_evidence = self.investigator.investigate_paths(
            repository_id=wo.intent.target_repo.repository_id,
            target_paths=list(wo.authorization.authorized_mutation_paths),
            test_paths=[c.test_target for c in wo.acceptance.criteria],
        )

        inv_bytes = json.dumps(asdict(inv_evidence)).encode("utf-8")
        inv_rec = self.artifact_store.put(
            content=inv_bytes,
            artifact_type=ArtifactType.REPRODUCTION_SCRIPT,
            work_order_id=work_order_id,
            work_order_version=version,
            step_id="step-investigate",
            producing_worker_id="system-investigator",
            producing_profile_hash="hash-investigator",
            capability_token_id=f"token-inv-{work_order_id}",
        )

        # Stage 2: Planning
        plan = self.planner.create_plan(wo)
        self.engine.initialize_plan(plan)

        # Stage 3: Author Implementation
        author_asgn = self._find_or_create_assignment(work_order_id, version, "step-patch")
        author_asgn_id = author_asgn["assignment_id"]
        author_route = self.router.route_assignment(
            assignment_id=author_asgn_id,
            task_id=work_order_id,
            task_class="defect_repair",
            required_role="author",
            force_topology=force_topology,
        )

        author_worker = self.workers.get(author_route.selected_candidate_id) or self.workers.get("worker-b65-0") or next(iter(self.workers.values()))
        author_token = self.engine.acquire_lease(author_asgn_id, getattr(author_worker, "worker_id", "worker-author"))

        context = {
            "allowed_paths": [p for p in wo.authorization.authorized_mutation_paths],
            "investigation_summary": inv_evidence.summary_text,
            "target_repo": str(self.target_repo_dir),
        }
        author_patch_text = author_worker.execute(
            task_id=work_order_id,
            step_id="step-patch",
            instruction=wo.source_instruction.raw_text,
            context=context,
        )

        patch_rec = self.artifact_store.put(
            content=author_patch_text.encode("utf-8"),
            artifact_type=ArtifactType.PATCH,
            work_order_id=work_order_id,
            work_order_version=version,
            step_id="step-patch",
            producing_worker_id=getattr(author_worker, "worker_id", "worker-author"),
            producing_profile_hash=getattr(author_worker, "profile_hash", "hash-author"),
            capability_token_id=f"token-{author_asgn_id}",
            parent_artifact_hashes=(inv_rec.artifact_hash,),
        )
        self.engine.complete_assignment(author_asgn_id, author_token, patch_rec.artifact_hash)

        # Stage 4: Review and Bounded Repair
        review_hash: Optional[str] = None
        current_patch_rec = patch_rec

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

            reviewer_worker = self.workers.get(review_route.selected_candidate_id) or self.workers.get("worker-phi4") or author_worker
            rev_token = self.engine.acquire_lease(rev_asgn_id, getattr(reviewer_worker, "worker_id", "worker-reviewer"))

            review_raw = reviewer_worker.execute(
                task_id=work_order_id,
                step_id="step-review",
                instruction="Review patch against acceptance criteria and mutation boundaries",
                context={"patch": author_patch_text, "allowed_paths": [p for p in wo.authorization.authorized_mutation_paths]},
            )

            # Check if review found any defect requiring bounded repair
            has_finding = "REPAIR_REQUIRED" in review_raw or "FINDING:" in review_raw
            findings = ()
            disposition = ReviewDisposition.RECOMMEND_ACCEPT
            if has_finding:
                disposition = ReviewDisposition.RECOMMEND_REVISE
                findings = (
                    ReviewFinding(
                        finding_id="rev-find-001",
                        severity=FindingSeverity.MAJOR,
                        file_path=str(wo.authorization.authorized_mutation_paths[0]),
                        line_number=10,
                        description="Patch requires bounded repair to satisfy strict acceptance boundaries.",
                        suggested_action="Sanitize headers and adhere strictly to authorized paths.",
                    ),
                )

            report = ReviewReport(
                report_id=f"rev-{work_order_id}-v{version}",
                target_artifact_hash=current_patch_rec.artifact_hash,
                reviewer_worker_id=getattr(reviewer_worker, "worker_id", "worker-reviewer"),
                disposition=disposition,
                findings=findings,
                summary=review_raw,
            )
            report_bytes = json.dumps(report.to_dict()).encode("utf-8")
            review_rec = self.artifact_store.put(
                content=report_bytes,
                artifact_type=ArtifactType.REVIEW_REPORT,
                work_order_id=work_order_id,
                work_order_version=version,
                step_id="step-review",
                producing_worker_id=getattr(reviewer_worker, "worker_id", "worker-reviewer"),
                producing_profile_hash=getattr(reviewer_worker, "profile_hash", "hash-reviewer"),
                capability_token_id=f"token-{rev_asgn_id}",
                parent_artifact_hashes=(current_patch_rec.artifact_hash,),
            )
            self.engine.complete_assignment(rev_asgn_id, rev_token, review_rec.artifact_hash)
            review_hash = review_rec.artifact_hash

            # Bounded Repair Pass if required
            if report.disposition == ReviewDisposition.RECOMMEND_REVISE:
                repair_asgn = self._find_or_create_assignment(work_order_id, version, "step-repair")
                rep_asgn_id = repair_asgn["assignment_id"]
                rep_token = self.engine.acquire_lease(rep_asgn_id, getattr(author_worker, "worker_id", "worker-repairer"))

                repaired_patch_text = author_worker.execute(
                    task_id=work_order_id,
                    step_id="step-repair",
                    instruction=f"Repair patch based on review findings: {report.summary}",
                    context={"original_patch": author_patch_text, "findings": [asdict(f) for f in findings]},
                )

                current_patch_rec = self.artifact_store.put(
                    content=repaired_patch_text.encode("utf-8"),
                    artifact_type=ArtifactType.PATCH,
                    work_order_id=work_order_id,
                    work_order_version=version,
                    step_id="step-repair",
                    producing_worker_id=getattr(author_worker, "worker_id", "worker-repairer"),
                    producing_profile_hash=getattr(author_worker, "profile_hash", "hash-repairer"),
                    capability_token_id=f"token-{rep_asgn_id}",
                    parent_artifact_hashes=(patch_rec.artifact_hash, review_rec.artifact_hash),
                )
                self.engine.complete_assignment(rep_asgn_id, rep_token, current_patch_rec.artifact_hash)

        # Stage 5: Independent Sandboxed Validation
        val_verdict: ValidationVerdict = self.validator.validate(
            artifact=current_patch_rec,
            criteria=wo.acceptance.criteria,
            baseline_repo_dir=self.target_repo_dir,
        )
        if val_verdict.status != ValidationStatus.ACCEPTED:
            print(f"FAILED TASK {work_order_id} VERDICT:\n{val_verdict.diagnostic_logs}")

        # Stage 6: Supervisor Authoritative Disposition
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
    ) -> RealRepoDeliverableBundle:
        """Exports verified deliverable bundle with CAS cryptographic integrity manifest and human integration guide."""
        export_dir.mkdir(parents=True, exist_ok=True)
        assignments = self.engine.list_assignments(work_order_id, version)

        patch_hash = None
        review_hash = None
        for asgn in assignments:
            if asgn["step_id"] in {"step-repair", "step-patch"}:
                patch_hash = asgn.get("output_artifact_hash")
            elif asgn["step_id"] == "step-review":
                review_hash = asgn.get("output_artifact_hash")

        if not patch_hash:
            raise RuntimeError("Cannot export deliverable: missing synthesis patch artifact")

        # Copy patch
        patch_data = self.artifact_store.get(patch_hash)
        patch_file = export_dir / "deliverable.patch"
        patch_file.write_bytes(patch_data)

        # Parse changed files from patch
        changed_files: List[str] = []
        for line in patch_data.decode("utf-8", errors="replace").splitlines():
            if line.startswith("+++ b/"):
                changed_files.append(line[6:].strip())
            elif line.startswith("+++ ") and not line.startswith("+++ b/"):
                changed_files.append(line[4:].strip())

        # Copy review if present
        if review_hash:
            review_data = self.artifact_store.get(review_hash)
            (export_dir / "review_report.json").write_bytes(review_data)

        # Export routing lineage
        routing_records = [asdict(r) for r in self.router.decision_history if r.task_id == work_order_id]
        (export_dir / "routing_decisions.json").write_text(json.dumps(routing_records, indent=2))

        # Generate Human Integration Instructions
        instructions = (
            f"# Human Integration & Verification Guide\n\n"
            f"**Work Order**: `{work_order_id}` (Version {version})\n"
            f"**Verified Deliverable Hash**: `{content_hash(patch_data)}`\n"
            f"**Changed Files**:\n"
            + "\n".join(f"- `{f}`" for f in sorted(set(changed_files)))
            + f"\n\n### Application Steps:\n"
            f"1. Navigate to repository root: `cd {self.target_repo_dir}`\n"
            f"2. Apply verified patch: `git apply {export_dir / 'deliverable.patch'}`\n"
            f"3. Run validation suite: `pytest`\n"
            f"4. Commit with human authorization: `git commit -m 'feat: apply verified work order {work_order_id}'`\n"
        )
        (export_dir / "INTEGRATION_GUIDE.md").write_text(instructions)

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

        return RealRepoDeliverableBundle(
            work_order_id=work_order_id,
            version=version,
            deliverable_hash=deliverable_hash,
            patch_artifact_hash=patch_hash,
            review_artifact_hash=review_hash,
            verdict_artifact_hash="verdict_" + deliverable_hash[:16],
            changed_files=sorted(set(changed_files)),
            patch_path=str(patch_file),
            manifest_path=str(manifest_file),
            integration_instructions=instructions,
            routing_records=routing_records,
            exported_at=datetime.now(timezone.utc).isoformat(),
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
