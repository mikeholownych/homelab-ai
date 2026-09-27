"""Tests for Controlled Pull Request Delivery, Authorization Gates, and Idempotency."""
import subprocess
import tempfile
from pathlib import Path
import pytest

from autonomous_engineering.delivery.pr_manager import (
    BranchNotPermittedError,
    DeliverableMismatchError,
    DeliveryAuthorizationRecord,
    DeliveryStage,
    ProtectedMergeProhibitedError,
    PullRequestDeliveryManager,
    UnauthorizedDeliveryError,
)
from autonomous_engineering.repository.onboarding import RepositoryContract
from autonomous_engineering.workflow.real_repo_pipeline import RealRepoDeliverableBundle


@pytest.fixture
def delivery_env():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        # Create bare remote repository (upstream)
        remote_bare_dir = tmp_path / "remote_upstream.git"
        subprocess.run(["git", "init", "--bare", str(remote_bare_dir)], check=True, capture_output=True)

        # Create local repository cloned from remote bare
        local_repo_dir = tmp_path / "local_repo"
        subprocess.run(["git", "clone", str(remote_bare_dir), str(local_repo_dir)], check=True, capture_output=True)
        # Configure local git identity
        subprocess.run(["git", "config", "user.name", "Test Deliverer"], cwd=str(local_repo_dir), check=True)
        subprocess.run(["git", "config", "user.email", "test@delivery.local"], cwd=str(local_repo_dir), check=True)

        # Initial commit on main branch
        (local_repo_dir / "service.py").write_text("def ping(): return 'pong'\n")
        subprocess.run(["git", "add", "service.py"], cwd=str(local_repo_dir), check=True)
        subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(local_repo_dir), check=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=str(local_repo_dir), check=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=str(local_repo_dir), check=True)
        baseline_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(local_repo_dir), capture_output=True, text=True, check=True
        ).stdout.strip()

        # Create export bundle
        export_dir = tmp_path / "deliverable_export"
        export_dir.mkdir()
        patch_file = export_dir / "deliverable.patch"
        patch_file.write_text("--- service.py\n+++ service.py\n@@ -1,1 +1,2 @@\n def ping(): return 'pong'\n+# verified feature\n")
        manifest_file = export_dir / "manifest.sha256"
        manifest_file.write_text("dummy-hash deliverable.patch\n")
        guide_file = export_dir / "INTEGRATION_GUIDE.md"
        guide_file.write_text("# Human Integration Guide\nExecute: patch -p1 -R < deliverable.patch\n")

        bundle = RealRepoDeliverableBundle(
            work_order_id="wo-deliv-801",
            version=1,
            deliverable_hash="abc123deliverablehash801",
            patch_artifact_hash="patch801hash",
            review_artifact_hash="rev801hash",
            verdict_artifact_hash="verdict801hash",
            changed_files=["service.py"],
            patch_path=str(patch_file),
            manifest_path=str(manifest_file),
            integration_instructions="Apply patch",
            routing_records=[],
            exported_at="2026-09-27T15:00:00Z",
            export_directory=str(export_dir),
        )

        repo_contract = RepositoryContract(
            repository_id="test-service-repo",
            remote_url=str(remote_bare_dir),
            baseline_commit=baseline_commit,
            permitted_branches=("main",),
            authorized_mutation_paths=("service.py",),
        )

        manager = PullRequestDeliveryManager()

        yield {
            "manager": manager,
            "bundle": bundle,
            "repo_contract": repo_contract,
            "local_repo": local_repo_dir,
            "remote_bare": remote_bare_dir,
            "baseline_commit": baseline_commit,
        }


