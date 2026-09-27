"""Lightweight HMAC-SHA256 Token implementation."""
import base64
import hashlib
import hmac
import json
import time
from typing import Any


def _b64_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64_decode(data_str: str) -> bytes:
    padding = 4 - (len(data_str) % 4)
    if padding and padding < 4:
        data_str += "=" * padding
    return base64.urlsafe_b64decode(data_str)


def generate_token(claims: dict[str, Any], secret: str, ttl_seconds: int = 3600) -> str:
    """Generates an HMAC-SHA256 signed token with expiration claim."""
    header = {"alg": "HS256", "typ": "JWT"}
    payload = dict(claims)
    now = int(time.time())
    payload["iat"] = now
    payload["exp"] = now + ttl_seconds

    h_b64 = _b64_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p_b64 = _b64_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{h_b64}.{p_b64}"

    sig = hmac.new(secret.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()
    s_b64 = _b64_encode(sig)
    return f"{signing_input}.{s_b64}"


def verify_token(token: str, secret: str) -> dict[str, Any]:
    """Verifies token signature and expiration, returning claims."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid token format: must have 3 segments")

    h_b64, p_b64, s_b64 = parts
    signing_input = f"{h_b64}.{p_b64}"
    expected_sig = hmac.new(secret.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()

    try:
        actual_sig = _b64_decode(s_b64)
    except Exception as exc:
        raise ValueError("Malformed signature segment") from exc

    if not hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("Signature verification failed: token tampered")

    try:
        payload = json.loads(_b64_decode(p_b64).decode("utf-8"))
    except Exception as exc:
        raise ValueError("Malformed payload segment") from exc

    now = int(time.time())
    if "exp" in payload and payload["exp"] < now:
        raise ValueError("Token expired")

    return payload
