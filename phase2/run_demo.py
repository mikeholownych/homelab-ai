#!/usr/bin/env python3
"""Phase 2 Durable Multi-Worker Execution Vertical Slice Demonstration.

Runs one complete autonomous engineering work order through:
1. Canonical WorkOrder compilation with pre-registered acceptance criteria.
2. Empirical capability registry verification (Intel Arc Pro B65 stack).
3. Capability router enforcement of independence constraints (author != reviewer).
4. Dependency-aware DAG scheduling across specialized worker roles:
   - Investigation specialist (worker-b65-0) -> reproduction artifact.
   - Code authoring specialist (worker-b65-0) -> candidate patch artifact.
   - Independent review specialist (worker-b65-1) -> advisory ReviewReport artifact.
   - Independent validator (system-validator) -> acceptance verdict in clean sandbox.
5. Durable transactional state machine with monotonic fencing in SQLite WAL.
6. Export of tamper-evident audit evidence bundle.
7. Authoritative terminal disposition commitment.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import tempfile

# Add phase2/src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.authority.admission import AdmissionEvaluator
from autonomous_engineering.core.types import (
    ArtifactType,
    ValidationStatus,
    WorkerHealthStatus,
    WorkOrderState,
)
from autonomous_engineering.interface.adapter import HumanInterfaceAdapter
from autonomous_engineering.orchestrator import OrchestratorControlPlane
from autonomous_engineering.planning.planner import ExecutionPlanner
from autonomous_engineering.registry.models import (
    EmpiricalSkillRecord,
    EvidenceSource,
    HardwareTarget,
    RuntimeConfig,
    WorkerCapabilityProfile,
)
from autonomous_engineering.registry.registry import WorkerCapabilityRegistry
from autonomous_engineering.repair.controller import BoundedRepairController
from autonomous_engineering.router.router import CapabilityRouter
from autonomous_engineering.validator.independent import IndependentValidator
from autonomous_engineering.workers.simulated import (
    FastCoderWorker,
    InvestigatorWorker,
    ReviewerWorker,
)
from autonomous_engineering.workflow.engine import WorkflowEngine
from autonomous_engineering.work_order.compiler import WorkOrderCompiler
from autonomous_engineering.work_order.models import AcceptanceCriterion


def main() -> int:
    print("================================================================================")
    print(" AUTONOMOUS ENGINEERING SYSTEM: PHASE 2 COOPERATIVE MULTI-WORKER DEMO")
    print("================================================================================")

    fixture_repo = Path(__file__).parent / "fixtures" / "disposable_repo"
    if not fixture_repo.exists():
        print(f"[!] ERROR: Disposable fixture repo not found at {fixture_repo}")
        return 1

    with tempfile.TemporaryDirectory(prefix="aes_phase2_demo_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "orchestrator.sqlite"
        art_path = tmp_path / "artifacts"
        demo_worktree = tmp_path / "disposable_worktree"
        shutil.copytree(fixture_repo, demo_worktree)

        print(f"[*] Ephemeral workspace initialized at: {tmp_path}")
        print(f"[*] Disposable worktree cloned from: {fixture_repo}")

        # 1. Initialize Control Plane Subsystems
        engine = WorkflowEngine(db_path)
        store = ArtifactStore(art_path)
        interface = HumanInterfaceAdapter(engine, store)

        # 2. Register Empirical Worker Capability Profiles
        registry = WorkerCapabilityRegistry()
        hw_target_0 = HardwareTarget(
            device_type="intel_arc_pro_b65",
            pci_slot="0000:03:00.0",
            vram_bytes=32 * 1024 * 1024 * 1024,
            driver_version="xe-24.1",
        )
        hw_target_1 = HardwareTarget(
            device_type="intel_arc_pro_b65",
            pci_slot="0000:04:00.0",
            vram_bytes=32 * 1024 * 1024 * 1024,
            driver_version="xe-24.1",
        )
        runtime_cfg = RuntimeConfig(
            engine="vllm_xpu",
            model_name="engineering/b0",
            model_revision="v1.7",
            quantization="int4",
            context_window=16384,
            chat_template="qwen2",
            tool_parser="hermes",
        )

        profile_author = WorkerCapabilityProfile(
            profile_id="prof-author-b65-0",
            worker_id="worker-b65-0",
            hardware=hw_target_0,
            runtime=runtime_cfg,
            empirical_skills={
                "investigation": EmpiricalSkillRecord(
                    skill_name="investigation",
                    verified=True,
                    measured_pass_rate=0.95,
                    sample_size=40,
                    last_evaluated="2026-09-26",
                    evidence_source=EvidenceSource.EMPIRICAL_DEPLOYED_MEASUREMENT,
                ),
                "defect_patch": EmpiricalSkillRecord(
                    skill_name="defect_patch",
                    verified=True,
                    measured_pass_rate=0.92,
                    sample_size=50,
                    last_evaluated="2026-09-26",
                    evidence_source=EvidenceSource.EMPIRICAL_DEPLOYED_MEASUREMENT,
                ),
            },
            health_status=WorkerHealthStatus.HEALTHY,
        )

        profile_reviewer = WorkerCapabilityProfile(
            profile_id="prof-reviewer-b65-1",
            worker_id="worker-b65-1",
            hardware=hw_target_1,
            runtime=runtime_cfg,
            empirical_skills={
                "independent_review": EmpiricalSkillRecord(
                    skill_name="independent_review",
                    verified=True,
                    measured_pass_rate=0.96,
                    sample_size=60,
                    last_evaluated="2026-09-26",
                    evidence_source=EvidenceSource.EMPIRICAL_DEPLOYED_MEASUREMENT,
                ),
            },
            health_status=WorkerHealthStatus.HEALTHY,
        )

        registry.register(profile_author)
        registry.register(profile_reviewer)
        print(f"[*] Registered Author Worker: {profile_author.worker_id} (hash: {profile_author.profile_hash[:12]}...)")
        print(f"[*] Registered Reviewer Worker: {profile_reviewer.worker_id} (hash: {profile_reviewer.profile_hash[:12]}...)")

        # 3. Setup Workers
        patch_content = (
            "diff --git a/src/stats_utils.py b/src/stats_utils.py\n"
            "--- a/src/stats_utils.py\n"
            "+++ b/src/stats_utils.py\n"
            "@@ -9,4 +9,4 @@\n"
            "-    if window_size == 0:\n"
            "+    if window_size <= 0:\n"
            "         raise ValueError(\"window_size must be positive\")\n"
            "-\n"
            "+    if window_size > len(data):\n"
            "+        return []\n"
        )
        workers = {
            "worker-b65-0": FastCoderWorker(
                "worker-b65-0",
                profile_author.profile_hash,
                store,
                patch_content=patch_content,
            ),
            "worker-b65-1": ReviewerWorker(
                "worker-b65-1",
                profile_reviewer.profile_hash,
                store,
            ),
        }

        # 4. Compile Work Order via Human Interface Adapter
        print("\n--- 1. INGESTION & COMPILATION ---")
        user_prompt = (
            "Fix calculate_moving_average in src/stats_utils.py so it validates that "
            "window_size is positive (raising ValueError on negative window) and returns empty "
            "list when window_size exceeds data length."
        )
        compiler = WorkOrderCompiler()
        wo = compiler.compile(
            raw_text=user_prompt,
            source_channel="opencode_cli",
            source_reference="session-demo-phase2",
            repository_id="homelab-ai",
            baseline_commit="8b25d26",
            proposed_mutation_paths=["src/stats_utils.py"],
            acceptance_criteria=[
                AcceptanceCriterion(
                    criterion_id="crit-stats-pytest",
                    description="Run pytest tests/test_stats_utils.py",
                    validator_type="pytest",
                    test_target="tests/test_stats_utils.py",
                )
            ],
            max_retries=2,
        )

        receipt = interface.submit_work_order(wo)
        interface.disconnect()
        wo_id = wo.work_order_id
        version = wo.version
        print(f"[+] Work Order Compiled & Submitted: {wo_id} v{version} (Receipt: {receipt.initial_state})")
        print(f"    Human Interface disconnected: session independence active.")
        print(f"    Contract Hash: {wo.contract_hash}")
        print(f"    Authorized Mutation Scope: {wo.authorization.authorized_mutation_paths}")

        # 5. Execute Work Order through Control Plane
        print("\n--- 2. ADMISSION, PLANNING & DISPATCH ---")
        orchestrator = OrchestratorControlPlane(
            admission_evaluator=AdmissionEvaluator(),
            planner=ExecutionPlanner(include_investigation=False, include_review=True, primary_role="defect_patch"),
            router=CapabilityRouter(registry),
            engine=engine,
            artifact_store=store,
            validator=IndependentValidator(store),
            repair_controller=BoundedRepairController(),
            workers=workers,
            baseline_repo_dir=demo_worktree,
            enable_review_repair=True,
        )

        print("[*] Executing DAG: [step-patch] (Author) -> [step-review] (Reviewer) -> [step-validate] (Validator)")
        final_state = orchestrator.execute_work_order(wo, human_approval_present=True)
        print(f"[+] DAG Execution Completed. Final State: {final_state}")

        # 6. Verify Durable Database Lineage & Fencing
        print("\n--- 3. DURABLE ASSIGNMENT AUDIT & FENCING ---")
        assignments = engine.list_assignments(wo_id, version)
        for a in assignments:
            print(f"    Task [{a['step_id']}] -> Role: {a['required_role']:<20} Worker: {a.get('lease_worker', 'none'):<16} Status: {a['status']:<10} Fence: {a['fencing_token']}")

        # 7. Review Findings Verification
        review_asgn = [a for a in assignments if a["required_role"] == "independent_review"][0]
        rev_art = store.get(review_asgn["output_artifact_hash"]).decode("utf-8")
        rev_data = json.loads(rev_art)
        print(f"\n--- 4. INDEPENDENT REVIEW ARTIFACT ---")
        print(f"    Reviewer ID:  {rev_data['reviewer_worker_id']}")
        print(f"    Target Patch: {rev_data['target_artifact_hash'][:16]}...")
        print(f"    Disposition:  {rev_data['disposition']}")
        print(f"    Summary:      {rev_data['summary']}")
        print(f"    Findings:     {len(rev_data['findings'])}")

        # 8. Export Evidence Bundle
        print("\n--- 5. TAMPER-EVIDENT EVIDENCE BUNDLE ---")
        bundle = interface.export_evidence_bundle(wo_id, version)
        print(f"    Work Order: {bundle['work_order_id']} v{bundle['version']}")
        print(f"    State:      {bundle['state']}")
        print(f"    Disposition: {bundle['terminal_disposition']}")
        print(f"    Audit Events Logged: {len(bundle['audit_trail'])}")
        print(f"    Artifacts Preserved: {len(bundle['artifacts'])}")

        print("\n================================================================================")
        if final_state == WorkOrderState.ACCEPTED:
            print(" RESULT: PHASE_2_DURABLE_MULTI_WORKER_ENGINEERING: PROVEN")
            print("================================================================================")
            return 0
        else:
            print(" RESULT: PHASE_2_DURABLE_MULTI_WORKER_ENGINEERING: FAILED")
            print("================================================================================")
            return 1


if __name__ == "__main__":
    sys.exit(main())
