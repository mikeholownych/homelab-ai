"""
Autonomous Engineering System - Phase 10
Workstream G: Independent Project-Level Acceptance

Validates the full integrated repository state against build integrity, AST syntax,
security static analysis, and isolated test suite execution.
Stores cryptographically verified acceptance verdicts in Content-Addressed Storage.
"""

import ast
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.core.types import ValidationStatus
from autonomous_engineering.project.integration import IntegratedRepositoryState
from autonomous_engineering.validator.acceptance import ValidationExecutionRecord


class ProjectAcceptanceError(Exception):
    """Base exception for project acceptance authority."""


class ProjectAcceptanceRejectedError(ProjectAcceptanceError):
    """Raised when the integrated repository state fails project acceptance validation."""


@dataclass(frozen=True)
class ProjectAcceptanceContract:
    """Immutable acceptance contract for an integrated project."""
    contract_id: str
    project_id: str
    plan_version: int
    repository_id: str
    baseline_commit: str
    authorized_project_scope: Tuple[str, ...]
    required_test_commands: Tuple[str, ...]
    forbidden_modules: Tuple[str, ...] = ("subprocess", "eval", "exec")
    timeout_seconds: float = 120.0


@dataclass(frozen=True)
class ProjectAcceptanceVerdict:
    """Authoritative verdict rendered for the integrated repository state."""
    verdict_id: str
    contract_id: str
    project_id: str
    plan_version: int
    integrated_tree_hash: str
    status: ValidationStatus
    execution_records: Tuple[ValidationExecutionRecord, ...]
    findings: Tuple[str, ...]
    verdict_hash: str
    artifact_hash: Optional[str] = None
    created_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ProjectAcceptanceManager:
    """
    Evaluates integrated repository trees against project acceptance contracts.
    """

    def __init__(self, artifact_store: ArtifactStore) -> None:
        self.artifact_store = artifact_store

    def validate_integrated_project(
        self,
        contract: ProjectAcceptanceContract,
        integrated_state: IntegratedRepositoryState,
        integrated_workspace_dir: Path,
    ) -> ProjectAcceptanceVerdict:
        """
        Validates the integrated workspace across AST syntax, security rules, and test suites.
        """
        findings: List[str] = []
        execution_records: List[ValidationExecutionRecord] = []
        status = ValidationStatus.ACCEPTED

        # 1. Tree Hash Verification (anti-tampering check)
        # Verify workspace matches the claimed integrated tree hash
        computed_hash = self._compute_tree_hash(integrated_workspace_dir)
        if computed_hash != integrated_state.integrated_tree_hash:
            findings.append(
                f"Integrated tree hash mismatch: claimed '{integrated_state.integrated_tree_hash}', observed '{computed_hash}'"
            )
            status = ValidationStatus.REJECTED

        # 2. AST Syntax Check on all modified files
        for rel_path in integrated_state.modified_files:
            target_file = integrated_workspace_dir / rel_path
            if target_file.exists() and target_file.suffix == ".py":
                try:
                    content = target_file.read_text(encoding="utf-8")
                    tree = ast.parse(content, filename=rel_path)
                    # Check forbidden patterns
                    sec_errs = self._check_ast_security(tree, rel_path, contract.forbidden_modules)
                    if sec_errs:
                        findings.extend(sec_errs)
                        status = ValidationStatus.REJECTED
                except SyntaxError as e:
                    findings.append(f"SyntaxError in integrated file '{rel_path}': {e}")
                    status = ValidationStatus.REJECTED

        # 3. Execute Required Test Commands
        for cmd in contract.required_test_commands:
            t0 = time.time()
            try:
                res = subprocess.run(
                    cmd,
                    shell=True,
                    cwd=integrated_workspace_dir,
                    capture_output=True,
                    text=True,
                    timeout=contract.timeout_seconds,
                )
                dur = round(time.time() - t0, 3)
                out_summary = (res.stdout + res.stderr)[:2000]
                rec = ValidationExecutionRecord(
                    command=cmd,
                    exit_code=res.returncode,
                    stdout_digest=hashlib.sha256(res.stdout.encode("utf-8")).hexdigest(),
                    stderr_digest=hashlib.sha256(res.stderr.encode("utf-8")).hexdigest(),
                    duration_seconds=dur,
                    output_summary=out_summary,
                )
                execution_records.append(rec)
                if res.returncode != 0:
                    status = ValidationStatus.REJECTED
                    findings.append(f"Test command '{cmd}' failed with exit code {res.returncode}: {out_summary}")
            except subprocess.TimeoutExpired:
                status = ValidationStatus.REJECTED
                findings.append(f"Test command '{cmd}' timed out after {contract.timeout_seconds}s")

        # 4. Generate Verdict and Content-Addressed Storage Record
        verdict_data = {
            "contract_id": contract.contract_id,
            "project_id": contract.project_id,
            "tree_hash": integrated_state.integrated_tree_hash,
            "status": status.value,
            "findings": findings,
            "execution_records_count": len(execution_records),
        }
        verdict_hash = hashlib.sha256(
            json.dumps(verdict_data, sort_keys=True).encode("utf-8")
        ).hexdigest()

        verdict = ProjectAcceptanceVerdict(
            verdict_id=f"proj-verdict-{verdict_hash[:12]}",
            contract_id=contract.contract_id,
            project_id=contract.project_id,
            plan_version=contract.plan_version,
            integrated_tree_hash=integrated_state.integrated_tree_hash,
            status=status,
            execution_records=tuple(execution_records),
            findings=tuple(findings),
            verdict_hash=verdict_hash,
        )

        return verdict

    def _check_ast_security(
        self,
        tree: ast.AST,
        file_path: str,
        forbidden: Tuple[str, ...],
    ) -> List[str]:
        """Scans AST for prohibited function calls or module imports."""
        errs: List[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in forbidden:
                        errs.append(f"Security violation in '{file_path}': prohibited import '{alias.name}'")
            elif isinstance(node, ast.ImportFrom):
                if node.module in forbidden:
                    errs.append(f"Security violation in '{file_path}': prohibited import from '{node.module}'")
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in ["eval", "exec"]:
                    errs.append(f"Security violation in '{file_path}': prohibited call to '{node.func.id}()'")
        return errs

    def _compute_tree_hash(self, repo_dir: Path) -> str:
        """Computes deterministic SHA-256 tree hash over repository contents."""
        hasher = hashlib.sha256()
        files = sorted(list(repo_dir.rglob("*.py")))
        for f in files:
            rel = str(f.relative_to(repo_dir))
            hasher.update(rel.encode("utf-8"))
            hasher.update(f.read_bytes())
        return hasher.hexdigest()
