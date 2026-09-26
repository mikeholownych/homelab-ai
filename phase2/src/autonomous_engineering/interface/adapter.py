"""Human Interface Adapter supporting detached sessions and asynchronous status retrieval."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.core.types import WorkOrderState
from autonomous_engineering.workflow.engine import WorkflowEngine
from autonomous_engineering.work_order.models import WorkOrder


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
    """Entry point for human direction, work order submission, and detached status queries.

    Invariants:
    - Session Independence: Once submitted, the work order executes to completion independently.
    - Post-Hoc Auditability: Full status, assignments, and audit trails are readable at any time.
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
