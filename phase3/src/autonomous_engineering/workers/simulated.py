"""Simulated Workers and Tool Execution Adapters."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
import uuid

from autonomous_engineering.artifacts.models import ArtifactRecord
from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.authority.guard import ScopeGuard, ScopeViolationError
from autonomous_engineering.authority.tokens import CapabilityToken
from autonomous_engineering.core.crypto import canonical_json
from autonomous_engineering.core.types import ArtifactType
from autonomous_engineering.planning.models import TaskStepDefinition
from autonomous_engineering.review.models import (
    FindingSeverity,
    ReviewDisposition,
    ReviewFinding,
    ReviewReport,
)


@dataclass(frozen=True)
class WorkerExecutionResult:
    worker_id: str
    assignment_id: str
    fencing_token: int
    output_artifact: ArtifactRecord
    logs: str
    exit_code: int


class BaseWorker:
    """Base class for untrusted execution adapters."""

    def __init__(
        self,
        worker_id: str,
        profile_hash: str,
        artifact_store: ArtifactStore,
    ) -> None:
        self.worker_id = worker_id
        self.profile_hash = profile_hash
        self.artifact_store = artifact_store

    def execute(
        self,
        assignment_id: str,
        step: TaskStepDefinition,
        token: CapabilityToken,
        fencing_token: int,
        input_artifacts: tuple[ArtifactRecord, ...] = (),
        repo_dir: Path | None = None,
    ) -> WorkerExecutionResult:
        raise NotImplementedError


class FastCoderWorker(BaseWorker):
    """Simulates a fast code synthesis specialist (e.g. Qwen2.5-Coder on B65-0)."""

    def __init__(
        self,
        worker_id: str = "worker-b65-0",
        profile_hash: str = "hash-b65-0",
        artifact_store: ArtifactStore | None = None,
        patch_content: str | None = None,
    ) -> None:
        super().__init__(worker_id, profile_hash, artifact_store)  # type: ignore
        self.patch_content = patch_content

    def execute(
        self,
        assignment_id: str,
        step: TaskStepDefinition,
        token: CapabilityToken,
        fencing_token: int,
        input_artifacts: tuple[ArtifactRecord, ...] = (),
        repo_dir: Path | None = None,
    ) -> WorkerExecutionResult:
        ScopeGuard.verify_token(token)
        ScopeGuard.check_tool_execution(token, "write_patch")

        # Verify mutation path against authorized scope
        for path in step.target_paths:
            ScopeGuard.check_mutation_path(token, path)

        # Default working patch for the calculator fixture if not explicitly specified
        patch = self.patch_content or (
            "diff --git a/src/calculator/math_utils.py b/src/calculator/math_utils.py\n"
            "--- a/src/calculator/math_utils.py\n"
            "+++ b/src/calculator/math_utils.py\n"
            "@@ -10,2 +10,4 @@\n"
            " def calculate_ratio(a: float, b: float) -> float:\n"
            "+    if b == 0:\n"
            "+        raise ValueError('Denominator cannot be zero')\n"
            "     return a / b\n"
        )

        parent_hashes = tuple(a.artifact_hash for a in input_artifacts)
        artifact = self.artifact_store.put(
            content=patch,
            artifact_type=step.output_artifact_type,
            work_order_id=token.work_order_id,
            work_order_version=token.work_order_version,
            step_id=step.step_id,
            producing_worker_id=self.worker_id,
            producing_profile_hash=self.profile_hash,
            capability_token_id=token.token_id,
            parent_artifact_hashes=parent_hashes,
            metadata={"status": "synthesized_successfully"},
        )

        return WorkerExecutionResult(
            worker_id=self.worker_id,
            assignment_id=assignment_id,
            fencing_token=fencing_token,
            output_artifact=artifact,
            logs=f"Patch generated successfully for {step.step_id}",
            exit_code=0,
        )


class InvestigatorWorker(BaseWorker):
    """Simulates an investigation and reproduction specialist."""

    def execute(
        self,
        assignment_id: str,
        step: TaskStepDefinition,
        token: CapabilityToken,
        fencing_token: int,
        input_artifacts: tuple[ArtifactRecord, ...] = (),
        repo_dir: Path | None = None,
    ) -> WorkerExecutionResult:
        ScopeGuard.verify_token(token)
        ScopeGuard.check_tool_execution(token, "read_file")

        repro_script = (
            "# Reproduction script\n"
            "from src.calculator.math_utils import calculate_ratio\n"
            "try:\n"
            "    calculate_ratio(10, 0)\n"
            "except Exception as e:\n"
            "    print('Observed failure:', type(e), e)\n"
        )

        artifact = self.artifact_store.put(
            content=repro_script,
            artifact_type=ArtifactType.REPRODUCTION_SCRIPT,
            work_order_id=token.work_order_id,
            work_order_version=token.work_order_version,
            step_id=step.step_id,
            producing_worker_id=self.worker_id,
            producing_profile_hash=self.profile_hash,
            capability_token_id=token.token_id,
            parent_artifact_hashes=(),
            metadata={"reproduced": True},
        )

        return WorkerExecutionResult(
            worker_id=self.worker_id,
            assignment_id=assignment_id,
            fencing_token=fencing_token,
            output_artifact=artifact,
            logs="Defect successfully investigated and reproduced.",
            exit_code=0,
        )


class FaultyWorker(BaseWorker):
    """Simulates a worker generating a buggy or incomplete patch."""

    def __init__(
        self,
        worker_id: str = "worker-faulty",
        profile_hash: str = "hash-faulty",
        artifact_store: ArtifactStore | None = None,
        flaw_type: str = "syntax_error",
    ) -> None:
        super().__init__(worker_id, profile_hash, artifact_store)  # type: ignore
        self.flaw_type = flaw_type

    def execute(
        self,
        assignment_id: str,
        step: TaskStepDefinition,
        token: CapabilityToken,
        fencing_token: int,
        input_artifacts: tuple[ArtifactRecord, ...] = (),
        repo_dir: Path | None = None,
    ) -> WorkerExecutionResult:
        ScopeGuard.verify_token(token)
        ScopeGuard.check_tool_execution(token, "write_patch")

        if self.flaw_type == "syntax_error":
            broken_patch = (
                "diff --git a/src/calculator/math_utils.py b/src/calculator/math_utils.py\n"
                "--- a/src/calculator/math_utils.py\n"
                "+++ b/src/calculator/math_utils.py\n"
                "@@ -10,2 +10,3 @@\n"
                " def calculate_ratio(a: float, b: float) -> float:\n"
                "+    this is not valid python syntax !!!\n"
                "     return a / b\n"
            )
        else:
            broken_patch = (
                "diff --git a/src/calculator/math_utils.py b/src/calculator/math_utils.py\n"
                "--- a/src/calculator/math_utils.py\n"
                "+++ b/src/calculator/math_utils.py\n"
                "@@ -10,2 +10,4 @@\n"
                " def calculate_ratio(a: float, b: float) -> float:\n"
                "+    if b == 0:\n"
                "+        return 999999.0  # Incorrect logic; fails test asserting ValueError\n"
                "     return a / b\n"
            )

        artifact = self.artifact_store.put(
            content=broken_patch,
            artifact_type=step.output_artifact_type,
            work_order_id=token.work_order_id,
            work_order_version=token.work_order_version,
            step_id=step.step_id,
            producing_worker_id=self.worker_id,
            producing_profile_hash=self.profile_hash,
            capability_token_id=token.token_id,
            parent_artifact_hashes=tuple(a.artifact_hash for a in input_artifacts),
            metadata={"flaw_type": self.flaw_type},
        )

        return WorkerExecutionResult(
            worker_id=self.worker_id,
            assignment_id=assignment_id,
            fencing_token=fencing_token,
            output_artifact=artifact,
            logs="Flawed patch produced.",
            exit_code=0,
        )


class OutOfScopeWorker(BaseWorker):
    """Simulates a rogue or broken worker attempting an unauthorized mutation."""

    def execute(
        self,
        assignment_id: str,
        step: TaskStepDefinition,
        token: CapabilityToken,
        fencing_token: int,
        input_artifacts: tuple[ArtifactRecord, ...] = (),
        repo_dir: Path | None = None,
    ) -> WorkerExecutionResult:
        # Attempt to mutate an unauthorized file (e.g. /etc/shadow or unauthorized config)
        unauthorized_target = "config/production_secrets.json"
        ScopeGuard.check_mutation_path(token, unauthorized_target)
        raise RuntimeError("ScopeGuard failed to intercept out-of-scope mutation!")


class ReviewerWorker(BaseWorker):
    """Simulates an independent code reviewer specialist (e.g. specialized reviewer model)."""

    def __init__(
        self,
        worker_id: str = "worker-b65-1",
        profile_hash: str = "hash-b65-1",
        artifact_store: ArtifactStore | None = None,
        custom_findings: tuple[ReviewFinding, ...] | None = None,
        force_disposition: ReviewDisposition | None = None,
    ) -> None:
        super().__init__(worker_id, profile_hash, artifact_store)  # type: ignore
        self.custom_findings = custom_findings
        self.force_disposition = force_disposition

    def execute(
        self,
        assignment_id: str,
        step: TaskStepDefinition,
        token: CapabilityToken,
        fencing_token: int,
        input_artifacts: tuple[ArtifactRecord, ...] = (),
        repo_dir: Path | None = None,
    ) -> WorkerExecutionResult:
        ScopeGuard.verify_token(token)
        ScopeGuard.check_tool_execution(token, "read_file")

        # Find candidate patch from inputs
        candidate_patch: ArtifactRecord | None = None
        for art in input_artifacts:
            if art.artifact_type == ArtifactType.PATCH:
                candidate_patch = art
                break

        if not candidate_patch:
            candidate_patch = input_artifacts[-1] if input_artifacts else None

        target_hash = candidate_patch.artifact_hash if candidate_patch else "none"
        patch_text = ""
        if candidate_patch:
            patch_text = self.artifact_store.get(candidate_patch.artifact_hash).decode("utf-8", errors="replace")

        findings: list[ReviewFinding] = []
        disposition = self.force_disposition

        if self.custom_findings is not None:
            findings = list(self.custom_findings)
            if disposition is None:
                has_defect = any(f.severity in (FindingSeverity.CRITICAL, FindingSeverity.MAJOR) for f in findings)
                disposition = ReviewDisposition.RECOMMEND_REVISE if has_defect else ReviewDisposition.RECOMMEND_ACCEPT
        elif disposition is None:
            # Automatic heuristic inspection on added diff lines only
            added_lines = [
                line[1:]
                for line in patch_text.splitlines()
                if line.startswith("+") and not line.startswith("+++")
            ]
            added_text = "\n".join(added_lines)

            if "this is not valid python syntax" in added_text or "syntax_error" in added_text:
                findings.append(
                    ReviewFinding(
                        finding_id=f"find-{uuid.uuid4().hex[:8]}",
                        severity=FindingSeverity.CRITICAL,
                        file_path=step.target_paths[0] if step.target_paths else "unknown",
                        line_number=10,
                        description="Syntax defect detected in patch: invalid python syntax statement",
                        suggested_action="Remove invalid syntax statement and implement correct error check",
                    )
                )
                disposition = ReviewDisposition.RECOMMEND_REVISE
            elif "return 999999" in added_text or "999999.0" in added_text:
                findings.append(
                    ReviewFinding(
                        finding_id=f"find-{uuid.uuid4().hex[:8]}",
                        severity=FindingSeverity.MAJOR,
                        file_path=step.target_paths[0] if step.target_paths else "unknown",
                        line_number=11,
                        description="Incorrect defect handling: returns arbitrary dummy number instead of expected ValueError",
                        suggested_action="Raise ValueError('Denominator cannot be zero') when denominator is 0",
                    )
                )
                disposition = ReviewDisposition.RECOMMEND_REVISE
            elif "subtotal + discount" in added_text:
                findings.append(
                    ReviewFinding(
                        finding_id=f"find-{uuid.uuid4().hex[:8]}",
                        severity=FindingSeverity.CRITICAL,
                        file_path="src/processor.py",
                        line_number=12,
                        description="Subtotal adds discount instead of subtracting it",
                        suggested_action="Change 'subtotal + discount' to 'subtotal - discount'",
                    )
                )
                disposition = ReviewDisposition.RECOMMEND_REVISE
            else:
                disposition = ReviewDisposition.RECOMMEND_ACCEPT

        summary = (
            f"Review completed with {len(findings)} findings. Recommendation: {disposition}"
            if findings
            else "Clean review: patch satisfies acceptance criteria without defect findings."
        )

        report = ReviewReport(
            report_id=f"rev-{uuid.uuid4().hex[:12]}",
            target_artifact_hash=target_hash,
            reviewer_worker_id=self.worker_id,
            disposition=disposition or ReviewDisposition.RECOMMEND_ACCEPT,
            findings=tuple(findings),
            summary=summary,
            is_advisory=True,
        )

        parent_hashes = (candidate_patch.artifact_hash,) if candidate_patch else ()
        artifact = self.artifact_store.put(
            content=canonical_json(report.to_dict()),
            artifact_type=ArtifactType.REVIEW_REPORT,
            work_order_id=token.work_order_id,
            work_order_version=token.work_order_version,
            step_id=step.step_id,
            producing_worker_id=self.worker_id,
            producing_profile_hash=self.profile_hash,
            capability_token_id=token.token_id,
            parent_artifact_hashes=parent_hashes,
            metadata={
                "disposition": str(disposition or ReviewDisposition.RECOMMEND_ACCEPT),
                "findings_count": len(findings),
                "target_artifact_hash": target_hash,
                "is_advisory": True,
            },
        )

        return WorkerExecutionResult(
            worker_id=self.worker_id,
            assignment_id=assignment_id,
            fencing_token=fencing_token,
            output_artifact=artifact,
            logs=f"Independent review completed: {disposition} ({len(findings)} findings)",
            exit_code=0,
        )


class RepairWorker(BaseWorker):
    """Simulates a repair worker that inspects failure diagnostics or review findings and generates a corrected patch."""

    def __init__(
        self,
        worker_id: str = "worker-b65-0",
        profile_hash: str = "hash-b65-0",
        artifact_store: ArtifactStore | None = None,
        repaired_patch: str | None = None,
    ) -> None:
        super().__init__(worker_id, profile_hash, artifact_store)  # type: ignore
        self.repaired_patch = repaired_patch

    def execute(
        self,
        assignment_id: str,
        step: TaskStepDefinition,
        token: CapabilityToken,
        fencing_token: int,
        input_artifacts: tuple[ArtifactRecord, ...] = (),
        repo_dir: Path | None = None,
    ) -> WorkerExecutionResult:
        ScopeGuard.verify_token(token)
        ScopeGuard.check_tool_execution(token, "write_patch")

        for path in step.target_paths:
            ScopeGuard.check_mutation_path(token, path)

        patch = self.repaired_patch or (
            "diff --git a/src/calculator/math_utils.py b/src/calculator/math_utils.py\n"
            "--- a/src/calculator/math_utils.py\n"
            "+++ b/src/calculator/math_utils.py\n"
            "@@ -10,2 +10,4 @@\n"
            " def calculate_ratio(a: float, b: float) -> float:\n"
            "+    if b == 0:\n"
            "+        raise ValueError('Denominator cannot be zero')\n"
            "     return a / b\n"
        )

        parent_hashes = tuple(a.artifact_hash for a in input_artifacts)
        artifact = self.artifact_store.put(
            content=patch,
            artifact_type=step.output_artifact_type,
            work_order_id=token.work_order_id,
            work_order_version=token.work_order_version,
            step_id=step.step_id,
            producing_worker_id=self.worker_id,
            producing_profile_hash=self.profile_hash,
            capability_token_id=token.token_id,
            parent_artifact_hashes=parent_hashes,
            metadata={"status": "repaired_successfully"},
        )

        return WorkerExecutionResult(
            worker_id=self.worker_id,
            assignment_id=assignment_id,
            fencing_token=fencing_token,
            output_artifact=artifact,
            logs=f"Repaired patch generated successfully for {step.step_id}",
            exit_code=0,
        )


class MultiFileWorker(BaseWorker):
    """Worker specialized for multi-file implementation tasks."""

    def __init__(
        self,
        worker_id: str = "worker-multifile",
        profile_hash: str = "hash-multifile",
        artifact_store: ArtifactStore | None = None,
        patch_content: str | None = None,
    ) -> None:
        super().__init__(worker_id, profile_hash, artifact_store)  # type: ignore
        self.patch_content = patch_content

    def execute(
        self,
        assignment_id: str,
        step: TaskStepDefinition,
        token: CapabilityToken,
        fencing_token: int,
        input_artifacts: tuple[ArtifactRecord, ...] = (),
        repo_dir: Path | None = None,
    ) -> WorkerExecutionResult:
        ScopeGuard.verify_token(token)
        ScopeGuard.check_tool_execution(token, "write_patch")
        for path in step.target_paths:
            ScopeGuard.check_mutation_path(token, path)

        patch = self.patch_content or (
            "diff --git a/src/processor.py b/src/processor.py\n"
            "--- a/src/processor.py\n"
            "+++ b/src/processor.py\n"
            "@@ -11,2 +11,2 @@\n"
            "-    discounted_subtotal = subtotal + discount\n"
            "+    discounted_subtotal = subtotal - discount\n"
        )
        parent_hashes = tuple(a.artifact_hash for a in input_artifacts)
        artifact = self.artifact_store.put(
            content=patch,
            artifact_type=step.output_artifact_type,
            work_order_id=token.work_order_id,
            work_order_version=token.work_order_version,
            step_id=step.step_id,
            producing_worker_id=self.worker_id,
            producing_profile_hash=self.profile_hash,
            capability_token_id=token.token_id,
            parent_artifact_hashes=parent_hashes,
            metadata={"status": "multi_file_patch_synthesized"},
        )
        return WorkerExecutionResult(
            worker_id=self.worker_id,
            assignment_id=assignment_id,
            fencing_token=fencing_token,
            output_artifact=artifact,
            logs="Multi-file patch synthesized.",
            exit_code=0,
        )


class TestDevWorker(BaseWorker):
    """Worker specialized for test development."""
    __test__ = False

    def __init__(
        self,
        worker_id: str = "worker-testdev",
        profile_hash: str = "hash-testdev",
        artifact_store: ArtifactStore | None = None,
        patch_content: str | None = None,
    ) -> None:
        super().__init__(worker_id, profile_hash, artifact_store)  # type: ignore
        self.patch_content = patch_content

    def execute(
        self,
        assignment_id: str,
        step: TaskStepDefinition,
        token: CapabilityToken,
        fencing_token: int,
        input_artifacts: tuple[ArtifactRecord, ...] = (),
        repo_dir: Path | None = None,
    ) -> WorkerExecutionResult:
        ScopeGuard.verify_token(token)
        ScopeGuard.check_tool_execution(token, "write_patch")
        for path in step.target_paths:
            ScopeGuard.check_mutation_path(token, path)

        patch = self.patch_content or (
            "--- a/tests/test_token_utils.py\n"
            "+++ b/tests/test_token_utils.py\n"
            "@@ -0,0 +1,22 @@\n"
            "+from src.token_utils import validate_bearer_token\n"
            "+\n"
            "+\n"
            "+def test_valid_token():\n"
            "+    assert validate_bearer_token('Bearer abc123xyz') == 'abc123xyz'\n"
            "+\n"
            "+\n"
            "+def test_invalid_prefix():\n"
            "+    assert validate_bearer_token('Basic abc123xyz') is None\n"
            "+    assert validate_bearer_token('bearer abc123xyz') is None\n"
            "+\n"
            "+\n"
            "+def test_empty_or_whitespace():\n"
            "+    assert validate_bearer_token(None) is None\n"
            "+    assert validate_bearer_token('') is None\n"
            "+    assert validate_bearer_token('Bearer ') is None\n"
            "+    assert validate_bearer_token('Bearer    ') is None\n"
            "+\n"
            "+\n"
            "+def test_internal_whitespace():\n"
            "+    assert validate_bearer_token('Bearer abc 123') is None\n"
            "+    assert validate_bearer_token('Bearer abc\\n123') is None\n"
        )
        parent_hashes = tuple(a.artifact_hash for a in input_artifacts)
        artifact = self.artifact_store.put(
            content=patch,
            artifact_type=step.output_artifact_type,
            work_order_id=token.work_order_id,
            work_order_version=token.work_order_version,
            step_id=step.step_id,
            producing_worker_id=self.worker_id,
            producing_profile_hash=self.profile_hash,
            capability_token_id=token.token_id,
            parent_artifact_hashes=parent_hashes,
            metadata={"status": "test_suite_authored"},
        )
        return WorkerExecutionResult(
            worker_id=self.worker_id,
            assignment_id=assignment_id,
            fencing_token=fencing_token,
            output_artifact=artifact,
            logs="Test suite authored successfully.",
            exit_code=0,
        )


class RefactorWorker(BaseWorker):
    """Worker specialized for code maintainability and deduplication."""

    def __init__(
        self,
        worker_id: str = "worker-refactor",
        profile_hash: str = "hash-refactor",
        artifact_store: ArtifactStore | None = None,
        patch_content: str | None = None,
    ) -> None:
        super().__init__(worker_id, profile_hash, artifact_store)  # type: ignore
        self.patch_content = patch_content

    def execute(
        self,
        assignment_id: str,
        step: TaskStepDefinition,
        token: CapabilityToken,
        fencing_token: int,
        input_artifacts: tuple[ArtifactRecord, ...] = (),
        repo_dir: Path | None = None,
    ) -> WorkerExecutionResult:
        ScopeGuard.verify_token(token)
        ScopeGuard.check_tool_execution(token, "write_patch")
        for path in step.target_paths:
            ScopeGuard.check_mutation_path(token, path)

        patch = self.patch_content or (
            "--- a/src/currency_formatters.py\n"
            "+++ b/src/currency_formatters.py\n"
            "@@ -1,31 +1,25 @@\n"
            ' """Currency formatting utilities with duplicate boilerplate."""\n'
            "+\n"
            "+\n"
            "+def _format_currency(amount: float, symbol: str) -> str:\n"
            "+    if not isinstance(amount, (int, float)) or isinstance(amount, bool):\n"
            '+        raise TypeError("amount must be a numeric value")\n'
            "+    if amount < 0:\n"
            '+        raise ValueError("negative amount not supported")\n'
            "+    rounded = round(float(amount), 2)\n"
            '+    return f"{symbol}{rounded:,.2f}"\n'
            " \n"
            " \n"
            " def format_usd(amount: float) -> str:\n"
            '     """Format amount as USD."""\n'
            "-    if not isinstance(amount, (int, float)):\n"
            '-        raise TypeError("amount must be a numeric value")\n'
            "-    if amount < 0:\n"
            '-        raise ValueError("negative amount not supported")\n'
            "-    rounded = round(float(amount), 2)\n"
            '-    return f"${rounded:,.2f}"\n'
            '+    return _format_currency(amount, "$")\n'
            " \n"
            " \n"
            " def format_eur(amount: float) -> str:\n"
            '     """Format amount as EUR."""\n'
            "-    if not isinstance(amount, (int, float)):\n"
            '-        raise TypeError("amount must be a numeric value")\n'
            "-    if amount < 0:\n"
            '-        raise ValueError("negative amount not supported")\n'
            "-    rounded = round(float(amount), 2)\n"
            '-    return f"€{rounded:,.2f}"\n'
            '+    return _format_currency(amount, "€")\n'
            " \n"
            " \n"
            " def format_gbp(amount: float) -> str:\n"
            '     """Format amount as GBP."""\n'
            "-    if not isinstance(amount, (int, float)):\n"
            '-        raise TypeError("amount must be a numeric value")\n'
            "-    if amount < 0:\n"
            '-        raise ValueError("negative amount not supported")\n'
            "-    rounded = round(float(amount), 2)\n"
            '-    return f"£{rounded:,.2f}"\n'
            '+    return _format_currency(amount, "£")\n'
        )
        parent_hashes = tuple(a.artifact_hash for a in input_artifacts)
        artifact = self.artifact_store.put(
            content=patch,
            artifact_type=step.output_artifact_type,
            work_order_id=token.work_order_id,
            work_order_version=token.work_order_version,
            step_id=step.step_id,
            producing_worker_id=self.worker_id,
            producing_profile_hash=self.profile_hash,
            capability_token_id=token.token_id,
            parent_artifact_hashes=parent_hashes,
            metadata={"status": "refactored_and_deduplicated"},
        )
        return WorkerExecutionResult(
            worker_id=self.worker_id,
            assignment_id=assignment_id,
            fencing_token=fencing_token,
            output_artifact=artifact,
            logs="Maintainability refactoring completed.",
            exit_code=0,
        )


class IterativeWorker(BaseWorker):
    """Simulates a worker that produces different patches on subsequent attempts (e.g. initial attempt then fix)."""

    def __init__(
        self,
        worker_id: str = "worker-b65-0",
        profile_hash: str = "hash-b65-0",
        artifact_store: ArtifactStore | None = None,
        patches: list[str] | tuple[str, ...] = (),
    ) -> None:
        super().__init__(worker_id, profile_hash, artifact_store)  # type: ignore
        self.patches = list(patches)
        self.call_count = 0

    def execute(
        self,
        assignment_id: str,
        step: TaskStepDefinition,
        token: CapabilityToken,
        fencing_token: int,
        input_artifacts: tuple[ArtifactRecord, ...] = (),
        repo_dir: Path | None = None,
    ) -> WorkerExecutionResult:
        ScopeGuard.verify_token(token)
        ScopeGuard.check_tool_execution(token, "write_patch")
        for path in step.target_paths:
            ScopeGuard.check_mutation_path(token, path)

        patch = self.patches[min(self.call_count, len(self.patches) - 1)]
        self.call_count += 1

        parent_hashes = tuple(a.artifact_hash for a in input_artifacts)
        artifact = self.artifact_store.put(
            content=patch,
            artifact_type=step.output_artifact_type,
            work_order_id=token.work_order_id,
            work_order_version=token.work_order_version,
            step_id=step.step_id,
            producing_worker_id=self.worker_id,
            producing_profile_hash=self.profile_hash,
            capability_token_id=token.token_id,
            parent_artifact_hashes=parent_hashes,
            metadata={"call_count": self.call_count},
        )
        return WorkerExecutionResult(
            worker_id=self.worker_id,
            assignment_id=assignment_id,
            fencing_token=fencing_token,
            output_artifact=artifact,
            logs=f"Patch iteration {self.call_count} generated.",
            exit_code=0,
        )
