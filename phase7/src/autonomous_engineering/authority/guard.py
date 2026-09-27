"""ScopeGuard: Runtime containment and authority enforcement."""
from __future__ import annotations

import fnmatch
from pathlib import PurePosixPath
from typing import Any

from autonomous_engineering.authority.tokens import CapabilityToken
from autonomous_engineering.core.types import FailureClass


class ScopeViolationError(RuntimeError):
    def __init__(self, message: str, failure_class: FailureClass) -> None:
        super().__init__(message)
        self.failure_class = failure_class


class ScopeGuard:
    """Enforces capability token boundaries on all worker operations."""

    @staticmethod
    def verify_token(token: CapabilityToken | None, now_iso: str | None = None) -> None:
        """Verify token presence and cryptographic validity."""
        if token is None:
            raise ScopeViolationError(
                "Execution attempted without a valid CapabilityToken",
                FailureClass.CAPABILITY_EXPIRED_OR_REVOKED,
            )
        if not token.is_valid(now_iso):
            raise ScopeViolationError(
                f"CapabilityToken {token.token_id} is expired, revoked, or tampered",
                FailureClass.CAPABILITY_EXPIRED_OR_REVOKED,
            )

    @classmethod
    def check_mutation_path(
        cls,
        token: CapabilityToken,
        target_path: str,
        now_iso: str | None = None,
    ) -> None:
        """Verify that a path being modified matches authorized path globs in token."""
        cls.verify_token(token, now_iso)

        normalized = PurePosixPath(target_path).as_posix()
        for pattern in token.authorized_paths:
            # Match directly or as glob
            if fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(
                normalized, pattern.lstrip("/")
            ):
                return

        raise ScopeViolationError(
            f"Unauthorized mutation: path '{target_path}' outside authorized scope {token.authorized_paths}",
            FailureClass.SCOPE_VIOLATION,
        )

    @classmethod
    def check_tool_execution(
        cls,
        token: CapabilityToken,
        tool_name: str,
        now_iso: str | None = None,
    ) -> None:
        """Verify that a tool invocation is authorized by the token."""
        cls.verify_token(token, now_iso)

        if tool_name not in token.authorized_tools:
            raise ScopeViolationError(
                f"Unauthorized tool invocation: '{tool_name}' not in authorized tools {token.authorized_tools}",
                FailureClass.SCOPE_VIOLATION,
            )
