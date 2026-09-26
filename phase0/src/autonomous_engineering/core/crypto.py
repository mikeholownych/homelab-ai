"""Cryptographic primitives, canonical serialization, and hashing."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    """Serialize value to canonical JSON string with sorted keys and compact separators."""
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )


def sha256_digest(data: bytes | str) -> str:
    """Compute hex SHA-256 digest of bytes or string."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def content_hash(value: Any) -> str:
    """Compute hex SHA-256 hash of canonical JSON representation of value."""
    return sha256_digest(canonical_json(value))
