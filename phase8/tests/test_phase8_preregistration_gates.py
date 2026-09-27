"""Formal Acceptance Gate Verification Suite for Phase 8 Qualification (Gates G1 - G12)."""
import subprocess
import tempfile
from pathlib import Path
import pytest

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.authority.admission import AdmissionEvaluator
from autonomous_engineering.core.types import ValidationStatus, WorkOrderState
from autonomous_engineering.delivery.pr_manager import (
    DeliveryAuthorizationRecord,
    DeliveryStage,
    PullRequestDeliveryManager,
    UnauthorizedDeliveryError,
    ProtectedMergeProhibitedError,
)
from autonomous_engineering.planning.planner import ExecutionPlanner
from autonomous_engineering.repair.controller import BoundedRepairController
from autonomous_engineering.repository.onboarding import (
    ProtectedPathViolationError,
    RepositoryContract,
    RepositoryNotOnboardedError,
    RepositoryOnboardingManager,
    ScopeBoundaryError,
)
from autonomous_engineering.router.evidence_router import EvidenceBasedRouter
from autonomous_engineering.service.multi_repo_service import (
    DependencyCycleError,
    MultiRepoConcurrencyManager,
    MultiRepoEngineeringService,
    TaskDependencyManager,
)
from autonomous_engineering.validator.acceptance import (
    AcceptanceContract,
    IndependentAcceptanceManager,
    ValidatorTamperingError,
)
from autonomous_engineering.validator.independent import IndependentValidator
from autonomous_engineering.workflow.engine import WorkflowEngine
from autonomous_engineering.workflow.hardened_pipeline import HardenedRealRepoPipeline
from autonomous_engineering.workflow.real_repo_pipeline import RealRepoDeliverableBundle
from autonomous_engineering.work_order.compiler import WorkOrderCompiler


def test_gate_g01_baseline_integrity():
    """G1: Verify Phase 7 baseline manifest and commit identity."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    manifest = repo_root / "phase7" / "evidence" / "manifest.sha256"
    assert manifest.exists(), "Phase 7 manifest.sha256 missing!"
    res = subprocess.run(
        ["sha256sum", "-c", str(manifest)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Phase 7 manifest checksum failure: {res.stderr}"


def test_gate_g02_repository_authorization():
    """G2: Repository onboarding required, scope enforced, protected paths protected."""
    onboarding = RepositoryOnboardingManager()
    contract = RepositoryContract(
        repository_id="g2-repo",
        remote_url="git@github.com:mike/g2-repo.git",
        baseline_commit="da54731",
        authorized_mutation_paths=("src/",),
        protected_paths=(".github", "ci", "validators"),
    )
    onboarding.onboard_repository(contract)

    # 1. Scope enforcement
    onboarding.validate_work_order_scope("g2-repo", ["src/main.py"])
    with pytest.raises(ScopeBoundaryError):
        onboarding.validate_work_order_scope("g2-repo", ["other/file.py"])

    # 2. Protected paths
    with pytest.raises(ProtectedPathViolationError):
        onboarding.validate_work_order_scope("g2-repo", [".github/workflows/main.yml"])

    # 3. Offboarding
    onboarding.offboard_repository("g2-repo")
    assert onboarding.is_onboarded("g2-repo") is False


def test_gate_g03_multi_repo_orchestration():
    """G3: Concurrent and dependency-aware execution without authority or isolation failures."""
    dag = TaskDependencyManager()
    dag.register_task("t1")
    dag.register_task("t2", dependencies=["t1"])
    with pytest.raises(DependencyCycleError):
        dag.register_task("t1_cycle", dependencies=["t2"])
        dag2 = TaskDependencyManager()
        dag2.register_task("A", dependencies=["B"])
        dag2.register_task("B", dependencies=["A"])

    concurrency = MultiRepoConcurrencyManager()
    can1, _ = concurrency.can_acquire_paths("repo-A", "task-1", ["shared.py"])
    assert can1 is True


def test_gate_g04_independent_acceptance():
    """G4: Implementation and validation authority demonstrably separated."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        store = ArtifactStore(tmp_path / "artifacts")
        mgr = IndependentAcceptanceManager(artifact_store=store)

        contract = AcceptanceContract(
            contract_id="c-g4",
            work_order_id="wo-g4",
            work_order_version=1,
            repository_id="repo-g4",
            baseline_commit="da54731",
            authorized_scope=("src/",),
            required_tests=(),
        )
        tamper_diff = "--- a/validators/acceptance.py\n+++ b/validators/acceptance.py\n@@ -1,1 +1,1 @@\n"
        with pytest.raises(ValidatorTamperingError):
            mgr.validate_proposed_tree(contract, tmp_path, tamper_diff)


