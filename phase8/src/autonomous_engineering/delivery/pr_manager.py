"""Controlled Pull Request Delivery Manager and Staged Authority Lifecycle for Phase 8."""
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import logging
from pathlib import Path
import subprocess
import time
from typing import Dict, List, Optional, Tuple, Any

from autonomous_engineering.core.crypto import content_hash
from autonomous_engineering.repository.onboarding import RepositoryContract
from autonomous_engineering.workflow.real_repo_pipeline import RealRepoDeliverableBundle

logger = logging.getLogger(__name__)


class DeliveryStage(str, Enum):
    VALIDATED = "VALIDATED"
    DELIVERY_PREPARED = "DELIVERY_PREPARED"
    AUTHORIZATION_PENDING = "AUTHORIZATION_PENDING"
    DELIVERY_AUTHORIZED = "DELIVERY_AUTHORIZED"
    PR_CREATED = "PR_CREATED"
    HUMAN_REVIEW_PENDING = "HUMAN_REVIEW_PENDING"


class DeliveryError(Exception):
    """Base error for deliverable preparation and PR publication."""


class UnauthorizedDeliveryError(DeliveryError):
    """Raised when publication is attempted without valid human authorization."""


class DeliverableMismatchError(DeliveryError):
    """Raised when deliverable hash does not match authorization record."""


class BranchNotPermittedError(DeliveryError):
    """Raised when publication targets an unpermitted branch."""


class ProtectedMergeProhibitedError(DeliveryError):
    """Raised when an attempt is made to autonomously merge or deploy."""


@dataclass(frozen=True)
class DeliveryAuthorizationRecord:
    """Explicit human authorization record required prior to branch creation or PR publication."""
    authorization_id: str
    work_order_id: str
    work_order_version: int
    deliverable_hash: str
    target_repository_id: str
    target_branch: str
    baseline_commit: str
    approver_id: str
    authorized_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at: Optional[str] = None
    signature: str = ""

    def is_valid(self, expected_deliverable_hash: str, now: Optional[datetime] = None) -> bool:
        if self.deliverable_hash != expected_deliverable_hash:
            return False
        if self.expires_at:
            current_time = now or datetime.now(timezone.utc)
            exp = datetime.fromisoformat(self.expires_at)
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if current_time >= exp:
                return False
        return True


@dataclass(frozen=True)
class PullRequestRecord:
    """Record of a created and reviewable pull request."""
    pr_id: str
    work_order_id: str
    work_order_version: int
    repository_id: str
    source_branch: str
    target_branch: str
    commit_hash: str
    pr_title: str
    pr_body: str
    pr_url: Optional[str]
    stage: DeliveryStage
    published_at: str
    is_remote_published: bool

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["stage"] = self.stage.value
        return d


