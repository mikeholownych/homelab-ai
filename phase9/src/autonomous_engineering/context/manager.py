"""
Autonomous Engineering System - Phase 9
Workstream H: Context Provenance and Isolation

Assembles isolated, provenance-tracked context buffers from authorized repository sources.
Sanitizes untrusted inputs, strips prompt injection attempts, detects stale git revisions,
and guarantees cross-work-order data isolation.
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set


class RetrievalStrategy(str, Enum):
    EXACT_FILE = "EXACT_FILE"
    AST_SYMBOL = "AST_SYMBOL"
    GIT_DIFF = "GIT_DIFF"
    GIT_LOG = "GIT_LOG"
    SUMMARY = "SUMMARY"


class ContextSecurityError(Exception):
    """Base exception for context isolation and security violations."""


class PromptInjectionAttemptError(ContextSecurityError):
    """Raised when malicious prompt injection or authority alteration is detected in context."""


class StaleContextError(ContextSecurityError):
    """Raised when context was assembled from a superseded or mismatched git revision."""


class CrossWorkOrderLeakageError(ContextSecurityError):
    """Raised when an attempt is made to import or reuse context from another work order."""


@dataclass(frozen=True)
class ContextItem:
    """A discrete, provenance-tracked piece of context."""
    source_path: str
    content_hash: str
    retrieval_strategy: RetrievalStrategy
    byte_range: Optional[tuple[int, int]]
    token_count_estimate: int
    raw_content: str
    sanitized_content: str
    is_authoritative: bool


@dataclass(frozen=True)
class AssembledContext:
    """
    Authoritative assembled context payload with cryptographic provenance tracking.
    """
    context_id: str
    work_order_id: str
    repository_id: str
    baseline_commit: str
    construction_version: str
    items: List[ContextItem]
    total_tokens_estimate: int
    omitted_items_count: int
    provenance_digest: str
    assembled_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ContextConstructionManager:
    """
    Assembles, sanitizes, and audits context for specialized agents.
    Defends against prompt injection and cross-work-order leakage.
    """

    # Disallowed prompt injection patterns attempting to override instructions or system role
    INJECTION_PATTERNS = [
        re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
        re.compile(r"disregard\s+(all\s+)?prior\s+rules", re.IGNORECASE),
        re.compile(r"you\s+are\s+now\s+an\s+unrestricted", re.IGNORECASE),
        re.compile(r"system\s*:\s*you\s+have\s+full\s+root", re.IGNORECASE),
        re.compile(r"override_authority\s*=\s*true", re.IGNORECASE),
        re.compile(r"<\|im_start\|>\s*system", re.IGNORECASE),
        re.compile(r"grant_all_permissions", re.IGNORECASE),
    ]

    def __init__(self, construction_version: str = "1.0.0") -> None:
        self.construction_version = construction_version
        self._contexts: Dict[str, AssembledContext] = {}

    def assemble_context(
        self,
        work_order_id: str,
        repository_id: str,
        baseline_commit: str,
        target_files: List[Dict[str, Any]],  # [{"path": str, "content": str, "strategy": str}]
        token_budget: int = 32768,
        external_context: Optional[str] = None,
    ) -> AssembledContext:
        """
        Assembles context items from repository files, enforcing sanitization,
        budget constraints, and tracking exact provenance digests.
        """
        items: List[ContextItem] = []
        running_token_estimate = 0
        omitted = 0

        # Process repository files
        for entry in target_files:
            raw_path = entry["path"]
            raw_content = entry["content"]
            strategy_str = entry.get("strategy", RetrievalStrategy.EXACT_FILE.value)
            strategy = RetrievalStrategy(strategy_str)

            # 1. Detect and sanitize prompt injections
            sanitized = self._sanitize_and_audit(raw_content, raw_path)

            # 2. Token estimation (~4 chars per token)
            token_est = max(1, len(sanitized) // 4)

            # 3. Check token budget
            if running_token_estimate + token_est > token_budget:
                omitted += 1
                continue

            content_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
            item = ContextItem(
                source_path=raw_path,
                content_hash=content_hash,
                retrieval_strategy=strategy,
                byte_range=None,
                token_count_estimate=token_est,
                raw_content=raw_content,
                sanitized_content=sanitized,
                is_authoritative=True,
            )
            items.append(item)
            running_token_estimate += token_est

        # Process external instructions / issue text if present
        if external_context:
            sanitized_ext = self._sanitize_and_audit(external_context, "external_instructions")
            ext_token_est = max(1, len(sanitized_ext) // 4)
            if running_token_estimate + ext_token_est <= token_budget:
                ext_hash = hashlib.sha256(external_context.encode("utf-8")).hexdigest()
                items.append(
                    ContextItem(
                        source_path="work_order_description",
                        content_hash=ext_hash,
                        retrieval_strategy=RetrievalStrategy.SUMMARY,
                        byte_range=None,
                        token_count_estimate=ext_token_est,
                        raw_content=external_context,
                        sanitized_content=sanitized_ext,
                        is_authoritative=False,
                    )
                )
                running_token_estimate += ext_token_est
            else:
                omitted += 1

        # Calculate overall provenance digest
        provenance_string = f"{repository_id}:{baseline_commit}:" + ",".join(
            f"{i.source_path}:{i.content_hash}" for i in items
        )
        provenance_digest = hashlib.sha256(provenance_string.encode("utf-8")).hexdigest()

        context_id = f"ctx-{work_order_id}-{provenance_digest[:12]}"
        assembled = AssembledContext(
            context_id=context_id,
            work_order_id=work_order_id,
            repository_id=repository_id,
            baseline_commit=baseline_commit,
            construction_version=self.construction_version,
            items=items,
            total_tokens_estimate=running_token_estimate,
            omitted_items_count=omitted,
            provenance_digest=provenance_digest,
        )

        self._contexts[context_id] = assembled
        return assembled

    def verify_context_freshness(
        self,
        context: AssembledContext,
        current_repo_commit: str,
    ) -> None:
        """
        Validates that the context has not become stale due to an external repository mutation.
        """
        if context.baseline_commit != current_repo_commit:
            raise StaleContextError(
                f"Context {context.context_id} was assembled at commit '{context.baseline_commit}', but current repo HEAD is '{current_repo_commit}'"
            )

    def validate_task_isolation(
        self,
        context: AssembledContext,
        target_work_order_id: str,
    ) -> None:
        """
        Guarantees that context from Work Order A cannot leak into Work Order B.
        """
        if context.work_order_id != target_work_order_id:
            raise CrossWorkOrderLeakageError(
                f"Attempted to bind context from '{context.work_order_id}' to active task '{target_work_order_id}'"
            )

    def _sanitize_and_audit(self, text: str, source_identifier: str) -> str:
        """
        Scans for prompt injection attacks and sanitizes suspicious patterns.
        Raises PromptInjectionAttemptError on blatant attacks attempting authority takeover.
        """
        for pattern in self.INJECTION_PATTERNS:
            if pattern.search(text):
                raise PromptInjectionAttemptError(
                    f"Prompt injection pattern detected in '{source_identifier}': matched {pattern.pattern}"
                )

        # Strip special chat template control tokens that could confuse tokenizer
        sanitized = text.replace("<|im_start|>", "[CONTROL_TOKEN_FILTERED]")
        sanitized = sanitized.replace("<|im_end|>", "[CONTROL_TOKEN_FILTERED]")
        return sanitized
