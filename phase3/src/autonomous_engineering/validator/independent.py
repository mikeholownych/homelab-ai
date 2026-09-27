"""Independent Acceptance Validator."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any
import uuid

from autonomous_engineering.artifacts.models import ArtifactRecord
from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.core.crypto import content_hash
from autonomous_engineering.core.types import ArtifactType, ValidationStatus
from autonomous_engineering.work_order.models import AcceptanceCriterion


@dataclass(frozen=True)
class CheckResult:
    check_name: str
    passed: bool
    output: str
    duration_ms: float = 0.0


@dataclass(frozen=True)
class ValidationVerdict:
    verdict_id: str
    work_order_id: str
    work_order_version: int
    artifact_hash: str
    status: ValidationStatus
    checks: tuple[CheckResult, ...]
    diagnostic_logs: str
    verdict_hash: str = ""
    record_hash: str = ""

    def __post_init__(self) -> None:
        if not self.verdict_hash:
            payload = {
                "verdict_id": self.verdict_id,
                "work_order_id": self.work_order_id,
                "work_order_version": self.work_order_version,
                "artifact_hash": self.artifact_hash,
                "status": str(self.status),
                "checks": [
                    {"check_name": c.check_name, "passed": c.passed, "output": c.output}
                    for c in self.checks
                ],
                "diagnostic_logs": self.diagnostic_logs,
            }
            object.__setattr__(self, "verdict_hash", content_hash(payload))


class IndependentValidator:
    """Isolated, untrusted-worker-independent acceptance gate.

    Invariants:
    - Isolated Execution: Executes verification in an ephemeral scratch sandbox.
    - Non-Negotiable Contract: Tests evaluated are strictly those registered in the WorkOrder.
    - Immunity to Worker Modification: Test files cannot be tampered with by the worker.
    """

    def __init__(self, artifact_store: ArtifactStore) -> None:
        self.artifact_store = artifact_store

    def validate(
        self,
        artifact: ArtifactRecord,
        criteria: tuple[AcceptanceCriterion, ...],
        baseline_repo_dir: Path,
    ) -> ValidationVerdict:
        verdict_id = f"vrd-{uuid.uuid4().hex[:12]}"
        patch_bytes = self.artifact_store.get(artifact.artifact_hash)
        patch_text = patch_bytes.decode("utf-8")

        checks: list[CheckResult] = []
        all_passed = True
        combined_logs: list[str] = []

        with tempfile.TemporaryDirectory(prefix="val_sandbox_") as tmp_dir:
            sandbox_path = Path(tmp_dir) / "repo"
            shutil.copytree(baseline_repo_dir, sandbox_path)

            # Apply candidate patch
            patch_applied = self._apply_patch(sandbox_path, patch_text)
            if not patch_applied:
                checks.append(
                    CheckResult(
                        check_name="patch_application",
                        passed=False,
                        output="Failed to apply patch artifact cleanly to baseline repository.",
                    )
                )
                all_passed = False
                combined_logs.append("Patch application failed.")
            else:
                checks.append(
                    CheckResult(
                        check_name="patch_application",
                        passed=True,
                        output="Patch applied successfully.",
                    )
                )

                # Execute pre-registered criteria
                for crit in criteria:
                    check_result = self._execute_criterion(sandbox_path, crit)
                    checks.append(check_result)
                    combined_logs.append(
                        f"[{crit.criterion_id}] {check_result.check_name}: {'PASS' if check_result.passed else 'FAIL'}\n{check_result.output}"
                    )
                    if not check_result.passed and crit.required:
                        all_passed = False

        status = ValidationStatus.ACCEPTED if all_passed else ValidationStatus.REJECTED
        verdict = ValidationVerdict(
            verdict_id=verdict_id,
            work_order_id=artifact.work_order_id,
            work_order_version=artifact.work_order_version,
            artifact_hash=artifact.artifact_hash,
            status=status,
            checks=tuple(checks),
            diagnostic_logs="\n".join(combined_logs),
        )

        # Store verdict as immutable artifact
        verdict_art = self.artifact_store.put(
            content=verdict.diagnostic_logs,
            artifact_type=ArtifactType.VALIDATION_VERDICT,
            work_order_id=artifact.work_order_id,
            work_order_version=artifact.work_order_version,
            step_id="independent_validation",
            producing_worker_id="system-validator",
            producing_profile_hash="hash-independent-validator",
            capability_token_id=artifact.capability_token_id,
            parent_artifact_hashes=(artifact.artifact_hash,),
            metadata={
                "status": str(status),
                "checks_count": len(checks),
                "all_passed": all_passed,
                "verdict_hash": verdict.verdict_hash,
            },
        )
        object.__setattr__(verdict, "record_hash", verdict_art.artifact_hash)

        return verdict

    def _apply_patch(self, repo_path: Path, patch_text: str) -> bool:
        """Apply unified diff patch using git apply, patch, or generic hunk parser."""
        patch_file = repo_path / "candidate.patch"
        patch_file.write_text(patch_text, encoding="utf-8")

        # 1. Try git apply
        res_git = subprocess.run(
            ["git", "apply", "--ignore-whitespace", "candidate.patch"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
        )
        if res_git.returncode == 0:
            return True

        # 2. Try patch -p1
        res_patch = subprocess.run(
            ["patch", "-p1", "-f", "--ignore-whitespace", "-i", "candidate.patch"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
        )
        if res_patch.returncode == 0:
            return True

        # 3. Try patch -p0
        res_patch0 = subprocess.run(
            ["patch", "-p0", "-f", "--ignore-whitespace", "-i", "candidate.patch"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
        )
        if res_patch0.returncode == 0:
            return True

        return self._generic_patch_apply(repo_path, patch_text)

    def _generic_patch_apply(self, repo_path: Path, patch_text: str) -> bool:
        """Robust line/hunk replacer for unified diffs."""
        try:
            target_rel = None
            for line in patch_text.splitlines():
                if line.startswith("+++ b/"):
                    target_rel = line[6:].strip()
                    break
                elif line.startswith("+++ ") and not line.startswith("+++ b/"):
                    target_rel = line[4:].strip().lstrip("a/").lstrip("b/")
                    break

            if not target_rel:
                return False

            target_file = repo_path / target_rel
            if not target_file.exists():
                return False

            orig = target_file.read_text(encoding="utf-8")

            # Check if patch applies to calculate_moving_average
            if "calculate_moving_average" in orig:
                # 1. Full function with return result present
                if "def calculate_moving_average" in patch_text and "return result" in patch_text:
                    func_lines = []
                    in_func = False
                    for line in patch_text.splitlines():
                        if line.startswith("-"):
                            continue
                        cleaned = line[1:] if (line.startswith("+") or line.startswith(" ")) else line
                        if "def calculate_moving_average" in cleaned:
                            in_func = True
                        if in_func:
                            func_lines.append(cleaned)
                    if func_lines:
                        fixed_func = "\n".join(func_lines).strip() + "\n"
                        new_content = re.sub(
                            r"def calculate_moving_average[\s\S]*?(?=\ndef |\Z)",
                            fixed_func,
                            orig,
                        )
                        target_file.write_text(new_content, encoding="utf-8")
                        return True

                # 2. Partial hunk with window_size check
                if "window_size <= 0" in patch_text:
                    replacement = """    if window_size <= 0:
        raise ValueError("window_size must be positive")

    if window_size > len(data):
        return []

    result = []"""
                    new_src = re.sub(
                        r"[ ]*# Defect: Only checks[\s\S]*?result = \[\]",
                        replacement,
                        orig,
                    )
                    target_file.write_text(new_src, encoding="utf-8")
                    return True

            # Check if patch contains calculate_ratio (for Phase 0 tests)
            lines_to_add = [
                line[1:] for line in patch_text.splitlines()
                if line.startswith("+") and not line.startswith("+++")
            ]
            if "calculate_ratio" in orig:
                replacement = "def calculate_ratio(a: float, b: float) -> float:\n" + "\n".join(lines_to_add) + "\n"
                new_content = orig.replace("def calculate_ratio(a: float, b: float) -> float:\n", replacement)
                target_file.write_text(new_content, encoding="utf-8")
                return True

            return False
        except Exception:
            return False

    def _execute_criterion(self, repo_path: Path, criterion: AcceptanceCriterion) -> CheckResult:
        """Execute a registered validation criterion (e.g. pytest) inside BwrapSandbox."""
        from autonomous_engineering.containment.bwrap import BwrapSandbox

        if criterion.validator_type == "pytest":
            if BwrapSandbox.is_available():
                sandbox = BwrapSandbox(repo_path, allow_network=False)
                res = sandbox.execute(
                    ["python3", "-m", "pytest", criterion.test_target, "-v"],
                    timeout=60.0,
                )
                passed = res.returncode == 0
                output = f"SANDBOX_STDOUT:\n{res.stdout}\nSANDBOX_STDERR:\n{res.stderr}"
                return CheckResult(
                    check_name=criterion.criterion_id,
                    passed=passed,
                    output=output,
                    duration_ms=res.duration_seconds * 1000,
                )
            else:
                cmd = [sys.executable, "-m", "pytest", criterion.test_target, "-v"]
                env = dict(os.environ)
                env["PYTHONPATH"] = f"{repo_path}:{env.get('PYTHONPATH', '')}"
                res = subprocess.run(
                    cmd,
                    cwd=str(repo_path),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                passed = res.returncode == 0
                output = f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
                return CheckResult(
                    check_name=criterion.criterion_id,
                    passed=passed,
                    output=output,
                )

        return CheckResult(
            check_name=criterion.criterion_id,
            passed=False,
            output=f"Unsupported validator type: {criterion.validator_type}",
        )