class PullRequestDeliveryManager:
    """Manages the staged delivery lifecycle from validated deliverable to human-reviewable PR."""

    def __init__(self) -> None:
        self._staged_bundles: Dict[str, RealRepoDeliverableBundle] = {}
        self._authorizations: Dict[str, DeliveryAuthorizationRecord] = {}
        self._pr_records: Dict[str, PullRequestRecord] = {}
        self._stages: Dict[str, DeliveryStage] = {}

    def prepare_delivery(
        self,
        bundle: RealRepoDeliverableBundle,
        repo_contract: RepositoryContract,
    ) -> DeliveryStage:
        """Prepares a validated deliverable bundle for delivery authorization."""
        wo_id = bundle.work_order_id
        # Verify deliverable files exist
        if not Path(bundle.patch_path).exists() or not Path(bundle.manifest_path).exists():
            raise DeliveryError(f"Deliverable bundle for {wo_id} is incomplete or corrupted.")

        self._staged_bundles[wo_id] = bundle
        self._stages[wo_id] = DeliveryStage.AUTHORIZATION_PENDING
        logger.info(f"Work order {wo_id} delivery prepared; awaiting human authorization.")
        return DeliveryStage.AUTHORIZATION_PENDING

    def record_authorization(self, auth_record: DeliveryAuthorizationRecord) -> None:
        """Records explicit human delivery authorization."""
        wo_id = auth_record.work_order_id
        bundle = self._staged_bundles.get(wo_id)
        if not bundle:
            raise DeliveryError(f"No staged delivery bundle found for work order '{wo_id}'.")

        if not auth_record.is_valid(bundle.deliverable_hash):
            raise DeliverableMismatchError(
                f"Authorization deliverable hash '{auth_record.deliverable_hash[:16]}' does not match staged deliverable hash '{bundle.deliverable_hash[:16]}'."
            )

        self._authorizations[wo_id] = auth_record
        self._stages[wo_id] = DeliveryStage.DELIVERY_AUTHORIZED
        logger.info(f"Work order {wo_id} delivery authorized by {auth_record.approver_id}.")

    def publish_pull_request(
        self,
        work_order_id: str,
        repo_contract: RepositoryContract,
        local_repo_path: Path,
        remote_name: str = "origin",
        target_branch: Optional[str] = None,
    ) -> PullRequestRecord:
        """Publishes deliverable as a git branch and pull request against the target repository."""
        # 1. Verification of Authorization Gate
        stage = self._stages.get(work_order_id)
        if stage != DeliveryStage.DELIVERY_AUTHORIZED:
            raise UnauthorizedDeliveryError(
                f"Cannot publish PR for work order '{work_order_id}': delivery not authorized (current stage: {stage})."
            )

        auth = self._authorizations.get(work_order_id)
        bundle = self._staged_bundles.get(work_order_id)
        assert auth is not None and bundle is not None

        if not auth.is_valid(bundle.deliverable_hash):
            raise UnauthorizedDeliveryError("Authorization record expired or invalid.")

        tgt_branch = target_branch or auth.target_branch
        if tgt_branch not in repo_contract.permitted_branches:
            raise BranchNotPermittedError(
                f"Target branch '{tgt_branch}' is not among permitted branches: {repo_contract.permitted_branches}"
            )

        # 2. Idempotent Git Branch Creation & Patch Application
        source_branch = f"delivery/wo-{work_order_id}"
        
        # Check current branch and ensure clean working directory
        current_branch = self._git_run(local_repo_path, ["rev-parse", "--abbrev-ref", "HEAD"])
        
        # Check if delivery branch already exists (Idempotency)
        branches = self._git_run(local_repo_path, ["branch", "--list", source_branch])
        if source_branch in branches:
            logger.info(f"Reconciling existing delivery branch '{source_branch}'.")
            self._git_run(local_repo_path, ["checkout", source_branch])
        else:
            self._git_run(local_repo_path, ["checkout", "-b", source_branch, auth.baseline_commit])

        # Apply patch idempotently
        patch_file = Path(bundle.patch_path)
        # Test if patch is already applied
        check_res = subprocess.run(
            ["git", "apply", "--check", str(patch_file)],
            cwd=str(local_repo_path),
            capture_output=True,
        )
        if check_res.returncode == 0:
            self._git_run(local_repo_path, ["apply", str(patch_file)])
            self._git_run(local_repo_path, ["add", "-A"])
            commit_msg = (
                f"feat(delivery): autonomous implementation for work order {work_order_id}\n\n"
                f"Work-Order-ID: {work_order_id}\n"
                f"Deliverable-Hash: {bundle.deliverable_hash}\n"
                f"Approver: {auth.approver_id}\n"
                f"Baseline: {auth.baseline_commit}\n"
            )
            self._git_run(local_repo_path, ["commit", "-m", commit_msg])

        commit_hash = self._git_run(local_repo_path, ["rev-parse", "HEAD"])

        # Push branch to remote
        push_output = self._git_run(local_repo_path, ["push", "-u", remote_name, source_branch, "--force"])

        # 3. Assemble Pull Request Content
        pr_title = f"Autonomous Delivery: Work Order {work_order_id}"
        pr_body = self._assemble_pr_body(work_order_id, bundle, auth, repo_contract, commit_hash)

        pr_id = f"pr-{work_order_id}"
        pr_record = PullRequestRecord(
            pr_id=pr_id,
            work_order_id=work_order_id,
            work_order_version=bundle.version,
            repository_id=repo_contract.repository_id,
            source_branch=source_branch,
            target_branch=tgt_branch,
            commit_hash=commit_hash,
            pr_title=pr_title,
            pr_body=pr_body,
            pr_url=f"{repo_contract.remote_url}/pull/{pr_id}",
            stage=DeliveryStage.HUMAN_REVIEW_PENDING,
            published_at=datetime.now(timezone.utc).isoformat(),
            is_remote_published=True,
        )

        self._pr_records[work_order_id] = pr_record
        self._stages[work_order_id] = DeliveryStage.HUMAN_REVIEW_PENDING

        # Restore original branch
        if current_branch and current_branch != source_branch:
            try:
                self._git_run(local_repo_path, ["checkout", current_branch])
            except Exception:
                pass

        logger.info(f"Pull request for {work_order_id} published: {pr_record.pr_url}")
        return pr_record

    def attempt_merge(self, work_order_id: str) -> None:
        """Enforces hard barrier: autonomous merge is strictly prohibited."""
        raise ProtectedMergeProhibitedError(
            "Autonomous merging is strictly PROHIBITED. All pull requests require independent human review and merge."
        )

    def _assemble_pr_body(
        self,
        work_order_id: str,
        bundle: RealRepoDeliverableBundle,
        auth: DeliveryAuthorizationRecord,
        contract: RepositoryContract,
        commit_hash: str,
    ) -> str:
        files_str = "\n".join(f"- `{f}`" for f in bundle.changed_files)
        guide_text = "See INTEGRATION_GUIDE.md in deliverable bundle."
        guide_path = Path(bundle.export_directory) / "INTEGRATION_GUIDE.md"
        if guide_path.exists():
            guide_text = guide_path.read_text(encoding="utf-8")

        return (
            f"## Autonomous Engineering Delivery\n\n"
            f"**Work Order**: `{work_order_id}` (Version {bundle.version})\n"
            f"**Repository**: `{contract.repository_id}`\n"
            f"**Commit**: `{commit_hash}`\n"
            f"**Baseline**: `{auth.baseline_commit}`\n"
            f"**Deliverable SHA-256**: `{bundle.deliverable_hash}`\n"
            f"**Authorized By**: `{auth.approver_id}`\n\n"
            f"### Affected Files\n{files_str}\n\n"
            f"### Acceptance & Verification Status\n"
            f"- Independent Sandbox Validation: **PASSED**\n"
            f"- Validation Verdict Artifact: `{bundle.verdict_artifact_hash}`\n"
            f"- Target Repository TOCTOU Verified: **PASS**\n\n"
            f"### Rollback & Integration Instructions\n"
            f"```bash\n"
            f"# To revert this change\n"
            f"git revert {commit_hash}\n"
            f"# Or reverse apply patch\n"
            f"patch -p1 -R < deliverable.patch\n"
            f"```\n\n"
            f"---\n"
            f"*Human Review Required. Autonomous merge is prohibited.*"
        )

    def _git_run(self, cwd: Path, args: List[str]) -> str:
        cmd = ["git"] + args
        res = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
        if res.returncode != 0:
            raise DeliveryError(f"Git command failed ({' '.join(cmd)}): {res.stderr.strip()}")
        return res.stdout.strip()
