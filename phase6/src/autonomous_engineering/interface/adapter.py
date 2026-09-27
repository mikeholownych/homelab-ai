"""Human Interface Adapter supporting detached sessions, revisions, and external artifact delivery."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.core.crypto import sha256_digest
from autonomous_engineering.core.types import (
    AmbiguityStatus,
    FailureClass,
    RevisionKind,
    WorkOrderState,
)
from autonomous_engineering.workflow.engine import WorkflowEngine, WorkflowEngineError
from autonomous_engineering.work_order.models import (
    AcceptanceCriterion,
    Ambiguity,
    WorkOrder,
)
from autonomous_engineering.work_order.versioning import WorkOrderRevisionManager


@dataclass(frozen=True)
class WorkOrderSubmissionReceipt:
    work_order_id: str
    version: int
    contract_hash: str
    submitted_at: str
    initial_state: str


@dataclass(frozen=True)
class WorkOrderStatusReport:
    work_order_id: str
    version: int
    state: WorkOrderState
    terminal_disposition: str | None
    fencing_token: int
    assignments: list[dict[str, Any]]
    audit_events: list[dict[str, Any]]


class HumanInterfaceAdapter:
    """Entry point for human direction, work order submission, revisions, and external artifact delivery.

    Invariants:
    - Session Independence: Once submitted, the work order executes to completion independently.
    - Post-Hoc Auditability: Full status, assignments, and audit trails are readable at any time.
    - Non-Authoritative Boundary: Interface cannot issue capability tokens or bypass independent validation.
    """

    def __init__(
        self,
        engine: WorkflowEngine,
        artifact_store: ArtifactStore,
    ) -> None:
        self.engine = engine
        self.artifact_store = artifact_store
        self._connected = True

    def submit_work_order(self, work_order: WorkOrder) -> WorkOrderSubmissionReceipt:
        """Submit a canonical work order to the durable engine."""
        self.engine.register_work_order(work_order)
        return WorkOrderSubmissionReceipt(
            work_order_id=work_order.work_order_id,
            version=work_order.version,
            contract_hash=work_order.contract_hash,
            submitted_at=work_order.created_at,
            initial_state=str(work_order.state.current_stage),
        )

    def disconnect(self) -> None:
        """Simulate interface session termination."""
        self._connected = False

    def reconnect(self) -> None:
        """Simulate interface re-attaching or polling from a new session."""
        self._connected = True

    def query_status(self, work_order_id: str, version: int) -> WorkOrderStatusReport | None:
        """Query durable status from SQLite store without requiring active session."""
        wo_record = self.engine.get_work_order(work_order_id, version)
        if not wo_record:
            return None

        assignments = self.engine.list_assignments(work_order_id, version)
        events = self.engine.list_audit_events(work_order_id, version)

        return WorkOrderStatusReport(
            work_order_id=work_order_id,
            version=version,
            state=WorkOrderState(wo_record["state"]),
            terminal_disposition=wo_record["terminal_disposition"],
            fencing_token=wo_record["fencing_token"],
            assignments=assignments,
            audit_events=events,
        )

    def inspect_work_order(self, work_order_id: str, version: int) -> dict[str, Any] | None:
        """Inspect the compiled work order, ambiguity state, and authorization bounds."""
        wo_record = self.engine.get_work_order(work_order_id, version)
        if not wo_record:
            return None

        wo_data = json.loads(wo_record["data_json"])
        ambiguities = wo_data.get("ambiguities", [])
        has_unresolved = any(a.get("status") == str(AmbiguityStatus.UNRESOLVED) for a in ambiguities)

        return {
            "work_order_id": work_order_id,
            "version": version,
            "contract_hash": wo_record["contract_hash"],
            "predecessor_hash": wo_record["predecessor_hash"],
            "state": wo_record["state"],
            "terminal_disposition": wo_record["terminal_disposition"],
            "fencing_token": wo_record["fencing_token"],
            "objective": wo_data.get("intent", {}).get("normalized_objective"),
            "repository": wo_data.get("intent", {}).get("target_repo"),
            "authorized_mutation_paths": wo_data.get("authorization", {}).get("authorized_mutation_paths"),
            "prohibited_operations": wo_data.get("authorization", {}).get("prohibited_operations"),
            "acceptance_criteria": wo_data.get("acceptance", {}).get("criteria"),
            "ambiguities": ambiguities,
            "requires_clarification": has_unresolved,
            "created_at": wo_record["created_at"],
            "updated_at": wo_record["updated_at"],
        }

    def clarify_ambiguity(
        self,
        work_order_id: str,
        version: int,
        ambiguity_id: str,
        resolution: str,
        author: str = "human_operator",
    ) -> WorkOrderSubmissionReceipt:
        """Submit an explicit human resolution for a registered ambiguity, creating a new revision."""
        wo_record = self.engine.get_work_order(work_order_id, version)
        if not wo_record:
            raise WorkflowEngineError(f"Work order {work_order_id} v{version} not found")

        wo_dict = json.loads(wo_record["data_json"])
        old_wo = WorkOrder.from_dict(wo_dict)

        updated_ambigs = []
        found = False
        for a in old_wo.ambiguities:
            if a.ambiguity_id == ambiguity_id:
                updated_ambigs.append(
                    Ambiguity(
                        ambiguity_id=a.ambiguity_id,
                        description=a.description,
                        status=AmbiguityStatus.HUMAN_RESOLVED,
                        resolution=resolution,
                    )
                )
                found = True
            else:
                updated_ambigs.append(a)

        if not found:
            raise WorkflowEngineError(f"Ambiguity {ambiguity_id} not found in work order")

        new_wo = WorkOrderRevisionManager.create_revision(
            current_wo=old_wo,
            change_reason=f"Resolved ambiguity {ambiguity_id}: {resolution}",
            author=author,
            revision_kind=RevisionKind.CLARIFICATION,
            updated_ambiguities=updated_ambigs,
        )

        self.engine.apply_revision(old_wo, new_wo, RevisionKind.CLARIFICATION)
        return WorkOrderSubmissionReceipt(
            work_order_id=new_wo.work_order_id,
            version=new_wo.version,
            contract_hash=new_wo.contract_hash,
            submitted_at=new_wo.created_at,
            initial_state=str(new_wo.state.current_stage),
        )

    def pause_work_order(self, work_order_id: str, version: int) -> None:
        """Pause execution through the control plane."""
        self.engine.pause_work_order(work_order_id, version)

    def resume_work_order(self, work_order_id: str, version: int) -> None:
        """Resume execution through the control plane."""
        self.engine.resume_work_order(work_order_id, version)

    def cancel_work_order(
        self,
        work_order_id: str,
        version: int,
        reason: str = "User requested cancellation",
    ) -> None:
        """Cancel execution and revoke active leases."""
        self.engine.cancel_work_order(work_order_id, version, reason)

    def revise_work_order(
        self,
        work_order_id: str,
        version: int,
        revision_kind: RevisionKind,
        change_reason: str,
        author: str = "human_operator",
        new_instruction_text: str | None = None,
        updated_paths: list[str] | None = None,
        updated_criteria: list[AcceptanceCriterion] | None = None,
    ) -> WorkOrderSubmissionReceipt:
        """Submit a bounded revision to an active work order."""
        wo_record = self.engine.get_work_order(work_order_id, version)
        if not wo_record:
            raise WorkflowEngineError(f"Work order {work_order_id} v{version} not found")

        wo_dict = json.loads(wo_record["data_json"])
        old_wo = WorkOrder.from_dict(wo_dict)

        new_wo = WorkOrderRevisionManager.create_revision(
            current_wo=old_wo,
            change_reason=change_reason,
            author=author,
            revision_kind=revision_kind,
            new_instruction_text=new_instruction_text,
            updated_paths=updated_paths,
            updated_criteria=updated_criteria,
        )

        self.engine.apply_revision(old_wo, new_wo, revision_kind)
        return WorkOrderSubmissionReceipt(
            work_order_id=new_wo.work_order_id,
            version=new_wo.version,
            contract_hash=new_wo.contract_hash,
            submitted_at=new_wo.created_at,
            initial_state=str(new_wo.state.current_stage),
        )

    def export_evidence_bundle(self, work_order_id: str, version: int) -> dict[str, Any]:
        """Compile a complete evidence bundle for external verification."""
        status = self.query_status(work_order_id, version)
        if not status:
            return {}

        artifacts = []
        for asgn in status.assignments:
            art_hash = asgn.get("output_artifact_hash")
            if art_hash:
                rec = self.artifact_store.get_record(art_hash)
                if rec:
                    artifacts.append(rec.to_dict())

        return {
            "work_order_id": work_order_id,
            "version": version,
            "state": str(status.state),
            "terminal_disposition": status.terminal_disposition,
            "assignments": status.assignments,
            "audit_trail": status.audit_events,
            "artifacts": artifacts,
        }

    def deliver_accepted_artifact(
        self,
        work_order_id: str,
        version: int,
        export_patch_path: Path | str | None = None,
    ) -> dict[str, Any]:
        """Deliver final accepted artifact with verification metadata and local application commands."""
        status = self.query_status(work_order_id, version)
        if not status:
            raise WorkflowEngineError(f"Work order {work_order_id} v{version} not found")

        if status.state != WorkOrderState.ACCEPTED:
            raise WorkflowEngineError(
                f"Work order {work_order_id} v{version} is in state {status.state}, not ACCEPTED"
            )

        wo_record = self.engine.get_work_order(work_order_id, version)
        wo_data = json.loads(wo_record["data_json"]) if wo_record else {}

        # 1. Locate candidate patch and validation verdict from assignments
        patch_hash = None
        validation_asgn = None
        review_asgn = None

        for asgn in status.assignments:
            role = asgn.get("required_role")
            if role in ("defect_patch", "implementation", "test_development", "refactoring", "bounded_repair"):
                # Take latest patch assignment
                if asgn.get("output_artifact_hash"):
                    patch_hash = asgn["output_artifact_hash"]
            elif role == "independent_review":
                review_asgn = asgn
            elif role == "independent_validation":
                validation_asgn = asgn

        if not patch_hash:
            raise WorkflowEngineError("No patch artifact associated with completed work order")

        # 2. CAS Integrity Check (Tamper Detection)
        try:
            patch_bytes = self.artifact_store.get(patch_hash)
        except Exception as exc:
            raise WorkflowEngineError(
                f"Cryptographic tamper detected: {exc}",
                FailureClass.ARTIFACT_TAMPERED,
            ) from exc

        patch_text = patch_bytes.decode("utf-8")

        # 3. Changed file inventory
        changed_files = []
        for line in patch_text.splitlines():
            if line.startswith("--- a/") or line.startswith("+++ b/"):
                filepath = line[6:].strip()
                if filepath and filepath not in changed_files:
                    changed_files.append(filepath)

        # 4. Extract validation metadata
        val_meta = {}
        if validation_asgn and validation_asgn.get("output_artifact_hash"):
            val_bytes = self.artifact_store.get(validation_asgn["output_artifact_hash"])
            if val_bytes:
                val_text = val_bytes.decode("utf-8")
                try:
                    val_meta = json.loads(val_text)
                except Exception:
                    val_meta = {
                        "status": "ACCEPTED" if status.state == WorkOrderState.ACCEPTED else "REJECTED",
                        "diagnostic_logs": val_text,
                    }

        # 5. Extract review summary
        rev_meta = {}
        if review_asgn and review_asgn.get("output_artifact_hash"):
            rev_bytes = self.artifact_store.get(review_asgn["output_artifact_hash"])
            if rev_bytes:
                rev_meta = json.loads(rev_bytes.decode("utf-8"))

        # 6. Optionally write patch file to disk
        patch_file_name = f"{work_order_id}_v{version}.patch"
        if export_patch_path:
            out_path = Path(export_patch_path)
            if out_path.is_dir():
                out_file = out_path / patch_file_name
            else:
                out_file = out_path
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text(patch_text, encoding="utf-8")
        else:
            patch_file_name = f"{work_order_id}.patch"

        return {
            "work_order_id": work_order_id,
            "version": version,
            "contract_hash": wo_record["contract_hash"] if wo_record else "",
            "terminal_disposition": status.terminal_disposition,
            "repository": wo_data.get("intent", {}).get("target_repo", {}),
            "deliverable": {
                "artifact_type": "PATCH",
                "artifact_hash": patch_hash,
                "changed_files": changed_files,
                "patch_content": patch_text,
            },
            "verification": {
                "status": val_meta.get("status", "ACCEPTED"),
                "validator_type": val_meta.get("validator_type", "pytest"),
                "test_target": val_meta.get("test_target", ""),
                "execution_duration_sec": val_meta.get("duration_seconds", 0.0),
                "exit_code": val_meta.get("exit_code", 0),
            },
            "review": {
                "reviewer_worker_id": rev_meta.get("reviewer_worker_id", "unknown"),
                "disposition": rev_meta.get("disposition", "RECOMMEND_ACCEPT"),
                "findings_count": len(rev_meta.get("findings", [])),
                "summary": rev_meta.get("summary", ""),
            },
            "supervisor_audit": {
                "events_count": len(status.audit_events),
                "fencing_token": status.fencing_token,
                "completed_at": status.audit_events[-1]["created_at"] if status.audit_events else "",
            },
            "local_inspection": {
                "check_command": f"git apply --check {patch_file_name}",
                "apply_command": f"git apply {patch_file_name}",
                "stat_command": f"git apply --stat {patch_file_name}",
            },
        }
