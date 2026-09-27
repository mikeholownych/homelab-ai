"""Independent Acceptance Manager and Acceptance Contract Authority for Phase 8."""
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Dict, List, Optional, Tuple, Any

from autonomous_engineering.artifacts.models import ArtifactType
from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.core.crypto import content_hash
from autonomous_engineering.core.types import ValidationStatus
from autonomous_engineering.repository.onboarding import RepositoryContract
from autonomous_engineering.work_order.models import WorkOrder

logger = logging.getLogger(__name__)


class AcceptanceAuthorityError(Exception):
    """Base error for acceptance authority enforcement."""


class ValidatorTamperingError(AcceptanceAuthorityError):
    """Raised when an untrusted worker attempts to tamper with validator definitions or test contracts."""


@dataclass(frozen=True)
class AcceptanceContract:
    """Immutable acceptance contract binding validation rules outside worker authority."""
    contract_id: str
    work_order_id: str
    work_order_version: int
    repository_id: str
    baseline_commit: str
    authorized_scope: Tuple[str, ...]
    required_tests: Tuple[str, ...]
    required_static_checks: Tuple[str, ...] = ("ast_syntax",)
    security_checks: Tuple[str, ...] = ("no_eval", "no_hardcoded_secrets")
    validator_identity: str = "independent-acceptance-v8"
    validator_version: str = "8.0.0"
    timeout_seconds: float = 60.0

    def contract_digest(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True).encode("utf-8")
        return content_hash(raw)


@dataclass(frozen=True)
class ValidationExecutionRecord:
    """Audit record of a specific validator execution."""
    command: str
    exit_code: int
    stdout_digest: str
    stderr_digest: str
    duration_seconds: float
    output_summary: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass(frozen=True)
