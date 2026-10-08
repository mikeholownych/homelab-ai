"""Live per-worker capacity: what each worker actually is and can hold, re-observed every health cycle.

The inventory states what a worker is *expected* to be. The engine says what it *is*. Observed limits govern sizing;
inventory values become expectations whose mismatch is evidenced. A worker serving a different model than its pool
declares is blocked (the wrong model must never answer under a pool's name). A real engine whose capacity has never
been observed is not eligible: unknown capacity fails closed.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .capabilities import Capability, worker_capabilities
from .engines import EngineAdapter, EngineObservation


@dataclass(frozen=True)
class CapacityState:
    worker_id: str
    source: str  # "observed" | "inventory"
    engine: str
    engine_version: str | None
    model_path: str | None
    model_alias: str | None
    quantization: str | None
    ctx_per_slot: int
    slots_total: int
    observed_at: float
    limits_version: str
    declared: dict[str, bool] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source, "engine": self.engine, "engine_version": self.engine_version,
            "model_alias": self.model_alias, "quantization": self.quantization,
            "ctx_per_slot": self.ctx_per_slot, "slots_total": self.slots_total,
            "observed_at": self.observed_at, "limits_version": self.limits_version,
        }


# Inventory capability names (orchestrator_gateway_workers[].capabilities) -> API capability names.
_INVENTORY_CAPABILITIES = {"tool_call_proposal": "tools", "tools": "tools", "structured_output": "structured_output",
                           "vision": "vision", "reasoning": "reasoning"}


def _version(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


class CapacityTracker:
    def __init__(
        self,
        records: Callable[[], list[dict[str, Any]]],
        engines: dict[str, EngineAdapter],
        *,
        evidence: Any = None,
        metrics: Any = None,
        verified: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._records = records
        self.engines = engines
        self.evidence = evidence
        self.metrics = metrics
        self.verified = verified or {}
        self._states: dict[str, CapacityState] = {}
        self._mismatch: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ observation
    def _record(self, worker_id: str) -> dict[str, Any] | None:
        return next((r for r in self._records() if r["worker_id"] == worker_id), None)

    def refresh(self, worker_id: str) -> CapacityState | None:
        record = self._record(worker_id)
        if record is None:
            return None
        engine = self.engines.get(worker_id)
        if engine is None:
            # No engine adapter (in-memory / unknown engine): the inventory record is the only description we have,
            # and it is labelled as such everywhere it is shown.
            state = CapacityState(
                worker_id, "inventory", record.get("engine", "unknown"), None, None, record.get("model_id"), None,
                int(record["context_limit"]), int(record["max_concurrency"]), time.time(),
                _version("inventory", record["context_limit"], record["max_concurrency"], record.get("model_id")),
            )
        else:
            observation = engine.observe()
            if observation is None or not observation.ctx_per_slot:
                return self.state(worker_id)  # unknown now: keep last known for display, eligibility decides
            state = self._from_observation(worker_id, record, observation)
        self._apply(record, state)
        return state

    def _from_observation(self, worker_id: str, record: dict[str, Any], obs: EngineObservation) -> CapacityState:
        # vLLM publishes no slot count; the inventory's declared concurrency stands in (and is labelled observed+declared).
        slots = obs.slots_total or int(record["max_concurrency"])
        return CapacityState(
            worker_id, "observed", obs.engine, obs.engine_version, obs.model_path, obs.model_alias, obs.quantization,
            int(obs.ctx_per_slot or 0), slots, obs.observed_at,
            _version(obs.limits_tuple(), slots), dict(obs.declared),
        )

    def _apply(self, record: dict[str, Any], state: CapacityState) -> None:
        worker_id = state.worker_id
        with self._lock:
            previous = self._states.get(worker_id)
            self._states[worker_id] = state
        if previous is not None and previous.limits_version != state.limits_version and self.evidence is not None:
            self.evidence.append("worker_capacity_changed", worker_id=worker_id,
                                 previous=previous.as_dict(), current=state.as_dict())
        mismatch: dict[str, Any] = {}
        if state.source == "observed":
            if int(record["context_limit"]) != state.ctx_per_slot:
                mismatch["context_limit"] = {"inventory": int(record["context_limit"]), "observed": state.ctx_per_slot}
            if int(record["max_concurrency"]) != state.slots_total:
                mismatch["max_concurrency"] = {"inventory": int(record["max_concurrency"]), "observed": state.slots_total}
            if state.model_alias and record.get("model_id") and state.model_alias != record["model_id"]:
                mismatch["model_identity"] = {"inventory": record["model_id"], "observed": state.model_alias}
        with self._lock:
            before = self._mismatch.get(worker_id)
            self._mismatch[worker_id] = mismatch
        if mismatch != (before or {}) and mismatch and self.evidence is not None:
            self.evidence.append("worker_inventory_mismatch", worker_id=worker_id, fields=mismatch)
        if self.metrics is not None:
            for name in ("context_limit", "max_concurrency", "model_identity"):
                self.metrics.worker_inventory_mismatch.set(1.0 if name in mismatch else 0.0, worker_id=worker_id, field=name)
            self.metrics.worker_context_limit.set(state.ctx_per_slot, worker_id=worker_id)
            self.metrics.worker_slots_total.set(state.slots_total, worker_id=worker_id)

    def refresh_all(self) -> None:
        for record in self._records():
            try:
                self.refresh(record["worker_id"])
            except Exception:  # noqa: BLE001 - one worker's observation must never stop the others
                continue

    # ------------------------------------------------------------------ queries
    def state(self, worker_id: str) -> CapacityState | None:
        with self._lock:
            return self._states.get(worker_id)

    def mismatch(self, worker_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._mismatch.get(worker_id) or {})

    def blocked_reason(self, worker_id: str) -> str | None:
        """Why a worker must not receive work right now, or None. Unknown capacity of a real engine fails closed."""
        state = self.state(worker_id)
        if state is None:
            return "capacity_unknown"
        if "model_identity" in self.mismatch(worker_id):
            return "model_identity_mismatch"
        return None

    def capabilities(self, worker_id: str) -> dict[str, Capability]:
        record = self._record(worker_id) or {}
        state = self.state(worker_id)
        if state is not None and state.source == "observed":
            declared = dict(state.declared)
        else:
            # No engine to ask: only what the inventory explicitly declares (inventory names map to API capabilities).
            declared = {_INVENTORY_CAPABILITIES[name]: True for name in (record.get("capabilities") or ())
                        if name in _INVENTORY_CAPABILITIES}
        verified = self.verified.get(str(record.get("artifact_digest", ""))) or {}
        return worker_capabilities(declared, verified)
