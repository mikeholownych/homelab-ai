"""Capabilities with provenance: DECLARED by the engine, VERIFIED by qualification evidence, never assumed.

One model serves both routing (R9) and what clients are told (`/v1/models`), so the gateway can never route on a
capability it would not report, or report one it would not route on. An alias's capabilities are the intersection over
every worker the alias can reach, because that is all the gateway can guarantee.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

# Capabilities the gateway can offer through its API. Engine features the gateway does not expose (e.g. /infill,
# /embeddings) are reported unavailable for every alias: a feature the gateway does not serve is not the alias's.
CAPABILITIES = (
    "tools", "parallel_tool_calls", "structured_output", "vision", "reasoning", "reasoning_controllable",
    "streaming", "output_contract_compliance", "fim", "embeddings",
)
_GATEWAY_PROVIDED = {"streaming"}
_NOT_EXPOSED = {"fim", "embeddings"}
_RANK = {"verified": 2, "declared": 1, "unavailable": 0}


@dataclass(frozen=True)
class Capability:
    available: bool
    provenance: str  # "declared" | "verified" | "unavailable"
    evidence: tuple[str, ...] = ()
    verified_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"available": self.available, "provenance": self.provenance}
        if self.evidence:
            out["evidence"] = list(self.evidence)
        if self.verified_at:
            out["verified_at"] = self.verified_at
        return out


UNAVAILABLE = Capability(False, "unavailable")


def worker_capabilities(declared: dict[str, bool] | None, verified: dict[str, Any] | None) -> dict[str, Capability]:
    """Combine an engine declaration with qualification evidence for one worker artifact.

    A verified result (pass or fail) overrides the declaration: evidence that the engine's claim does not hold in
    practice (e.g. reasoning cannot actually be switched off) must win over the claim.
    """
    declared = declared or {}
    verified = verified or {}
    result: dict[str, Capability] = {}
    for name in CAPABILITIES:
        record = verified.get(name)
        if name in _NOT_EXPOSED:
            result[name] = UNAVAILABLE
        elif isinstance(record, dict) and record.get("result") in ("pass", "fail"):
            evidence = (str(record["evidence_id"]),) if record.get("evidence_id") else ()
            result[name] = Capability(record["result"] == "pass", "verified", evidence, record.get("date"))
        elif name in _GATEWAY_PROVIDED:
            result[name] = Capability(True, "declared", ("gateway",))
        elif declared.get(name):
            result[name] = Capability(True, "declared", ("engine",))
        else:
            result[name] = UNAVAILABLE
    return result


def intersect(per_worker: Iterable[dict[str, Capability]]) -> dict[str, Capability]:
    """Alias view: available only where every reachable worker has it; provenance is the weakest one present."""
    per_worker = list(per_worker)
    if not per_worker:
        return {name: UNAVAILABLE for name in CAPABILITIES}
    merged: dict[str, Capability] = {}
    for name in CAPABILITIES:
        caps = [w.get(name, UNAVAILABLE) for w in per_worker]
        if not all(c.available for c in caps):
            # A worker *verified* to lack it is stronger information than a worker that merely does not declare it.
            failed = [c for c in caps if not c.available and c.provenance == "verified"]
            merged[name] = Capability(False, "verified", tuple(sorted({e for c in failed for e in c.evidence}))) if failed else UNAVAILABLE
            continue
        weakest = min(caps, key=lambda c: _RANK[c.provenance])
        evidence = tuple(sorted({e for c in caps for e in c.evidence}))
        merged[name] = Capability(True, weakest.provenance, evidence, weakest.verified_at)
    return merged


def requirements(request: dict[str, Any], reasoning_requested: bool) -> frozenset[str]:
    """What a request needs from a worker (R9). Derived from the request itself, never guessed from content."""
    needs: set[str] = set()
    if request.get("tools"):
        needs.add("tools")
        if request.get("parallel_tool_calls") is True:
            needs.add("parallel_tool_calls")
    response_format = request.get("response_format")
    if isinstance(response_format, dict) and response_format.get("type") in ("json_schema", "json_object"):
        needs.add("structured_output")
    for message in request.get("messages") or []:
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list) and any(isinstance(p, dict) and p.get("type") in ("image_url", "input_image") for p in content):
            needs.add("vision")
            break
    if reasoning_requested:
        needs.add("reasoning")
    return frozenset(needs)
