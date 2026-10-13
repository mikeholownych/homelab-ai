"""Inline Data Loss Prevention (DLP) and prompt guardrails.

Inspects incoming prompts and messages before upstream inference dispatch:
- High-entropy secret detection: AWS credentials, GitHub tokens, OpenAI/Generic API keys, private keys.
- Prompt injection & jailbreak heuristics: System instruction overrides, developer mode tricks.
- Actions: 'reject' (raises GuardrailViolation, returning HTTP 400), 'redact' (replaces secrets in-place),
  or 'flag' (attaches audit alert to evidence).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Sequence


class GuardrailViolation(Exception):
    """Raised when a request violates security guardrail policies under 'reject' action."""

    def __init__(self, message: str, violation_type: str, matches: list[str] | None = None) -> None:
        super().__init__(message)
        self.violation_type = violation_type
        self.matches = matches or []


@dataclass
class GuardrailResult:
    rejected: bool = False
    redacted: bool = False
    flagged: bool = False
    violation_type: str | None = None
    reason: str | None = None
    detected_patterns: list[str] = field(default_factory=list)
    sanitized_request: dict[str, Any] | None = None


# Pre-compiled high-precision secret detection patterns
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("aws_secret_key_assignment", re.compile(r"(?i)\baws[_\-]?secret[_\-]?access[_\-]?key\b\s*[:=]\s*['\"]?([A-Za-z0-9/+=]{40})['\"]?")),
    ("github_pat", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,255}\b|\bgithub_pat_[A-Za-z0-9_]{82}\b")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("api_key", re.compile(r"\b(?:sk|pk)[-_][a-zA-Z0-9_\-]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[0-9a-zA-Z\-]{10,}\b")),
)

# Pre-compiled prompt injection heuristics
INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("override_instructions", re.compile(r"(?i)\b(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|prior)\s+(?:instructions|prompts|directions|rules)\b")),
    ("developer_mode", re.compile(r"(?i)\b(?:you\s+are\s+now\s+in\s+developer\s+mode|enable\s+dan\s+mode)\b")),
    ("system_override", re.compile(r"(?i)\b(?:system\s+override\s*:\s*disable\s+safety|bypass\s+all\s+guardrails)\b")),
)


class GuardrailScanner:
    """Enterprise inline DLP scanner for secrets and prompt injections."""

    def __init__(
        self,
        *,
        action: str = "reject",
        detect_secrets: bool = True,
        detect_injection: bool = True,
        redaction_mask: str = "[REDACTED_SECRET]",
        custom_patterns: Sequence[tuple[str, re.Pattern[str]]] = (),
    ) -> None:
        if action not in ("reject", "redact", "flag", "none"):
            raise ValueError(f"unknown guardrail action {action!r}")
        self.action = action
        self.detect_secrets = detect_secrets
        self.detect_injection = detect_injection
        self.redaction_mask = redaction_mask
        self.custom_patterns = tuple(custom_patterns)

    def _extract_texts(self, data: Any) -> list[str]:
        texts: list[str] = []
        if isinstance(data, str):
            texts.append(data)
        elif isinstance(data, dict):
            for k, v in data.items():
                if k in ("content", "prompt", "text") and isinstance(v, str):
                    texts.append(v)
                elif isinstance(v, (dict, list)):
                    texts.extend(self._extract_texts(v))
        elif isinstance(data, list):
            for item in data:
                texts.extend(self._extract_texts(item))
        return texts

    def _sanitize_data(self, data: Any, patterns: list[re.Pattern[str]]) -> Any:
        if isinstance(data, str):
            res = data
            for p in patterns:
                res = p.sub(self.redaction_mask, res)
            return res
        if isinstance(data, dict):
            return {k: self._sanitize_data(v, patterns) for k, v in data.items()}
        if isinstance(data, list):
            return [self._sanitize_data(item, patterns) for item in data]
        return data

    def inspect(self, request: dict[str, Any]) -> GuardrailResult:
        if self.action == "none":
            return GuardrailResult()

        texts = self._extract_texts(request.get("messages") or request.get("prompt") or [])
        matched_secrets: list[str] = []
        matched_injections: list[str] = []
        patterns_to_redact: list[re.Pattern[str]] = []

        if self.detect_secrets:
            for name, pattern in SECRET_PATTERNS:
                for text in texts:
                    if pattern.search(text):
                        matched_secrets.append(name)
                        patterns_to_redact.append(pattern)
                        break

        for name, pattern in self.custom_patterns:
            for text in texts:
                if pattern.search(text):
                    matched_secrets.append(name)
                    patterns_to_redact.append(pattern)
                    break

        if self.detect_injection:
            for name, pattern in INJECTION_PATTERNS:
                for text in texts:
                    if pattern.search(text):
                        matched_injections.append(name)
                        break

        all_detected = matched_secrets + matched_injections
        if not all_detected:
            return GuardrailResult()

        # Determine violation type and reason
        if matched_secrets:
            violation_type = "secret_detected"
            reason = f"High-entropy secret pattern detected: {matched_secrets[0]}"
        else:
            violation_type = "prompt_injection"
            reason = f"Prompt injection heuristic triggered: {matched_injections[0]}"

        if self.action == "reject":
            return GuardrailResult(
                rejected=True,
                violation_type=violation_type,
                reason=reason,
                detected_patterns=all_detected,
            )

        if self.action == "redact":
            sanitized = self._sanitize_data(request, patterns_to_redact)
            return GuardrailResult(
                redacted=True,
                violation_type=violation_type,
                reason=reason,
                detected_patterns=all_detected,
                sanitized_request=sanitized,
            )

        # action == "flag"
        return GuardrailResult(
            flagged=True,
            violation_type=violation_type,
            reason=reason,
            detected_patterns=all_detected,
        )