def test_staged_delivery_lifecycle_and_authorization_gate(delivery_env):
    """Verifies that delivery cannot proceed without valid, matching human authorization."""
    mgr = delivery_env["manager"]
    bundle = delivery_env["bundle"]
    contract = delivery_env["repo_contract"]
    local_repo = delivery_env["local_repo"]

    # 1. Prepare delivery
    stage = mgr.prepare_delivery(bundle, contract)
    assert stage == DeliveryStage.AUTHORIZATION_PENDING

    # 2. Attempt publish without authorization -> UnauthorizedDeliveryError
    with pytest.raises(UnauthorizedDeliveryError, match="delivery not authorized"):
        mgr.publish_pull_request(bundle.work_order_id, contract, local_repo)

    # 3. Attempt authorize with mismatched deliverable hash -> DeliverableMismatchError
    bad_auth = DeliveryAuthorizationRecord(
        authorization_id="auth-bad",
        work_order_id=bundle.work_order_id,
        work_order_version=bundle.version,
        deliverable_hash="WRONG_DELIVERABLE_HASH",
        target_repository_id=contract.repository_id,
        target_branch="main",
        baseline_commit=delivery_env["baseline_commit"],
        approver_id="human-reviewer",
    )
    with pytest.raises(DeliverableMismatchError):
        mgr.record_authorization(bad_auth)


def test_real_git_remote_branch_creation_and_pr_assembly(delivery_env):
    """Verifies real git branch creation, patch commit, remote push, and PR assembly."""
    mgr = delivery_env["manager"]
    bundle = delivery_env["bundle"]
    contract = delivery_env["repo_contract"]
    local_repo = delivery_env["local_repo"]
    remote_bare = delivery_env["remote_bare"]

    # Prepare and authorize
    mgr.prepare_delivery(bundle, contract)
    good_auth = DeliveryAuthorizationRecord(
        authorization_id="auth-ok",
        work_order_id=bundle.work_order_id,
        work_order_version=bundle.version,
        deliverable_hash=bundle.deliverable_hash,
        target_repository_id=contract.repository_id,
        target_branch="main",
        baseline_commit=delivery_env["baseline_commit"],
        approver_id="principal-engineer",
    )
    mgr.record_authorization(good_auth)

    # Publish PR
    pr = mgr.publish_pull_request(bundle.work_order_id, contract, local_repo)
    assert pr.pr_id == f"pr-{bundle.work_order_id}"
    assert pr.source_branch == f"delivery/wo-{bundle.work_order_id}"
    assert pr.target_branch == "main"
    assert pr.stage == DeliveryStage.HUMAN_REVIEW_PENDING
    assert pr.is_remote_published is True
    assert "Autonomous Delivery: Work Order" in pr.pr_title
    assert "git revert" in pr.pr_body

    # Verify branch actually exists in remote bare repository
    branches_res = subprocess.run(
        ["git", "branch", "--list"], cwd=str(remote_bare), capture_output=True, text=True, check=True
    )
    assert f"delivery/wo-{bundle.work_order_id}" in branches_res.stdout


def test_delivery_idempotency_on_retry(delivery_env):
    """Verifies that retrying delivery reconciles existing branch cleanly without duplicate branches or crash."""
    mgr = delivery_env["manager"]
    bundle = delivery_env["bundle"]
    contract = delivery_env["repo_contract"]
    local_repo = delivery_env["local_repo"]

    mgr.prepare_delivery(bundle, contract)
    auth = DeliveryAuthorizationRecord(
        authorization_id="auth-idem",
        work_order_id=bundle.work_order_id,
        work_order_version=bundle.version,
        deliverable_hash=bundle.deliverable_hash,
        target_repository_id=contract.repository_id,
        target_branch="main",
        baseline_commit=delivery_env["baseline_commit"],
        approver_id="principal-engineer",
    )
    mgr.record_authorization(auth)

    # First publication
    pr1 = mgr.publish_pull_request(bundle.work_order_id, contract, local_repo)

    # Reset stage to DELIVERY_AUTHORIZED to simulate retry after network interruption
    mgr._stages[bundle.work_order_id] = DeliveryStage.DELIVERY_AUTHORIZED

    # Second publication (Retry)
    pr2 = mgr.publish_pull_request(bundle.work_order_id, contract, local_repo)
    assert pr1.commit_hash == pr2.commit_hash
    assert pr2.source_branch == pr1.source_branch


def test_autonomous_merge_prohibited(delivery_env):
    """Verifies the strict safety invariant that autonomous merge is unconditionally prohibited."""
    mgr = delivery_env["manager"]
    with pytest.raises(ProtectedMergeProhibitedError, match="Autonomous merging is strictly PROHIBITED"):
        mgr.attempt_merge("wo-deliv-801")