class AcceptanceVerdict:
    """Authoritative verdict rendered by the IndependentAcceptanceManager."""
    verdict_id: str
    contract_id: str
    work_order_id: str
    work_order_version: int
    tree_hash: str
    status: ValidationStatus
    execution_records: Tuple[ValidationExecutionRecord, ...]
    findings: Tuple[str, ...]
    verdict_hash: str
    artifact_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class IndependentAcceptanceManager:
    """Enforces independent acceptance validation outside worker authority."""

    def __init__(self, artifact_store: ArtifactStore) -> None:
        self.artifact_store = artifact_store

    def create_contract(
        self, work_order: WorkOrder, repo_contract: RepositoryContract
    ) -> AcceptanceContract:
        """Creates an immutable acceptance contract bound to the work order revision and repository baseline."""
        contract_id = f"ac-{work_order.work_order_id}-v{work_order.version}"
        return AcceptanceContract(
            contract_id=contract_id,
            work_order_id=work_order.work_order_id,
            work_order_version=work_order.version,
            repository_id=repo_contract.repository_id,
            baseline_commit=repo_contract.baseline_commit,
            authorized_scope=repo_contract.authorized_mutation_paths,
            required_tests=repo_contract.required_test_commands,
        )

    def validate_proposed_tree(
        self,
        contract: AcceptanceContract,
        proposed_repo_dir: Path,
        patch_text: str,
        trusted_test_dir: Optional[Path] = None,
    ) -> AcceptanceVerdict:
        """Executes independent validation against the proposed repository tree."""
        # 1. Anti-Tampering Check: Ensure patch does not tamper with validator definitions or protected tests
        self._check_anti_tampering(contract, patch_text)

        execution_records: List[ValidationExecutionRecord] = []
        findings: List[str] = []
        overall_status = ValidationStatus.ACCEPTED

        # 2. Compute Proposed Tree Hash
        from autonomous_engineering.workflow.hardened_pipeline import compute_directory_tree_hash
        tree_hash = compute_directory_tree_hash(proposed_repo_dir)

        # 3. Static AST & Syntax Checks
        ast_ok, ast_msg = self._run_static_ast_check(proposed_repo_dir)
        if not ast_ok:
            overall_status = ValidationStatus.REJECTED
            findings.append(f"Static syntax check failed: {ast_msg}")
            execution_records.append(
                ValidationExecutionRecord(
                    command="python_ast_check",
                    exit_code=1,
                    stdout_digest=content_hash(b""),
                    stderr_digest=content_hash(ast_msg.encode("utf-8")),
                    duration_seconds=0.01,
                    output_summary=ast_msg,
                )
            )

        # 4. Security Rule Checks (no suspicious eval/exec in modified files)
        sec_ok, sec_msg = self._run_security_check(patch_text)
        if not sec_ok:
            overall_status = ValidationStatus.REJECTED
            findings.append(f"Security check failed: {sec_msg}")

        # 5. Execute Required Test Commands in Sandbox
        if overall_status == ValidationStatus.ACCEPTED:
            for test_cmd in contract.required_tests:
                rec, passed = self._execute_test_command(
                    test_cmd, proposed_repo_dir, contract.timeout_seconds
                )
                execution_records.append(rec)
                if not passed:
                    overall_status = ValidationStatus.REJECTED
                    findings.append(f"Test command '{test_cmd}' failed with exit code {rec.exit_code}: {rec.output_summary}")
                    break

        verdict_id = f"verdict-{contract.work_order_id}-v{contract.work_order_version}"
        raw_summary = json.dumps(
            {
                "verdict_id": verdict_id,
                "contract_id": contract.contract_id,
                "tree_hash": tree_hash,
                "status": overall_status.value,
                "findings": findings,
            },
            sort_keys=True,
        ).encode("utf-8")
        verdict_hash = content_hash(raw_summary)

        # Persist verdict artifact in CAS
        art_rec = self.artifact_store.put(
            content=raw_summary,
            artifact_type=ArtifactType.VALIDATION_VERDICT,
            work_order_id=contract.work_order_id,
            work_order_version=contract.work_order_version,
            step_id="step-independent-acceptance",
            producing_worker_id=contract.validator_identity,
            producing_profile_hash=contract.validator_version,
            capability_token_id=f"token-{contract.contract_id}",
        )

        return AcceptanceVerdict(
            verdict_id=verdict_id,
            contract_id=contract.contract_id,
            work_order_id=contract.work_order_id,
            work_order_version=contract.work_order_version,
            tree_hash=tree_hash,
            status=overall_status,
            execution_records=tuple(execution_records),
            findings=tuple(findings),
            verdict_hash=verdict_hash,
            artifact_hash=art_rec.artifact_hash,
        )

    def _check_anti_tampering(self, contract: AcceptanceContract, patch_text: str) -> None:
        """Detects unauthorized alterations to validator definitions or test assertion weakening."""
        for line in patch_text.splitlines():
            # Check for deletion of assert statements in tests
            if line.startswith("-") and not line.startswith("---"):
                if "assert " in line:
                    logger.warning("Patch deleted assertion in test file.")
            # Check for modification of validator files
            if line.startswith("--- a/") or line.startswith("+++ b/"):
                target = line[6:].strip()
                if "validator" in target or "acceptance" in target:
                    raise ValidatorTamperingError(
                        f"Patch attempts to modify protected validator definition '{target}'."
                    )

    def _run_static_ast_check(self, repo_dir: Path) -> Tuple[bool, str]:
        import ast
        for py_file in repo_dir.rglob("*.py"):
            try:
                ast.parse(py_file.read_bytes(), filename=str(py_file))
            except SyntaxError as se:
                return False, f"SyntaxError in {py_file.name}: {se}"
        return True, "AST syntax check passed"

    def _run_security_check(self, patch_text: str) -> Tuple[bool, str]:
        for line in patch_text.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                if "eval(" in line or "exec(" in line:
                    return False, f"Prohibited dynamic code execution detected: {line.strip()}"
        return True, "Security static checks passed"

    def _execute_test_command(
        self, command: str, cwd: Path, timeout: float
    ) -> Tuple[ValidationExecutionRecord, bool]:
        start = time.time()
        try:
            res = subprocess.run(
                command,
                shell=True,
                cwd=str(cwd),
                capture_output=True,
                timeout=timeout,
            )
            duration = time.time() - start
            stdout_d = content_hash(res.stdout)
            stderr_d = content_hash(res.stderr)
            summary = (res.stdout.decode("utf-8", errors="replace") + res.stderr.decode("utf-8", errors="replace"))[-300:].strip()
            rec = ValidationExecutionRecord(
                command=command,
                exit_code=res.returncode,
                stdout_digest=stdout_d,
                stderr_digest=stderr_d,
                duration_seconds=duration,
                output_summary=summary,
            )
            return rec, res.returncode == 0
        except subprocess.TimeoutExpired:
            duration = time.time() - start
            rec = ValidationExecutionRecord(
                command=command,
                exit_code=124,
                stdout_digest=content_hash(b""),
                stderr_digest=content_hash(b"Timeout"),
                duration_seconds=duration,
                output_summary=f"Command timed out after {timeout} seconds",
            )
            return rec, False
        except Exception as e:
            duration = time.time() - start
            rec = ValidationExecutionRecord(
                command=command,
                exit_code=1,
                stdout_digest=content_hash(b""),
                stderr_digest=content_hash(str(e).encode("utf-8")),
                duration_seconds=duration,
                output_summary=f"Execution error: {e}",
            )
            return rec, False
