"""Hardened Capability Tokens with cryptographic revision and constraint binding."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import uuid

from autonomous_engineering.core.crypto import content_hash


@dataclass(frozen=True)
class CapabilityToken:
    """A tamper-evident, time-bounded capability token issued exclusively by the control plane.

    Hardened in Phase 1 to bind:
    - Target repository baseline commit.
    - Authoritative Work-Order contract hash.
    - Strict maximum output payload limits.
    """

    token_id: str
    work_order_id: str
    work_order_version: int
    task_id: str
    authorized_paths: tuple[str, ...]
    authorized_tools: tuple[str, ...]
    max_retries: int
    fencing_token: int
    issued_at: str
    expires_at: str
    baseline_commit: str = ""
    contract_hash: str = ""
    max_output_bytes: int = 1_000_000
    revoked: bool = False
    signature_hash: str = ""

    def __post_init__(self) -> None:
        if not self.signature_hash:
            payload = {
                "token_id": self.token_id,
                "work_order_id": self.work_order_id,
                "work_order_version": self.work_order_version,
                "task_id": self.task_id,
                "baseline_commit": self.baseline_commit,
                "contract_hash": self.contract_hash,
                "authorized_paths": sorted(self.authorized_paths),
                "authorized_tools": sorted(self.authorized_tools),
                "max_retries": self.max_retries,
                "fencing_token": self.fencing_token,
                "issued_at": self.issued_at,
                "expires_at": self.expires_at,
                "max_output_bytes": self.max_output_bytes,
                "revoked": self.revoked,
            }
            computed = content_hash(payload)
            object.__setattr__(self, "signature_hash", computed)

    def is_valid(self, now_iso: str | None = None) -> bool:
        """Check whether the token is currently valid, unrevoked, and untampered."""
        if self.revoked:
            return False

        # Verify cryptographic integrity
        payload = {
            "token_id": self.token_id,
            "work_order_id": self.work_order_id,
            "work_order_version": self.work_order_version,
            "task_id": self.task_id,
            "baseline_commit": self.baseline_commit,
            "contract_hash": self.contract_hash,
            "authorized_paths": sorted(self.authorized_paths),
            "authorized_tools": sorted(self.authorized_tools),
            "max_retries": self.max_retries,
            "fencing_token": self.fencing_token,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "max_output_bytes": self.max_output_bytes,
            "revoked": self.revoked,
        }
        if content_hash(payload) != self.signature_hash:
            return False

        # Verify expiration
        current_time = (
            datetime.fromisoformat(now_iso)
            if now_iso
            else datetime.now(timezone.utc)
        )
        expiry_time = datetime.fromisoformat(self.expires_at)
        if expiry_time.tzinfo is None:
            expiry_time = expiry_time.replace(tzinfo=timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)

        return current_time < expiry_time
