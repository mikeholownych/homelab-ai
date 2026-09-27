"""Persistent Human-Facing Command-Line Interface (CLI) for Autonomous Engineering System."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Sequence

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.core.types import RevisionKind, WorkOrderState
from autonomous_engineering.interface.adapter import HumanInterfaceAdapter
from autonomous_engineering.work_order.compiler import WorkOrderCompiler
from autonomous_engineering.work_order.models import AcceptanceCriterion
from autonomous_engineering.workflow.engine import WorkflowEngine, WorkflowEngineError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aes-cli",
        description="Autonomous Engineering System Human Interface CLI",
    )
    parser.add_argument(
        "--db",
        default="./orchestrator.sqlite",
        help="Path to durable SQLite database (default: ./orchestrator.sqlite)",
    )
    parser.add_argument(
        "--artifacts",
        default="./artifacts",
        help="Path to content-addressed artifact store (default: ./artifacts)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. submit
    p_submit = subparsers.add_parser("submit", help="Submit a new canonical engineering work order")
    p_submit.add_argument("--prompt", required=True, help="Human instruction text / engineering intent")
    p_submit.add_argument("--repo", required=True, help="Repository path or identifier")
    p_submit.add_argument("--commit", default="HEAD", help="Baseline commit hash")
    p_submit.add_argument("--scope", nargs="+", required=True, help="Authorized file mutation paths")
    p_submit.add_argument("--test", nargs="+", required=True, help="Acceptance test targets (e.g. tests/test_foo.py)")
    p_submit.add_argument("--channel", default="cli", help="Source channel")
    p_submit.add_argument("--max-retries", type=int, default=2, help="Maximum validation retry count")

    # 2. inspect
    p_inspect = subparsers.add_parser("inspect", help="Inspect a compiled work order and material ambiguities")
    p_inspect.add_argument("work_order_id", help="Work order ID")
    p_inspect.add_argument("--version", type=int, default=1, help="Work order version")

    # 3. clarify
    p_clarify = subparsers.add_parser("clarify", help="Submit explicit human clarification for an ambiguity")
    p_clarify.add_argument("work_order_id", help="Work order ID")
    p_clarify.add_argument("--ambiguity-id", required=True, help="Ambiguity ID to resolve")
    p_clarify.add_argument("--decision", required=True, help="Resolution decision")
    p_clarify.add_argument("--version", type=int, default=1, help="Current work order version")

    # 4. status
    p_status = subparsers.add_parser("status", help="Query authoritative execution state and assignments")
    p_status.add_argument("work_order_id", help="Work order ID")
    p_status.add_argument("--version", type=int, default=1, help="Work order version")
    p_status.add_argument("--json", action="store_true", help="Output raw JSON")

    # 5. pause
    p_pause = subparsers.add_parser("pause", help="Pause an active work order")
    p_pause.add_argument("work_order_id", help="Work order ID")
    p_pause.add_argument("--version", type=int, default=1, help="Work order version")

    # 6. resume
    p_resume = subparsers.add_parser("resume", help="Resume a paused work order")
    p_resume.add_argument("work_order_id", help="Work order ID")
    p_resume.add_argument("--version", type=int, default=1, help="Work order version")

    # 7. cancel
    p_cancel = subparsers.add_parser("cancel", help="Cancel a work order and revoke active leases")
    p_cancel.add_argument("work_order_id", help="Work order ID")
    p_cancel.add_argument("--version", type=int, default=1, help="Work order version")
    p_cancel.add_argument("--reason", default="User requested cancellation", help="Cancellation reason")

    # 8. revise
    p_revise = subparsers.add_parser("revise", help="Submit a bounded revision to an existing work order")
    p_revise.add_argument("work_order_id", help="Work order ID")
    p_revise.add_argument("--version", type=int, default=1, help="Current work order version")
    p_revise.add_argument(
        "--kind",
        choices=["CLARIFICATION", "SCOPE_EXPANSION", "SCOPE_RESTRICTION", "CRITERIA_MUTATION", "CANCELLATION"],
        required=True,
        help="Revision classification kind",
    )
    p_revise.add_argument("--reason", required=True, help="Rationale for revision")
    p_revise.add_argument("--prompt", help="Revised instruction text")
    p_revise.add_argument("--scope", nargs="+", help="Revised authorized mutation paths")
    p_revise.add_argument("--test", nargs="+", help="Revised test targets")

    # 9. deliver
    p_deliver = subparsers.add_parser("deliver", help="Retrieve final accepted deliverables and application guide")
    p_deliver.add_argument("work_order_id", help="Work order ID")
    p_deliver.add_argument("--version", type=int, default=1, help="Work order version")
    p_deliver.add_argument("--export-dir", help="Directory to export deliverable patch file")

    # 10. export
    p_export = subparsers.add_parser("export", help="Export full tamper-evident audit evidence bundle")
    p_export.add_argument("work_order_id", help="Work order ID")
    p_export.add_argument("--version", type=int, default=1, help="Work order version")

    return parser


def run_cli(args: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parsed = parser.parse_args(args)

    engine = WorkflowEngine(parsed.db)
    store = ArtifactStore(parsed.artifacts)
    adapter = HumanInterfaceAdapter(engine, store)

    try:
        if parsed.command == "submit":
            criteria = [
                AcceptanceCriterion(
                    criterion_id=f"crit-{idx+1}",
                    description=f"Validate target {t}",
                    validator_type="pytest",
                    test_target=t,
                )
                for idx, t in enumerate(parsed.test)
            ]
            compiler = WorkOrderCompiler()
            wo = compiler.compile(
                raw_text=parsed.prompt,
                source_channel=parsed.channel,
                source_reference=f"cli-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
                repository_id=parsed.repo,
                baseline_commit=parsed.commit,
                proposed_mutation_paths=parsed.scope,
                acceptance_criteria=criteria,
                max_retries=parsed.max_retries,
            )
            receipt = adapter.submit_work_order(wo)
            print(f"[+] Work Order Submitted: {receipt.work_order_id} v{receipt.version}")
            print(f"    Contract Hash: {receipt.contract_hash}")
            print(f"    Initial State: {receipt.initial_state}")
            return 0

        elif parsed.command == "inspect":
            data = adapter.inspect_work_order(parsed.work_order_id, parsed.version)
            if not data:
                print(f"[!] Work order {parsed.work_order_id} v{parsed.version} not found", file=sys.stderr)
                return 1
            print(json.dumps(data, indent=2))
            return 0

        elif parsed.command == "clarify":
            receipt = adapter.clarify_ambiguity(
                work_order_id=parsed.work_order_id,
                version=parsed.version,
                ambiguity_id=parsed.ambiguity_id,
                resolution=parsed.decision,
            )
            print(f"[+] Clarification Recorded: {receipt.work_order_id} v{receipt.version}")
            print(f"    Contract Hash: {receipt.contract_hash}")
            return 0

        elif parsed.command == "status":
            report = adapter.query_status(parsed.work_order_id, parsed.version)
            if not report:
                print(f"[!] Work order {parsed.work_order_id} v{parsed.version} not found", file=sys.stderr)
                return 1
            if parsed.json:
                print(
                    json.dumps(
                        {
                            "work_order_id": report.work_order_id,
                            "version": report.version,
                            "state": str(report.state),
                            "terminal_disposition": report.terminal_disposition,
                            "fencing_token": report.fencing_token,
                            "assignments_count": len(report.assignments),
                            "audit_events_count": len(report.audit_events),
                        },
                        indent=2,
                    )
                )
            else:
                print(f"Work Order: {report.work_order_id} v{report.version}")
                print(f"State:      {report.state}")
                print(f"Terminal:   {report.terminal_disposition}")
                print(f"Fencing:    {report.fencing_token}")
                print("\nAssignments:")
                for asgn in report.assignments:
                    print(
                        f"  - [{asgn['step_id']}] {asgn['required_role']:<20} "
                        f"Status: {asgn['status']:<10} Worker: {asgn.get('lease_worker') or 'none':<14} "
                        f"Fence: {asgn['fencing_token']}"
                    )
            return 0

        elif parsed.command == "pause":
            adapter.pause_work_order(parsed.work_order_id, parsed.version)
            print(f"[+] Work Order {parsed.work_order_id} v{parsed.version} PAUSED")
            return 0

        elif parsed.command == "resume":
            adapter.resume_work_order(parsed.work_order_id, parsed.version)
            print(f"[+] Work Order {parsed.work_order_id} v{parsed.version} RESUMED")
            return 0

        elif parsed.command == "cancel":
            adapter.cancel_work_order(parsed.work_order_id, parsed.version, parsed.reason)
            print(f"[+] Work Order {parsed.work_order_id} v{parsed.version} CANCELLED")
            return 0

        elif parsed.command == "revise":
            rev_kind = RevisionKind(parsed.kind)
            criteria = None
            if parsed.test:
                criteria = [
                    AcceptanceCriterion(
                        criterion_id=f"crit-rev-{idx+1}",
                        description=f"Validate target {t}",
                        validator_type="pytest",
                        test_target=t,
                    )
                    for idx, t in enumerate(parsed.test)
                ]
            receipt = adapter.revise_work_order(
                work_order_id=parsed.work_order_id,
                version=parsed.version,
                revision_kind=rev_kind,
                change_reason=parsed.reason,
                new_instruction_text=parsed.prompt,
                updated_paths=parsed.scope,
                updated_criteria=criteria,
            )
            print(f"[+] Work Order Revised: {receipt.work_order_id} v{receipt.version} ([{rev_kind}])")
            print(f"    New Contract Hash: {receipt.contract_hash}")
            return 0

        elif parsed.command == "deliver":
            bundle = adapter.deliver_accepted_artifact(
                work_order_id=parsed.work_order_id,
                version=parsed.version,
                export_patch_path=parsed.export_dir,
            )
            print(f"[+] Accepted Deliverable Ready for {parsed.work_order_id} v{parsed.version}")
            print(f"    Terminal Disposition: {bundle['terminal_disposition']}")
            print(f"    Patch Hash:           {bundle['deliverable']['artifact_hash']}")
            print(f"    Changed Files:        {bundle['deliverable']['changed_files']}")
            print(f"\nLocal Inspection & Application Guide:")
            print(f"    Check:  {bundle['local_inspection']['check_command']}")
            print(f"    Apply:  {bundle['local_inspection']['apply_command']}")
            print(f"    Stat:   {bundle['local_inspection']['stat_command']}")
            return 0

        elif parsed.command == "export":
            bundle = adapter.export_evidence_bundle(parsed.work_order_id, parsed.version)
            print(json.dumps(bundle, indent=2))
            return 0

        else:
            print(f"[!] Unknown command: {parsed.command}", file=sys.stderr)
            return 1

    except WorkflowEngineError as e:
        print(f"[!] Engine Error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"[!] Error: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(run_cli())
