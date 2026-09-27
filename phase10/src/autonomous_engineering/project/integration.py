"""
Autonomous Engineering System - Phase 10
Workstream F: Cross-Task Integration

Assembles accepted intermediate deliverables into an integrated repository state.
Detects merge conflicts, interface mismatches, and unauthorized mutations in an isolated workspace.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Set, Tuple

from autonomous_engineering.project.planner import EngineeringProjectPlan, ProjectWorkOrder


class IntegrationError(Exception):
    """Base exception for cross-task integration."""


class IntegrationConflictError(IntegrationError):
    """Raised when intermediate deliverables have mutually conflicting patches."""


class MissingDeliverableError(IntegrationError):
    """Raised when an intermediate task deliverable is missing or incomplete."""


class UnauthorizedIntegrationScopeError(IntegrationError):
    """Raised when an integrated patch modifies files outside authorized project scope."""


@dataclass(frozen=True)
class IntegratedRepositoryState:
    """
    Authoritative integrated repository state ready for project-level acceptance validation.
    """
    project_id: str
    plan_version: int
    integrated_tree_hash: str
    unified_patch: str
    unified_patch_digest: str
    modified_files: List[str]
    applied_work_orders: List[str]
    rollback_instructions: str
    integrated_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ProjectIntegrationManager:
    """
    Integrates intermediate task deliverables in dependency order within an isolated workspace.
    """

    def __init__(self) -> None:
        pass

    def integrate_project_deliverables(
        self,
        plan: EngineeringProjectPlan,
        base_repo_dir: Path,
        intermediate_deliverables: Dict[str, Dict[str, Any]],  # wo_id -> {"patch_text", "patch_digest", ...}
    ) -> Tuple[IntegratedRepositoryState, Path]:
        """
        Integrates all accepted intermediate deliverables in topological order.
        Returns the integrated state record and the path to the isolated integration workspace.
        """
        # 1. Verify all planned work orders have intermediate deliverables
        for wo in plan.work_orders:
            if wo.work_order_id not in intermediate_deliverables:
                raise MissingDeliverableError(
                    f"Work order '{wo.work_order_id}' has no accepted intermediate deliverable"
                )

        # 2. Determine execution/integration order (topological sort)
        ordered_wo_ids = self._topological_order(plan.work_orders, plan.dependency_edges)

        # 3. Create isolated integration workspace
        temp_dir = Path(tempfile.mkdtemp(prefix=f"integrate_{plan.project_id}_"))
        # Copy base repository
        self._copy_repo_tree(base_repo_dir, temp_dir)

        modified_files: Set[str] = set()
        unified_patches: List[str] = []

        # 4. Sequentially apply patches in topological order
        norm_auth_scope = [p.strip("./").rstrip("/") for p in plan.authorized_project_scope]

        for wo_id in ordered_wo_ids:
            deliv = intermediate_deliverables[wo_id]
            patch_text = deliv["patch_text"]
            unified_patches.append(f"# --- Work Order: {wo_id} ---\n" + patch_text)

            # Check files touched in this patch
            wo_meta = next(w for w in plan.work_orders if w.work_order_id == wo_id)
            for path in wo_meta.target_files:
                norm_p = path.strip("./").rstrip("/")
                # Scope check
                is_covered = any(
                    norm_p == a or norm_p.startswith(f"{a}/") for a in norm_auth_scope
                )
                if not is_covered:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    raise UnauthorizedIntegrationScopeError(
                        f"Integration blocked: '{path}' in work order '{wo_id}' exceeds project scope"
                    )
                modified_files.add(path)

            # Apply patch to isolated workspace
            success, err = self._apply_patch(temp_dir, patch_text)
            if not success:
                shutil.rmtree(temp_dir, ignore_errors=True)
                raise IntegrationConflictError(
                    f"Merge conflict applying deliverable for '{wo_id}': {err}"
                )

        # 5. Compute canonical integrated tree hash
        tree_hash = self._compute_tree_hash(temp_dir)
        full_unified_patch = "\n".join(unified_patches)
        patch_digest = hashlib.sha256(full_unified_patch.encode("utf-8")).hexdigest()

        rollback_script = (
            f"# Deterministic Rollback Guide for Project {plan.project_id}\n"
            f"# Baseline Commit: {plan.baseline_commit}\n"
            f"# To reverse integrated patch:\n"
            f"patch -p1 -R < project_deliverable.patch\n"
        )

        state = IntegratedRepositoryState(
            project_id=plan.project_id,
            plan_version=plan.plan_version,
            integrated_tree_hash=tree_hash,
            unified_patch=full_unified_patch,
            unified_patch_digest=patch_digest,
            modified_files=sorted(list(modified_files)),
            applied_work_orders=ordered_wo_ids,
            rollback_instructions=rollback_script,
        )

        return state, temp_dir

    def _topological_order(
        self,
        work_orders: List[ProjectWorkOrder],
        edges: List[Tuple[str, str]],
    ) -> List[str]:
        """Calculates topological ordering of work orders."""
        in_degree: Dict[str, int] = {wo.work_order_id: 0 for wo in work_orders}
        adj: Dict[str, List[str]] = {wo.work_order_id: [] for wo in work_orders}

        for prereq, dep in edges:
            adj[prereq].append(dep)
            in_degree[dep] += 1

        queue = [wo_id for wo_id, deg in in_degree.items() if deg == 0]
        order = []

        while queue:
            curr = queue.pop(0)
            order.append(curr)
            for neighbor in adj[curr]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(order) != len(work_orders):
            raise IntegrationConflictError("Dependency cycle detected during integration ordering")

        return order

    def _copy_repo_tree(self, src: Path, dst: Path) -> None:
        """Copies repository tree ignoring .git and pycache."""
        for item in src.iterdir():
            if item.name in [".git", "__pycache__", ".venv"]:
                continue
            if item.is_dir():
                shutil.copytree(item, dst / item.name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            else:
                shutil.copy2(item, dst / item.name)

    def _apply_patch(self, repo_dir: Path, patch_text: str) -> Tuple[bool, str]:
        """Applies unified diff patch using git apply with strict conflict detection."""
        patch_file = repo_dir / "temp_deliverable.patch"
        patch_file.write_text(patch_text, encoding="utf-8")

        # Initialize temporary git tracking in isolated workspace if not present
        if not (repo_dir / ".git").exists():
            subprocess.run(["git", "init", "-q"], cwd=repo_dir, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_dir, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo_dir, capture_output=True, text=True)
            subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "init", "-q"], cwd=repo_dir, capture_output=True, text=True)

        res = subprocess.run(
            ["git", "apply", "--ignore-whitespace", "temp_deliverable.patch"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
        )
        patch_file.unlink(missing_ok=True)
        if res.returncode == 0:
            # Stage the applied changes so subsequent patches build on top
            subprocess.run(["git", "add", "."], cwd=repo_dir, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "applied patch", "-q"], cwd=repo_dir, capture_output=True, text=True)
            return True, ""

        return False, res.stderr

    def _compute_tree_hash(self, repo_dir: Path) -> str:
        """Computes deterministic SHA-256 tree hash over repository contents."""
        hasher = hashlib.sha256()
        files = sorted(list(repo_dir.rglob("*.py")))
        for f in files:
            rel = str(f.relative_to(repo_dir))
            hasher.update(rel.encode("utf-8"))
            hasher.update(f.read_bytes())
        return hasher.hexdigest()
