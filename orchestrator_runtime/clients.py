"""Per-client identity, scopes, priority ceiling and quotas (R6).

The registry holds only sha256 digests of client tokens; plaintext tokens live in root-only files the operator hands
to each client. Every authenticated request resolves to a client id that appears on evidence and metrics. Scopes are
least-privilege (workload, qualification, monitoring, admin). Quotas are a requests-per-minute token bucket and a daily
token budget; exceeding either is a 429 with Retry-After. Counters persist across gateway restarts via the state file.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCOPES = ("workload", "qualification", "monitoring", "admin")


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class Client:
    client_id: str
    token_sha256: str
    scopes: frozenset[str]
    default_priority: str = "interactive"
    max_priority: str = "interactive"
    requests_per_minute: int | None = None
    tokens_per_day: int | None = None


class QuotaExceeded(Exception):
    def __init__(self, message: str, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass
class _Usage:
    bucket: float = 0.0
    refilled_at: float = field(default_factory=time.monotonic)
    day: str = ""
    tokens_today: int = 0


class ClientRegistry:
    def __init__(self, clients: Iterable[Client], *, state_path: str | Path | None = None) -> None:
        self._clients = {c.client_id: c for c in clients}
        self._usage: dict[str, _Usage] = {}
        self._lock = threading.Lock()
        self.state_path = Path(state_path) if state_path else None
        self._load_state()

    # ------------------------------------------------------------------ construction
    @classmethod
    def from_file(cls, path: str | Path, *, state_path: str | Path | None = None) -> "ClientRegistry":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        clients = []
        for entry in raw.get("clients", []):
            scopes = frozenset(entry.get("scopes", []))
            unknown = scopes - set(SCOPES)
            if unknown:
                raise ValueError(f"client {entry.get('client_id')!r}: unknown scopes {sorted(unknown)}")
            digest = str(entry["token_sha256"]).lower()
            if len(digest) != 64:
                raise ValueError(f"client {entry.get('client_id')!r}: token_sha256 must be a sha256 hex digest")
            quota = entry.get("quota") or {}
            clients.append(Client(
                str(entry["client_id"]), digest, scopes, entry.get("default_priority", "interactive"),
                entry.get("max_priority", entry.get("default_priority", "interactive")),
                quota.get("requests_per_minute"), quota.get("tokens_per_day"),
            ))
        if len({c.client_id for c in clients}) != len(clients):
            raise ValueError("duplicate client_id in client registry")
        return cls(clients, state_path=state_path)

    @classmethod
    def from_tokens(cls, tokens: Iterable[tuple[str, str]], *, scopes: Iterable[str] = ("workload", "monitoring")) -> "ClientRegistry":
        """Compatibility: plain bearer tokens become clients with workload+monitoring scope."""
        return cls(Client(client_id, token_digest(token), frozenset(scopes)) for client_id, token in tokens if token)

    # ------------------------------------------------------------------ identity
    def authenticate(self, authorization: str) -> Client | None:
        if not authorization.startswith("Bearer "):
            return None
        presented = token_digest(authorization[len("Bearer "):].strip())
        match = None
        for client in self._clients.values():
            # compare every entry (constant work regardless of which one matches)
            if hmac.compare_digest(presented, client.token_sha256):
                match = client
        return match

    def clients(self) -> list[Client]:
        return list(self._clients.values())

    # ------------------------------------------------------------------ quotas
    def _usage_for(self, client: Client) -> _Usage:
        usage = self._usage.get(client.client_id)
        if usage is None:
            usage = _Usage(bucket=float(client.requests_per_minute or 0))
            self._usage[client.client_id] = usage
        return usage

    def admit(self, client: Client) -> None:
        """Charge one request; raise QuotaExceeded (429) when the RPM bucket or daily token budget is spent."""
        with self._lock:
            usage = self._usage_for(client)
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if usage.day != today:
                usage.day, usage.tokens_today = today, 0
            if client.tokens_per_day is not None and usage.tokens_today >= client.tokens_per_day:
                now = datetime.now(timezone.utc)
                seconds_left = 86400 - (now.hour * 3600 + now.minute * 60 + now.second)
                raise QuotaExceeded("daily token budget exhausted", max(1, seconds_left))
            if client.requests_per_minute:
                now = time.monotonic()
                rate = client.requests_per_minute / 60.0
                usage.bucket = min(float(client.requests_per_minute), usage.bucket + (now - usage.refilled_at) * rate)
                usage.refilled_at = now
                if usage.bucket < 1.0:
                    raise QuotaExceeded("request rate limit exceeded", max(1, int((1.0 - usage.bucket) / rate) + 1))
                usage.bucket -= 1.0

    def charge_tokens(self, client: Client, tokens: int) -> None:
        with self._lock:
            usage = self._usage_for(client)
            usage.tokens_today += max(0, int(tokens))
        self.save_state()

    def usage(self, client_id: str) -> dict[str, Any]:
        with self._lock:
            usage = self._usage.get(client_id)
            return {"day": usage.day, "tokens_today": usage.tokens_today} if usage else {"day": "", "tokens_today": 0}

    # ------------------------------------------------------------------ persistence
    def _load_state(self) -> None:
        if not self.state_path or not self.state_path.exists():
            return
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for client_id, entry in (raw.get("usage") or {}).items():
            if client_id in self._clients:
                self._usage[client_id] = _Usage(bucket=float(self._clients[client_id].requests_per_minute or 0),
                                                day=entry.get("day", ""), tokens_today=int(entry.get("tokens_today", 0)))

    def save_state(self) -> None:
        if not self.state_path:
            return
        with self._lock:
            payload = {"usage": {cid: {"day": u.day, "tokens_today": u.tokens_today} for cid, u in self._usage.items()}}
        tmp = self.state_path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(payload), encoding="utf-8")
            tmp.replace(self.state_path)
        except OSError:
            pass


def clamp_priority(requested: str | None, client: Client, order: dict[str, int]) -> tuple[str, bool]:
    """Monotonic: a client may ask for a lower class than its ceiling, never a higher one."""
    wanted = requested if requested in order else client.default_priority
    if order.get(wanted, 0) < order.get(client.max_priority, 0):
        return client.max_priority, True
    return wanted, False