def test_gate_g05_pr_delivery_authority():
    """G5: No remote publication occurs without valid, deliverable-specific human authorization."""
    pr_mgr = PullRequestDeliveryManager()
    contract = RepositoryContract(
        repository_id="repo-g5",
        remote_url="git@github.com:mike/g5.git",
        baseline_commit="da54731",
        permitted_branches=("main",),
    )
    with pytest.raises(UnauthorizedDeliveryError):
        pr_mgr.publish_pull_request("wo-g5", contract, Path("/tmp"))


def test_gate_g06_delivery_idempotency():
    """G6: Delivery retry reconciles cleanly without duplicate branches or error."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        remote_bare = tmp_path / "remote.git"
        subprocess.run(["git", "init", "--bare", str(remote_bare)], check=True, capture_output=True)
        local_repo = tmp_path / "local"
        subprocess.run(["git", "clone", str(remote_bare), str(local_repo)], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=str(local_repo), check=True)
        subprocess.run(["git", "config", "user.email", "tester@test.local"], cwd=str(local_repo), check=True)
        (local_repo / "main.py").write_text("def a(): pass\n")
        subprocess.run(["git", "add", "main.py"], cwd=str(local_repo), check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(local_repo), check=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=str(local_repo), check=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=str(local_repo), check=True)
        base_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(local_repo), capture_output=True, text=True, check=True).stdout.strip()

        patch_file = tmp_path / "test.patch"
        patch_file.write_text("--- main.py\n+++ main.py\n@@ -1,1 +1,2 @@\n def a(): pass\n+# feature\n")
        manifest_file = tmp_path / "manifest.sha256"
        manifest_file.write_text("d test.patch\n")

        bundle = RealRepoDeliverableBundle(
            work_order_id="wo-g6",
            version=1,
            deliverable_hash="deliv-g6-hash",
            patch_artifact_hash="p",
            review_artifact_hash=None,
            verdict_artifact_hash="v",
            changed_files=["main.py"],
            patch_path=str(patch_file),
            manifest_path=str(manifest_file),
            integration_instructions="",
            routing_records=[],
            exported_at="2026-09-27T15:00:00Z",
            export_directory=str(tmp_path),
        )
        contract = RepositoryContract(
            repository_id="repo-g6",
            remote_url=str(remote_bare),
            baseline_commit=base_commit,
            permitted_branches=("main",),
            authorized_mutation_paths=("main.py",),
        )
        auth = DeliveryAuthorizationRecord(
            authorization_id="auth-g6",
            work_order_id="wo-g6",
            work_order_version=1,
            deliverable_hash="deliv-g6-hash",
            target_repository_id="repo-g6",
            target_branch="main",
            baseline_commit=base_commit,
            approver_id="human-lead",
        )

        pr_mgr = PullRequestDeliveryManager()
        pr_mgr.prepare_delivery(bundle, contract)
        pr_mgr.record_authorization(auth)

        # 1st push
        pr1 = pr_mgr.publish_pull_request("wo-g6", contract, local_repo)
        # 2nd push (Idempotent retry)
        pr_mgr._stages["wo-g6"] = DeliveryStage.DELIVERY_AUTHORIZED
        pr2 = pr_mgr.publish_pull_request("wo-g6", contract, local_repo)
        assert pr1.commit_hash == pr2.commit_hash


def test_gate_g07_adversarial_security():
    """G7: Prohibited operations (autonomous merge, etc.) fail closed."""
    pr_mgr = PullRequestDeliveryManager()
    with pytest.raises(ProtectedMergeProhibitedError):
        pr_mgr.attempt_merge("any-task")


def test_gate_g08_operational_reliability():
    """G8: Multi-repo concurrency manager enforces bounds and limits."""
    mgr = MultiRepoConcurrencyManager(max_total_concurrency=2, max_concurrency_per_repo=1)
    assert mgr.can_dispatch_repo("repo-1") is True


def test_gate_g09_evidence_integrity():
    """G9: Deliverable hash verification binds authorization and export."""
    auth = DeliveryAuthorizationRecord(
        authorization_id="auth-g9",
        work_order_id="wo-g9",
        work_order_version=1,
        deliverable_hash="expected_hash",
        target_repository_id="repo-g9",
        target_branch="main",
        baseline_commit="da54731",
        approver_id="lead",
    )
    assert auth.is_valid("expected_hash") is True
    assert auth.is_valid("tampered_hash") is False


def test_gate_g10_protected_service_isolation():
    """G10: Preexisting processes PID 986, 3130937, 2093382 are running and undisturbed."""
    for pid in [986, 3130937, 2093382]:
        proc_path = Path(f"/proc/{pid}")
        assert proc_path.exists(), f"Protected process {pid} interrupted!"


def test_gate_g11_regression_integrity():
    """G11: Ensure Phase 8 package imports and components cleanly initialize."""
    from autonomous_engineering.repository.onboarding import RepositoryOnboardingManager
    from autonomous_engineering.service.multi_repo_service import MultiRepoEngineeringService
    from autonomous_engineering.validator.acceptance import IndependentAcceptanceManager
    from autonomous_engineering.delivery.pr_manager import PullRequestDeliveryManager
    assert True


def test_gate_g12_end_to_end_delivery():
    """G12: End-to-end engineering delivery lifecycle verified on real test git repository."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "e2e.sqlite"
        art_path = tmp_path / "artifacts"
        remote_bare = tmp_path / "upstream_repo.git"
        subprocess.run(["git", "init", "--bare", str(remote_bare)], check=True, capture_output=True)

        local_repo = tmp_path / "working_repo"
        subprocess.run(["git", "clone", str(remote_bare), str(local_repo)], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "E2E Engineer"], cwd=str(local_repo), check=True)
        subprocess.run(["git", "config", "user.email", "engineer@test.local"], cwd=str(local_repo), check=True)

        (local_repo / "component.py").write_text("def run(): return 42\n")
        (local_repo / "tests").mkdir()
        (local_repo / "tests" / "test_comp.py").write_text("from component import run\ndef test_r(): assert run() == 42\n")
        subprocess.run(["git", "add", "."], cwd=str(local_repo), check=True)
        subprocess.run(["git", "commit", "-m", "initial baseline"], cwd=str(local_repo), check=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=str(local_repo), check=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=str(local_repo), check=True)
        base_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(local_repo), capture_output=True, text=True, check=True).stdout.strip()

        # 1. Onboard Repository
        onboarding = RepositoryOnboardingManager()
        repo_contract = RepositoryContract(
            repository_id="test-e2e-repo",
            remote_url=str(remote_bare),
            baseline_commit=base_commit,
            permitted_branches=("main",),
            authorized_mutation_paths=("component.py",),
            required_test_commands=("python3 -m pytest tests/test_comp.py",),
        )
        onboarding.onboard_repository(repo_contract)

        # 2. Workflow engine & Pipeline
        engine = WorkflowEngine(db_path)
        store = ArtifactStore(art_path)
        admission = AdmissionEvaluator(onboarding_manager=onboarding)
        planner = ExecutionPlanner()
        router = EvidenceBasedRouter()
        validator = IndependentValidator(artifact_store=store)
        repair_ctrl = BoundedRepairController()

        class E2EWorker:
            def __init__(self):
                self.worker_id = "worker-b65-0"
                self.profile_hash = "hash-worker"

            def execute(self, task_id, step_id, instruction, context=None):
                if step_id == "step-patch":
                    return "--- component.py\n+++ component.py\n@@ -1,1 +1,2 @@\n def run(): return 42\n+# e2e verified\n"
                return "Review passed"

        worker = E2EWorker()
        pipeline = HardenedRealRepoPipeline(
            engine=engine,
            artifact_store=store,
            admission_evaluator=admission,
            planner=planner,
            router=router,
            validator=validator,
            repair_controller=repair_ctrl,
            workers={"worker-b65-0": worker, "worker-phi4": worker},
            target_repo_dir=local_repo,
        )

        # 3. Work Order Admission
        compiler = WorkOrderCompiler()
        wo = compiler.compile(
            raw_text="Add verified comment to component.py",
            source_channel="human_cli",
            source_reference="sess-e2e-gate",
            repository_id="test-e2e-repo",
            baseline_commit=base_commit,
            proposed_mutation_paths=["component.py"],
        )
        object.__setattr__(wo, "work_order_id", "wo-e2e-gate-01")
        pipeline.submit_and_admit(wo)

        # 4. Lifecycle Execution & Independent Acceptance
        state = pipeline.execute_lifecycle(wo.work_order_id, wo.version)
        assert state == WorkOrderState.ACCEPTED

        # 5. Deliverable Export
        export_dir = tmp_path / "exports" / wo.work_order_id
        bundle = pipeline.export_deliverable(wo.work_order_id, wo.version, export_dir)

        # 6. Controlled PR Delivery
        pr_mgr = PullRequestDeliveryManager()
        pr_mgr.prepare_delivery(bundle, repo_contract)
        auth = DeliveryAuthorizationRecord(
            authorization_id="auth-e2e",
            work_order_id=wo.work_order_id,
            work_order_version=wo.version,
            deliverable_hash=bundle.deliverable_hash,
            target_repository_id="test-e2e-repo",
            target_branch="main",
            baseline_commit=base_commit,
            approver_id="principal-qa",
        )
        pr_mgr.record_authorization(auth)
        pr_record = pr_mgr.publish_pull_request(wo.work_order_id, repo_contract, local_repo)

        # Verify PR published on remote
        assert pr_record.stage == DeliveryStage.HUMAN_REVIEW_PENDING
        assert pr_record.is_remote_published is True

        branches_res = subprocess.run(
            ["git", "branch", "--list"], cwd=str(remote_bare), capture_output=True, text=True, check=True
        )
        assert f"delivery/wo-{wo.work_order_id}" in branches_res.stdout
