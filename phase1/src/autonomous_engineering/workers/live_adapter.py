"""Controlled Live Model Worker Adapter for OpenAI-Compatible Gateway."""
from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any
import urllib.error
import urllib.request
import uuid

from autonomous_engineering.artifacts.models import ArtifactRecord
from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.authority.guard import ScopeGuard, ScopeViolationError
from autonomous_engineering.authority.tokens import CapabilityToken
from autonomous_engineering.containment.bwrap import BwrapSandbox
from autonomous_engineering.core.types import ArtifactType, FailureClass
from autonomous_engineering.planning.models import TaskStepDefinition
from autonomous_engineering.workers.simulated import BaseWorker, WorkerExecutionResult


class LiveWorkerError(RuntimeError):
    def __init__(self, message: str, failure_class: FailureClass = FailureClass.MALFORMED_OUTPUT) -> None:
        super().__init__(message)
        self.failure_class = failure_class


class LiveModelWorker(BaseWorker):
    """Untrusted execution adapter communicating with live model inference gateway.

    Invariants:
    - Does NOT own work order state, authority, or acceptance criteria.
    - Captures raw provider output, token counts, and correlated request IDs.
    - All file modifications applied to worktree are contained within BwrapSandbox.
    - Model response is treated as an advisory handoff, never an authoritative report.
    """

    def __init__(
        self,
        worker_id: str,
        profile_hash: str,
        artifact_store: ArtifactStore,
        endpoint_url: str = "http://127.0.0.1:18010/v1/chat/completions",
        token_path: Path | str = "/home/mike/.config/opencode/t5820-client-token",
        model_name: str = "engineering/b0",
        sandbox: BwrapSandbox | None = None,
    ) -> None:
        super().__init__(worker_id, profile_hash, artifact_store)
        self.endpoint_url = endpoint_url
        self.token_path = Path(token_path)
        self.model_name = model_name
        self.sandbox = sandbox

    def _read_auth_token(self) -> str:
        if not self.token_path.exists():
            raise LiveWorkerError(
                f"Client token file not found at {self.token_path}",
                FailureClass.CAPABILITY_EXPIRED_OR_REVOKED,
            )
        return self.token_path.read_text(encoding="utf-8").strip()

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

        if not repo_dir or not repo_dir.exists():
            raise LiveWorkerError(f"Target repository not found at {repo_dir}")

        # Construct prompt carrying exact authorized scope and target source file
        target_rel_path = step.target_paths[0].lstrip("/")
        target_file = repo_dir / target_rel_path
        file_content = target_file.read_text(encoding="utf-8") if target_file.exists() else ""

        system_prompt = (
            "You are an autonomous engineering assistant. Output ONLY a unified git diff patch to resolve "
            "the requested defect. The diff must modify ONLY the authorized file path.\n"
            "Do not include conversational filler or explanations. Format the patch inside a ```diff codeblock."
        )
        user_prompt = (
            f"Objective: {step.description}\n"
            f"Authorized Path: {target_rel_path}\n"
            f"Current File Content:\n"
            f"```python\n{file_content}\n```\n"
            "Provide the minimal correct unified diff patch to satisfy the requirement."
        )

        request_id = f"req-{uuid.uuid4().hex[:12]}"
        auth_token = self._read_auth_token()

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.0,
            "max_tokens": 1024,
        }

        req = urllib.request.Request(
            self.endpoint_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {auth_token}",
                "Content-Type": "application/json",
                "X-Request-ID": request_id,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=60.0) as resp:
                raw_bytes = resp.read()
                resp_json = json.loads(raw_bytes.decode("utf-8"))
        except urllib.error.HTTPError as err:
            err_body = err.read().decode("utf-8", errors="replace")
            raise LiveWorkerError(
                f"Gateway returned HTTP {err.code}: {err_body}",
                FailureClass.ENVIRONMENT_ERROR,
            ) from err
        except urllib.error.URLError as err:
            raise LiveWorkerError(
                f"Failed to connect to live gateway at {self.endpoint_url}: {err.reason}",
                FailureClass.ENVIRONMENT_ERROR,
            ) from err

        choice = resp_json.get("choices", [{}])[0]
        message = choice.get("message", {})
        raw_content = message.get("content", "")
        tool_calls = message.get("tool_calls", [])
        usage = resp_json.get("usage", {})

        # Extract patch from response
        patch_text = self._extract_patch(raw_content, target_rel_path)
        if not patch_text:
            raise LiveWorkerError(
                f"Model response did not contain a valid unified diff patch: {raw_content[:200]}",
                FailureClass.MALFORMED_OUTPUT,
            )

        # Store patch in immutable ArtifactStore
        parent_hashes = tuple(a.artifact_hash for a in input_artifacts)
        artifact = self.artifact_store.put(
            content=patch_text,
            artifact_type=ArtifactType.PATCH,
            work_order_id=token.work_order_id,
            work_order_version=token.work_order_version,
            step_id=step.step_id,
            producing_worker_id=self.worker_id,
            producing_profile_hash=self.profile_hash,
            capability_token_id=token.token_id,
            parent_artifact_hashes=parent_hashes,
            metadata={
                "request_id": request_id,
                "model_name": self.model_name,
                "endpoint": self.endpoint_url,
                "tokens_prompt": usage.get("prompt_tokens"),
                "tokens_completion": usage.get("completion_tokens"),
                "finish_reason": choice.get("finish_reason"),
                "tool_calls_count": len(tool_calls),
                "raw_response_snippet": raw_content[:300],
            },
        )

        return WorkerExecutionResult(
            worker_id=self.worker_id,
            assignment_id=assignment_id,
            fencing_token=fencing_token,
            output_artifact=artifact,
            logs=f"Live model {self.model_name} generated patch under request {request_id}",
            exit_code=0,
        )

    def _extract_patch(self, content: str, expected_path: str) -> str | None:
        """Extract diff text from markdown block or raw text."""
        # Try extracting fenced diff block
        diff_match = re.search(r"```(?:diff)?\n([\s\S]*?)\n```", content)
        if diff_match:
            candidate = diff_match.group(1).strip()
            if "---" in candidate and "+++" in candidate:
                return candidate + "\n"

        # Try raw diff text
        if "--- a/" in content or "diff --git" in content:
            lines = []
            capturing = False
            for line in content.splitlines():
                if line.startswith("diff --git") or line.startswith("--- "):
                    capturing = True
                if capturing:
                    lines.append(line)
            if lines:
                return "\n".join(lines) + "\n"

        return None
