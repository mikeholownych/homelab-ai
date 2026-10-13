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

SCOPES = ("workload", "qualification", "monitoring", "admin", "telemetry")


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
    allowed_models: frozenset[str] | None = None
    allowed_pools: frozenset[str] | None = None
    max_context_tokens: int | None = None
    model_quotas: dict[str, dict[str, Any]] = field(default_factory=dict)
    pool_quotas: dict[str, dict[str, Any]] = field(default_factory=dict)

    def permits_model(self, model_id: str | None) -> bool:
        """Check if this client is authorized for the given model ID / alias under RBAC policy."""
        if self.allowed_models is None or model_id is None:
            return True
        return model_id in self.allowed_models

    def permits_pool(self, pool_id: str | None) -> bool:
        """Check if this client is authorized for the given compute pool under RBAC policy."""
        if self.allowed_pools is None or pool_id is None:
            return True
        return pool_id in self.allowed_pools


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
    pool_buckets: dict[str, float] = field(default_factory=dict)
    pool_refilled_at: dict[str, float] = field(default_factory=dict)
    pool_tokens_today: dict[str, int] = field(default_factory=dict)
    model_buckets: dict[str, float] = field(default_factory=dict)
    model_refilled_at: dict[str, float] = field(default_factory=dict)
    model_tokens_today: dict[str, int] = field(default_factory=dict)


