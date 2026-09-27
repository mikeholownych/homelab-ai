"""Hardened Real-Repository Pipeline with Failure Injection Hooks, Strict Scope Enforcement, and TOCTOU Protection."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, asdict, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Callable

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.authority.admission import AdmissionEvaluator
from autonomous_engineering.core.crypto import content_hash
from autonomous_engineering.core.types import (
    ArtifactType,
    TaskStepState,
    ValidationStatus,
    WorkOrderState,
)
from autonomous_engineering.review.models import (
    FindingSeverity,
    ReviewDisposition,
    ReviewFinding,
    ReviewReport,
)
from autonomous_engineering.investigation.repo_investigator import (
    RepositoryInvestigator,
    RepositoryInvestigationEvidence,
)
from autonomous_engineering.planning.models import ExecutionPlan, TaskStepDefinition
from autonomous_engineering.planning.planner import ExecutionPlanner
from autonomous_engineering.repair.controller import BoundedRepairController
from autonomous_engineering.router.evidence_router import (
    EvidenceBasedRouter,
    RoutingTopology,
)
from autonomous_engineering.validator.independent import (
    IndependentValidator,
    ValidationVerdict,
)
from autonomous_engineering.workflow.engine import WorkflowEngine, WorkflowEngineError
from autonomous_engineering.workflow.real_repo_pipeline import (
    RealRepoDeliverableBundle,
    RealRepoEngineeringPipeline,
)
from autonomous_engineering.work_order.models import WorkOrder

logger = logging.getLogger(__name__)


class LifecycleBoundary(str, Enum):
    PRE_ACQUISITION = "PRE_ACQUISITION"
    POST_LEASE = "POST_LEASE"
    DURING_INVESTIGATION = "DURING_INVESTIGATION"
    DURING_PLANNING = "DURING_PLANNING"
    DURING_IMPLEMENTATION = "DURING_IMPLEMENTATION"
    DURING_REVIEW = "DURING_REVIEW"
    DURING_REPAIR = "DURING_REPAIR"
    DURING_VALIDATION = "DURING_VALIDATION"
    DURING_SUPERVISOR_DISPOSITION = "DURING_SUPERVISOR_DISPOSITION"
    DURING_EXPORT = "DURING_EXPORT"
    POST_EXPORT_PRE_ACK = "POST_EXPORT_PRE_ACK"


class LifecycleInjectedCrashError(Exception):
    """Simulates a hard crash or process termination at an explicit lifecycle boundary."""


class ScopeViolationError(Exception):
    """Raised when a patch attempts to modify files outside authorized mutation paths."""


class TOCTOUMutationError(Exception):
    """Raised when repository state changes between validation and deliverable export."""


def extract_diff_target_paths(patch_text: str) -> Set[str]:
    """Parses unified diff text to extract all targeted file paths."""
    paths: Set[str] = set()
    for line in patch_text.splitlines():
        if line.startswith("+++ "):
            # Example: +++ b/orchestrator_gateway/server.py or +++ orchestrator_gateway/server.py
            target = line[4:].strip()
            if target.startswith("b/"):
                target = target[2:]
            if target != "/dev/null":
                paths.add(target.lstrip("/"))
        elif line.startswith("--- "):
            target = line[4:].strip()
            if target.startswith("a/"):
                target = target[2:]
            if target != "/dev/null":
                paths.add(target.lstrip("/"))
    return paths


def compute_directory_tree_hash(dir_path: Path) -> str:
    """Computes a deterministic hash of all files and content in a directory tree."""
    records = []
    if not dir_path.exists():
        return "non_existent"
    for root, _, files in sorted(os.walk(dir_path)):
        for f in sorted(files):
            if f.endswith(".pyc") or "__pycache__" in root:
                continue
            fp = Path(root) / f
            rel = fp.relative_to(dir_path).as_posix()
            try:
                chash = content_hash(fp.read_bytes())
                records.append(f"{rel}:{chash}")
            except Exception:
                pass
    return content_hash("\n".join(records))


class HardenedRealRepoPipeline(RealRepoEngineeringPipeline):
    """Enhanced real-repository pipeline with failure injection, strict hunk-level scope guard, and TOCTOU protection."""

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
        super().__init__(
            engine=engine,
            artifact_store=artifact_store,
            admission_evaluator=admission_evaluator,
            planner=planner,
            router=router,
            validator=validator,
            repair_controller=repair_ctrl if 'repair_ctrl' in locals() else repair_controller,
            workers=workers,
            target_repo_dir=target_repo_dir,
        )
        self.crash_hooks: Dict[LifecycleBoundary, Callable[[str, int], None]] = {}
        self.validation_repo_snapshots: Dict[str, str] = {}  # work_order_id -> repo_hash

    def register_crash_hook(
        self, boundary: LifecycleBoundary, hook: Callable[[str, int], None]
    ) -> None:
        self.crash_hooks[boundary] = hook

    def clear_crash_hooks(self) -> None:
        self.crash_hooks.clear()

    def _trigger_hook(self, boundary: LifecycleBoundary, work_order_id: str, version: int) -> None:
        if boundary in self.crash_hooks:
            hook = self.crash_hooks[boundary]
            hook(work_order_id, version)

    def validate_patch_scope(self, patch_text: str, authorized_paths: tuple[Path | str, ...]) -> None:
        """Enforces point-of-use scope validation on all hunk paths."""
        mutated_paths = extract_diff_target_paths(patch_text)
        auth_set = {str(p).lstrip("/") for p in authorized_paths}
        unauthorized = mutated_paths - auth_set
        if unauthorized:
            raise ScopeViolationError(
                f"Patch contains unauthorized mutations to: {sorted(unauthorized)}. Authorized paths: {sorted(auth_set)}"
            )

    def execute_lifecycle(
        self,
        work_order_id: str,
        version: int = 1,
        force_topology: RoutingTopology = RoutingTopology.HETEROGENEOUS,
    ) -> WorkOrderState:
        # 1. Pre-acquisition hook
        self._trigger_hook(LifecycleBoundary.PRE_ACQUISITION, work_order_id, version)

        wo_record = self.engine.get_work_order(work_order_id, version)
        if not wo_record:
            raise WorkflowEngineError(f"Work order {work_order_id} v{version} not found in engine")

        if wo_record["state"] == str(WorkOrderState.CANCELLED):
            return WorkOrderState.CANCELLED

        raw_json = wo_record["data_json"]
        wo_dict = json.loads(raw_json) if isinstance(raw_json, str) and raw_json.startswith("{") else eval(raw_json)
        wo = WorkOrder.from_dict(wo_dict)

        # Acquire initial task step lease
        asgn_patch = self._find_or_create_assignment(work_order_id, version, "step-patch")
        patch_asgn_id = asgn_patch["assignment_id"]
        author_route = self.router.route_assignment(
            assignment_id=patch_asgn_id,
            task_id=work_order_id,
            task_class="defect_repair",
            required_role="author",
            force_topology=force_topology,
        )
        author_worker = self.workers.get(author_route.selected_candidate_id) or self.workers.get("worker-b65-0")
        patch_token = self.engine.acquire_lease(patch_asgn_id, getattr(author_worker, "worker_id", "worker-author"))

        # 2. Post-lease hook
        self._trigger_hook(LifecycleBoundary.POST_LEASE, work_order_id, version)

        # 3. Investigation
        self._trigger_hook(LifecycleBoundary.DURING_INVESTIGATION, work_order_id, version)
        inv_paths = [str(p) for p in wo.authorization.authorized_mutation_paths]
        target_repo_id = getattr(wo.intent, "target_repo", None).repository_id if getattr(wo, "intent", None) and getattr(wo.intent, "target_repo", None) else wo.contract.repository_id
        test_targets = [c.test_target for c in wo.acceptance.criteria] if getattr(wo, "acceptance", None) else None
        investigation_evidence = self.investigator.investigate_paths(
            repository_id=target_repo_id,
            target_paths=inv_paths,
            test_paths=test_targets,
        )
        inv_rec = self.artifact_store.put(
            content=json.dumps(asdict(investigation_evidence)).encode("utf-8"),
            artifact_type=ArtifactType.LOG,
            work_order_id=work_order_id,
            work_order_version=version,
            step_id="step-investigate",
            producing_worker_id="system-investigator",
            producing_profile_hash="hash-investigator",
            capability_token_id=f"token-{patch_asgn_id}",
        )

        # 4. Planning
        self._trigger_hook(LifecycleBoundary.DURING_PLANNING, work_order_id, version)
        plan = self.planner.create_plan(wo)
        self.engine.initialize_plan(plan)

        # 5. Implementation
        self._trigger_hook(LifecycleBoundary.DURING_IMPLEMENTATION, work_order_id, version)
        raw_instruction = getattr(wo, "source_instruction", None).raw_text if getattr(wo, "source_instruction", None) else wo.contract.instruction_payload.get("raw_text", "")
        author_patch_text = author_worker.execute(
            task_id=work_order_id,
            step_id="step-patch",
            instruction=raw_instruction,
            context={"investigation": asdict(investigation_evidence)},
        )

        # Point-of-use scope validation
        try:
            self.validate_patch_scope(author_patch_text, wo.authorization.authorized_mutation_paths)
        except ScopeViolationError as sve:
            logger.error(f"Scope violation in work order {work_order_id}: {sve}")
            self.engine.set_terminal_disposition(
                work_order_id=work_order_id,
                version=version,
                disposition="REJECTED_SCOPE_VIOLATION",
                state=WorkOrderState.REJECTED,
            )
            return WorkOrderState.REJECTED

        patch_rec = self.artifact_store.put(
            content=author_patch_text.encode("utf-8"),
            artifact_type=ArtifactType.PATCH,
            work_order_id=work_order_id,
            work_order_version=version,
            step_id="step-patch",
            producing_worker_id=getattr(author_worker, "worker_id", "worker-author"),
            producing_profile_hash=getattr(author_worker, "profile_hash", "hash-author"),
            capability_token_id=f"token-{patch_asgn_id}",
            parent_artifact_hashes=(inv_rec.artifact_hash,),
        )
        self.engine.complete_assignment(patch_asgn_id, patch_token, patch_rec.artifact_hash)

        current_patch_rec = patch_rec

        # 6. Review
        if force_topology != RoutingTopology.SINGLE_WORKER:
            self._trigger_hook(LifecycleBoundary.DURING_REVIEW, work_order_id, version)
            rev_asgn = self._find_or_create_assignment(work_order_id, version, "step-review")
            rev_asgn_id = rev_asgn["assignment_id"]
            rev_route = self.router.route_assignment(
                assignment_id=rev_asgn_id,
                task_id=work_order_id,
                task_class="defect_repair",
                required_role="reviewer",
                force_topology=force_topology,
            )
            reviewer_worker = self.workers.get(rev_route.selected_candidate_id) or self.workers.get("worker-phi4") or author_worker
            rev_token = self.engine.acquire_lease(rev_asgn_id, getattr(reviewer_worker, "worker_id", "worker-reviewer"))

            review_raw = reviewer_worker.execute(
                task_id=work_order_id,
                step_id="step-review",
                instruction="Review patch against acceptance criteria and mutation boundaries",
                context={"patch": author_patch_text, "allowed_paths": [str(p) for p in wo.authorization.authorized_mutation_paths]},
            )

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

            # 7. Bounded Repair
            if report.disposition == ReviewDisposition.RECOMMEND_REVISE:
                self._trigger_hook(LifecycleBoundary.DURING_REPAIR, work_order_id, version)
                rep_asgn = self._find_or_create_assignment(work_order_id, version, "step-repair")
                rep_asgn_id = rep_asgn["assignment_id"]
                rep_token = self.engine.acquire_lease(rep_asgn_id, getattr(author_worker, "worker_id", "worker-repairer"))

                repaired_patch_text = author_worker.execute(
                    task_id=work_order_id,
                    step_id="step-repair",
                    instruction=f"Repair patch based on review findings: {report.summary}",
                    context={"original_patch": author_patch_text, "findings": [asdict(f) for f in findings]},
                )

                self.validate_patch_scope(repaired_patch_text, wo.authorization.authorized_mutation_paths)

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

        # 8. Independent Sandboxed Validation
        self._trigger_hook(LifecycleBoundary.DURING_VALIDATION, work_order_id, version)
        # Snapshot repository baseline state for TOCTOU verification
        pre_val_repo_hash = compute_directory_tree_hash(self.target_repo_dir)
        self.validation_repo_snapshots[work_order_id] = pre_val_repo_hash

        val_verdict = self.validator.validate(
            artifact=current_patch_rec,
            criteria=wo.acceptance.criteria,
            baseline_repo_dir=self.target_repo_dir,
        )

        # 9. Supervisor Authoritative Disposition
        self._trigger_hook(LifecycleBoundary.DURING_SUPERVISOR_DISPOSITION, work_order_id, version)
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
        """Exports deliverable bundle with TOCTOU repository state verification."""
        # 10. During Export hook
        self._trigger_hook(LifecycleBoundary.DURING_EXPORT, work_order_id, version)

        # TOCTOU Verification: Ensure target repository has not mutated since validation
        expected_repo_hash = self.validation_repo_snapshots.get(work_order_id)
        if expected_repo_hash:
            current_repo_hash = compute_directory_tree_hash(self.target_repo_dir)
            if current_repo_hash != expected_repo_hash:
                raise TOCTOUMutationError(
                    f"Target repository was mutated after validation! Expected hash {expected_repo_hash[:16]}, observed {current_repo_hash[:16]}. Deliverable export aborted."
                )

        bundle = super().export_deliverable(work_order_id, version, export_dir)

        # 11. Post-Export Pre-ACK hook
        self._trigger_hook(LifecycleBoundary.POST_EXPORT_PRE_ACK, work_order_id, version)

        return bundle
