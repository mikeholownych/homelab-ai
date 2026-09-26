"""Simulated Workers and Tool Execution Adapters."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autonomous_engineering.artifacts.models import ArtifactRecord
from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.authority.guard import ScopeGuard, ScopeViolationError
from autonomous_engineering.authority.tokens import CapabilityToken
from autonomous_engineering.core.types import ArtifactType
from autonomous_engineering.planning.models import TaskStepDefinition


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