class ClientRegistry:
    def __init__(
        self,
        clients: Iterable[Client],
        *,
        state_path: str | Path | None = None,
        jwt_secret: str | None = None,
        jwt_public_key: str | None = None,
        jwt_issuer: str | None = None,
        jwt_audience: str | None = None,
        jwt_algorithms: tuple[str, ...] = ("HS256", "RS256"),
        flush_interval_seconds: float = 5.0,
    ) -> None:
        self._clients = {c.client_id: c for c in clients}
        self._usage: dict[str, _Usage] = {}
        self._lock = threading.Lock()
        self.state_path = Path(state_path) if state_path else None
        self.jwt_secret = jwt_secret
        self.jwt_public_key = jwt_public_key
        self.jwt_issuer = jwt_issuer
        self.jwt_audience = jwt_audience
        self.jwt_algorithms = jwt_algorithms
        self.flush_interval_seconds = max(0.1, float(flush_interval_seconds))
        self._dirty = False
        self._last_saved = time.monotonic()
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
            allowed_models = frozenset(entry["allowed_models"]) if "allowed_models" in entry else None
            allowed_pools = frozenset(entry["allowed_pools"]) if "allowed_pools" in entry else None
            model_quotas = quota.get("models") or {}
            pool_quotas = quota.get("pools") or {}
            clients.append(Client(
                str(entry["client_id"]), digest, scopes, entry.get("default_priority", "interactive"),
                entry.get("max_priority", entry.get("default_priority", "interactive")),
                quota.get("requests_per_minute"), quota.get("tokens_per_day"),
                allowed_models=allowed_models,
                allowed_pools=allowed_pools,
                max_context_tokens=entry.get("max_context_tokens"),
                model_quotas=model_quotas,
                pool_quotas=pool_quotas,
            ))
        if len({c.client_id for c in clients}) != len(clients):
            raise ValueError("duplicate client_id in client registry")
        return cls(
            clients,
            state_path=state_path,
            jwt_secret=raw.get("jwt_secret"),
            jwt_public_key=raw.get("jwt_public_key"),
            jwt_issuer=raw.get("jwt_issuer"),
            jwt_audience=raw.get("jwt_audience"),
        )

    @classmethod
    def from_tokens(cls, tokens: Iterable[tuple[str, str]], *, scopes: Iterable[str] = ("workload", "monitoring")) -> "ClientRegistry":
        """Compatibility: plain bearer tokens become clients with workload+monitoring scope."""
        return cls(Client(client_id, token_digest(token), frozenset(scopes)) for client_id, token in tokens if token)

    # ------------------------------------------------------------------ identity
    def authenticate(self, authorization: str) -> Client | None:
        if not authorization.startswith("Bearer "):
            return None
        token_str = authorization[len("Bearer "):].strip()
        presented = token_digest(token_str)
        match = None
        for client in self._clients.values():
            # compare every entry (constant work regardless of which one matches)
            if hmac.compare_digest(presented, client.token_sha256):
                match = client
        if match is not None:
            return match

        # Attempt JWT validation if configured
        verification_key = self.jwt_public_key or self.jwt_secret
        if verification_key and token_str.count(".") == 2:
            try:
                import jwt
                kwargs: dict[str, Any] = {"algorithms": list(self.jwt_algorithms)}
                if self.jwt_issuer:
                    kwargs["issuer"] = self.jwt_issuer
                if self.jwt_audience:
                    kwargs["audience"] = self.jwt_audience
                payload = jwt.decode(token_str, verification_key, **kwargs)
                client_id = str(payload.get("sub") or payload.get("client_id") or "jwt-client")
                scopes_raw = payload.get("scopes") or payload.get("roles") or ["workload"]
                scopes = frozenset(s for s in scopes_raw if s in SCOPES)
                allowed_models = frozenset(payload["allowed_models"]) if "allowed_models" in payload else None
                allowed_pools = frozenset(payload["allowed_pools"]) if "allowed_pools" in payload else None
                quota = payload.get("quota") or {}
                model_quotas = quota.get("models") or {}
                pool_quotas = quota.get("pools") or {}
                return Client(
                    client_id=client_id,
                    token_sha256=presented,
                    scopes=scopes if scopes else frozenset({"workload"}),
                    default_priority=str(payload.get("default_priority", "interactive")),
                    max_priority=str(payload.get("max_priority", "interactive")),
                    requests_per_minute=payload.get("requests_per_minute") or quota.get("requests_per_minute"),
                    tokens_per_day=payload.get("tokens_per_day") or quota.get("tokens_per_day"),
                    allowed_models=allowed_models,
                    allowed_pools=allowed_pools,
                    max_context_tokens=payload.get("max_context_tokens"),
                    model_quotas=model_quotas,
                    pool_quotas=pool_quotas,
                )
            except Exception:
                return None
        return None

    def clients(self) -> list[Client]:
        return list(self._clients.values())

    # ------------------------------------------------------------------ quotas
    def _usage_for(self, client: Client) -> _Usage:
        usage = self._usage.get(client.client_id)
        if usage is None:
            usage = _Usage(
                bucket=float(client.requests_per_minute or 0),
                model_buckets={m: float(q.get("requests_per_minute", 0)) for m, q in client.model_quotas.items() if q.get("requests_per_minute")},
                pool_buckets={p: float(q.get("requests_per_minute", 0)) for p, q in client.pool_quotas.items() if q.get("requests_per_minute")},
            )
            self._usage[client.client_id] = usage
        return usage

    def admit(self, client: Client, *, model: str | None = None, pool: str | None = None) -> None:
        """Charge one request; raise QuotaExceeded (429) when global, per-model, or per-pool limits are spent."""
        with self._lock:
            usage = self._usage_for(client)
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if usage.day != today:
                usage.day, usage.tokens_today = today, 0
                usage.model_tokens_today.clear()
                usage.pool_tokens_today.clear()

            now_dt = datetime.now(timezone.utc)
            seconds_left = max(1, 86400 - (now_dt.hour * 3600 + now_dt.minute * 60 + now_dt.second))
            now = time.monotonic()

            # Global daily tokens
            if client.tokens_per_day is not None and usage.tokens_today >= client.tokens_per_day:
                raise QuotaExceeded("daily token budget exhausted", seconds_left)

            # Global RPM
            if client.requests_per_minute:
                rate = client.requests_per_minute / 60.0
                usage.bucket = min(float(client.requests_per_minute), usage.bucket + (now - usage.refilled_at) * rate)
                usage.refilled_at = now
                if usage.bucket < 1.0:
                    raise QuotaExceeded("request rate limit exceeded", max(1, int((1.0 - usage.bucket) / rate) + 1))

            # Per-model quota check
            if model and model in client.model_quotas:
                mq = client.model_quotas[model]
                m_tokens_limit = mq.get("tokens_per_day")
                m_tokens_spent = usage.model_tokens_today.get(model, 0)
                if m_tokens_limit is not None and m_tokens_spent >= m_tokens_limit:
                    raise QuotaExceeded(f"daily token budget for model '{model}' exhausted", seconds_left)
                m_rpm = mq.get("requests_per_minute")
                if m_rpm:
                    m_rate = m_rpm / 60.0
                    m_bucket = usage.model_buckets.get(model, float(m_rpm))
                    m_refilled = usage.model_refilled_at.get(model, now)
                    m_bucket = min(float(m_rpm), m_bucket + (now - m_refilled) * m_rate)
                    usage.model_refilled_at[model] = now
                    if m_bucket < 1.0:
                        raise QuotaExceeded(f"request rate limit for model '{model}' exceeded", max(1, int((1.0 - m_bucket) / m_rate) + 1))

            # Per-pool quota check
            if pool and pool in client.pool_quotas:
                pq = client.pool_quotas[pool]
                p_tokens_limit = pq.get("tokens_per_day")
                p_tokens_spent = usage.pool_tokens_today.get(pool, 0)
                if p_tokens_limit is not None and p_tokens_spent >= p_tokens_limit:
                    raise QuotaExceeded(f"daily token budget for pool '{pool}' exhausted", seconds_left)
                p_rpm = pq.get("requests_per_minute")
                if p_rpm:
                    p_rate = p_rpm / 60.0
                    p_bucket = usage.pool_buckets.get(pool, float(p_rpm))
                    p_refilled = usage.pool_refilled_at.get(pool, now)
                    p_bucket = min(float(p_rpm), p_bucket + (now - p_refilled) * p_rate)
                    usage.pool_refilled_at[pool] = now
                    if p_bucket < 1.0:
                        raise QuotaExceeded(f"request rate limit for pool '{pool}' exceeded", max(1, int((1.0 - p_bucket) / p_rate) + 1))

            # Deduct from buckets only after all checks pass
            if client.requests_per_minute:
                usage.bucket -= 1.0
            if model and model in client.model_quotas and client.model_quotas[model].get("requests_per_minute"):
                usage.model_buckets[model] = usage.model_buckets.get(model, 0.0) - 1.0
            if pool and pool in client.pool_quotas and client.pool_quotas[pool].get("requests_per_minute"):
                usage.pool_buckets[pool] = usage.pool_buckets.get(pool, 0.0) - 1.0

    def charge_tokens(self, client: Client, tokens: int, *, model: str | None = None, pool: str | None = None, sync: bool = False) -> None:
        with self._lock:
            usage = self._usage_for(client)
            qty = max(0, int(tokens))
            usage.tokens_today += qty
            if model:
                usage.model_tokens_today[model] = usage.model_tokens_today.get(model, 0) + qty
            if pool:
                usage.pool_tokens_today[pool] = usage.pool_tokens_today.get(pool, 0) + qty
            self._dirty = True
        now = time.monotonic()
        if sync or (now - self._last_saved >= self.flush_interval_seconds):
            self.save_state()

    def usage(self, client_id: str) -> dict[str, Any]:
        with self._lock:
            usage = self._usage.get(client_id)
            if not usage:
                return {"day": "", "tokens_today": 0, "models": {}, "pools": {}}
            return {
                "day": usage.day,
                "tokens_today": usage.tokens_today,
                "models": dict(usage.model_tokens_today),
                "pools": dict(usage.pool_tokens_today),
            }

    # ------------------------------------------------------------------ dynamic reload
    def reload_clients(self, clients: Iterable[Client]) -> None:
        """Atomically update registered clients without losing in-memory usage tracking."""
        new_map = {c.client_id: c for c in clients}
        with self._lock:
            self._clients = new_map
            for cid in list(self._usage.keys()):
                if cid not in self._clients:
                    self._usage.pop(cid, None)

    def reload_from_file(self, path: str | Path) -> None:
        """Hot-reload registered clients from configuration file."""
        new_reg = self.from_file(path, state_path=self.state_path)
        self.reload_clients(new_reg.clients())

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
                self._usage[client_id] = _Usage(
                    bucket=float(self._clients[client_id].requests_per_minute or 0),
                    day=entry.get("day", ""),
                    tokens_today=int(entry.get("tokens_today", 0)),
                    model_tokens_today=dict(entry.get("models", {})),
                    pool_tokens_today=dict(entry.get("pools", {})),
                )

    def save_state(self, force: bool = False) -> None:
        if not self.state_path:
            return
        with self._lock:
            if not self._dirty and not force:
                return
            payload = {
                "usage": {
                    cid: {
                        "day": u.day,
                        "tokens_today": u.tokens_today,
                        "models": u.model_tokens_today,
                        "pools": u.pool_tokens_today,
                    }
                    for cid, u in self._usage.items()
                }
            }
            self._dirty = False
            self._last_saved = time.monotonic()
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
