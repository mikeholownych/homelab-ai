"""Capability-Aware Inference Scheduling (CAIS): evidence-backed model eligibility (docs/design/07).

A model execution profile may serve a capability-class request only while it holds an *effective* qualification:

* **Authority.** Qualifications are granted, reinstated and revoked only in the *authoritative ledger*, a
  hash-chained JSONL file kept in Git and delivered read-only to the gateway (the gateway user cannot write it). The
  gateway may append to its own *suspension ledger* in its state directory, but that ledger can only ever *remove*
  eligibility (suspend/revoke); grant-type events found there are treated as tampering and fail CAIS closed.
* **Evidence.** A grant is never trusted on its own. At every load the gateway re-verifies the referenced evidence
  bundle (sha256), checks it was produced against the exact execution profile and the *current* capability
  definition, and re-derives the decision from the raw trial results with :func:`assess_bundle`. A grant whose
  evidence does not independently support it is ``invalid``.
* **Scope.** A qualification binds capability + capability version + execution-profile digest (model artifact,
  runtime image, engine, topology, hardware class, worker reasoning cap) + reasoning policy + context envelope.
  Anything else (another GPU class, a rebuilt runtime, a re-quantised file) is a different profile and unqualified.
* **Fail closed.** Unknown capability, unreadable or broken ledgers, rolled-back ledgers, or no effective
  qualification all deny the request with a machine-readable reason. Nothing here ever widens eligibility; legacy
  requests (no capability header) never reach this module.

What this proves: that the selected profile is bound to an integrity-checked, re-scorable evaluation record that met
the versioned criteria, and that no recorded suspension/revocation applies. What it does not prove: that the
operator
who committed the ledger evaluated honestly (the hash chain and Git review attribute changes, they do not sign them),
that the evaluation suite measures real-world competence, or that the worker process is serving the bytes its
inventory digest names (the gateway compares the engine's reported model alias; the file digest is verified at deploy).
"""
from __future__ import annotations

import functools
import hashlib
import json
import math
import os
import re
import statistics
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .evidence import canonical, record_hash, verify_lines
from .reasoning import RoutePolicy

CAPABILITIES_SCHEMA = "cais-capabilities/v1"
BUNDLE_SCHEMA = "cais-evidence-bundle/v1"
MODES = ("off", "enforce")
PRIORITIES = ("quality", "latency")
FALLBACKS = ("qualified_only", "none")
INDEPENDENCE = ("internal", "independent")  # ordered weakest -> strongest; "self_reported" is never accepted
TRIAL_OUTCOMES = ("pass", "fail", "infra_error")
GRANT_EVENTS = ("qualification_granted", "qualification_reinstated")
REMOVAL_EVENTS = ("qualification_suspended", "qualification_revoked")
AUTHORITATIVE_EVENTS = ("cais_genesis", *GRANT_EVENTS, *REMOVAL_EVENTS)
GATEWAY_EVENTS = ("cais_genesis", *REMOVAL_EVENTS)
_CAPABILITY_NAME = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
_SAFE_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}\.json$")

# Effective qualification states. Only QUALIFIED confers eligibility.
QUALIFIED = "qualified"
SUSPENDED = "suspended"
REVOKED = "revoked"
EXPIRED = "expired"
PENDING = "pending"          # issued_at in the future
SUPERSEDED = "superseded"    # granted against an older capability definition version
INVALID = "invalid"          # evidence missing, tampered, mismatched, or does not support the grant
STATES = (QUALIFIED, SUSPENDED, REVOKED, EXPIRED, PENDING, SUPERSEDED, INVALID)

# failure_class -> HTTP status for every CAIS denial (stable client contract, docs/design/07 section 6).
FAILURES = {
    "cais_disabled": 503,
    "cais_request_invalid": 400,
    "capability_unknown": 400,
    "qualification_state_unavailable": 503,
    "no_qualified_model": 422,
    "qualification_expired": 422,
    "qualification_suspended": 422,
    "qualification_revoked": 422,
    "context_unsupported": 422,
    "policy_denied": 403,
    "worker_unavailable": 503,
}


class CaisConfigError(ValueError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ====================================================================================================== definitions
@dataclass(frozen=True)
class Criteria:
    suite_id: str
    suite_version: str
    min_tasks: int
    min_pass_lower_bound: float
    confidence: float
    max_infra_error_rate: float
    max_validity_days: int
    min_context_envelope: int
    min_independence: str

    def describe(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class CapabilityDefinition:
    name: str
    version: int
    description: str
    criteria: Criteria

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "version": self.version, "description": self.description,
                "criteria": self.criteria.describe()}


@dataclass(frozen=True)
class CapabilityCatalog:
    policy_version: str
    digest: str
    capabilities: Mapping[str, CapabilityDefinition]

    @classmethod
    def from_json(cls, raw: bytes | str) -> "CapabilityCatalog":
        data_bytes = raw.encode() if isinstance(raw, str) else raw
        try:
            data = json.loads(data_bytes)
        except ValueError as error:
            raise CaisConfigError(f"capability catalog is not JSON: {error}") from error
        if not isinstance(data, dict) or data.get("schema") != CAPABILITIES_SCHEMA:
            raise CaisConfigError(f"capability catalog schema must be {CAPABILITIES_SCHEMA!r}")
        unknown = set(data) - {"schema", "policy_version", "capabilities", "comment"}
        if unknown:
            raise CaisConfigError(f"capability catalog has unknown keys {sorted(unknown)}")
        policy_version = data.get("policy_version")
        if not isinstance(policy_version, str) or not policy_version:
            raise CaisConfigError("policy_version must be a non-empty string")
        raw_caps = data.get("capabilities")
        if not isinstance(raw_caps, dict) or not raw_caps:
            raise CaisConfigError("capabilities must be a non-empty object")
        caps: dict[str, CapabilityDefinition] = {}
        for name, spec in raw_caps.items():
            caps[name] = _definition(name, spec)
        return cls(policy_version, _sha256_bytes(data_bytes), caps)


def _definition(name: str, spec: Any) -> CapabilityDefinition:
    where = f"capability {name!r}"
    if not isinstance(name, str) or not _CAPABILITY_NAME.match(name):
        raise CaisConfigError(f"{where}: name must be dotted lowercase (e.g. coding.routine)")
    if not isinstance(spec, dict) or set(spec) - {"version", "description", "criteria"}:
        raise CaisConfigError(f"{where}: must be {{version, description, criteria}}")
    version = spec.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise CaisConfigError(f"{where}: version must be a positive integer")
    raw = spec.get("criteria")
    keys = {"suite_id", "suite_version", "min_tasks", "min_pass_lower_bound", "confidence",
            "max_infra_error_rate", "max_validity_days", "min_context_envelope", "min_independence"}
    if not isinstance(raw, dict) or set(raw) != keys:
        raise CaisConfigError(f"{where}: criteria must have exactly {sorted(keys)}")

    def number(key: str, low: float, high: float, integer: bool = False) -> Any:
        value = raw[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or (integer and not isinstance(value, int)):
            raise CaisConfigError(f"{where}: {key} must be {'an integer' if integer else 'a number'}")
        if not low <= value <= high:
            raise CaisConfigError(f"{where}: {key} must be within [{low}, {high}]")
        return value

    for key in ("suite_id", "suite_version"):
        if not isinstance(raw[key], str) or not raw[key]:
            raise CaisConfigError(f"{where}: {key} must be a non-empty string")
    if raw["min_independence"] not in INDEPENDENCE:
        raise CaisConfigError(f"{where}: min_independence must be one of {list(INDEPENDENCE)}")
    criteria = Criteria(
        suite_id=raw["suite_id"], suite_version=raw["suite_version"],
        # Below ~10 distinct tasks no pass-rate bound is meaningful; the floor stops a definition pretending otherwise.
        min_tasks=number("min_tasks", 10, 100_000, integer=True),
        min_pass_lower_bound=float(number("min_pass_lower_bound", 0.0, 1.0)),
        confidence=float(number("confidence", 0.5, 0.999)),
        max_infra_error_rate=float(number("max_infra_error_rate", 0.0, 0.5)),
        max_validity_days=number("max_validity_days", 1, 366, integer=True),
        min_context_envelope=number("min_context_envelope", 1, 10_000_000, integer=True),
        min_independence=raw["min_independence"],
    )
    description = spec.get("description", "")
    if not isinstance(description, str):
        raise CaisConfigError(f"{where}: description must be a string")
    return CapabilityDefinition(name, version, description, criteria)


# ================================================================================================ profile identity
PROFILE_FIELDS = ("model_id", "artifact_digest", "runtime_image_digest", "engine", "topology", "hardware_class",
                  "reasoning_budget")


def profile_identity(worker: Any) -> dict[str, Any]:
    """The execution profile a qualification binds to. Worker id, endpoint, GPU index and context size are excluded:
    two workers running the same artifact on the same runtime and hardware class are the same profile (equivalence
    rule), and context is bounded separately by the qualification's measured envelope."""
    get = worker.get if isinstance(worker, dict) else (lambda key, default=None: getattr(worker, key, default))
    return {name: get(name, None) for name in PROFILE_FIELDS}


def profile_digest(identity: Mapping[str, Any]) -> str:
    values = tuple(identity.get(k) for k in PROFILE_FIELDS)
    try:
        return _profile_digest(values)
    except TypeError:  # an unhashable field value (malformed ledger input): compute without the cache
        return _profile_digest.__wrapped__(values)


@functools.lru_cache(maxsize=1024)
def _profile_digest(values: tuple[Any, ...]) -> str:
    return "sha256:" + hashlib.sha256(canonical(dict(zip(PROFILE_FIELDS, values))).encode()).hexdigest()


# ===================================================================================================== assessment
def wilson_lower_bound(passes: int, trials: int, confidence: float) -> float:
    """One-sided Wilson score lower bound of the pass rate: the rate we can claim at ``confidence`` given n trials."""
    if trials <= 0:
        return 0.0
    z = statistics.NormalDist().inv_cdf(confidence)
    p = passes / trials
    denominator = 1 + z * z / trials
    centre = p + z * z / (2 * trials)
    margin = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials))
    return max(0.0, (centre - margin) / denominator)


@dataclass(frozen=True)
class Assessment:
    qualified: bool
    reasons: tuple[str, ...]
    functional: dict[str, Any]
    operational: dict[str, Any]
    performance: dict[str, Any]

    def describe(self) -> dict[str, Any]:
        return {"qualified": self.qualified, "reasons": list(self.reasons), "functional": self.functional,
                "operational": self.operational, "performance": self.performance}


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))
    return ordered[index]


def assess_bundle(bundle: Mapping[str, Any], definition: CapabilityDefinition) -> Assessment:
    """Deterministically re-derive a qualification decision from raw trial results.

    The statistical unit is the distinct *task*, not the trial: repeats of one prompt (temperature 0, same fixture)
    are strongly correlated, so counting them as independent Bernoulli trials would overstate confidence. A task passes
    only if every graded repeat passed; a task that both passed and failed is reported as unstable and counts as a
    failure. Gate tasks (deterministic must-pass checks) must pass regardless of the statistical result, so a high
    average can never hide a critical failure. Infrastructure errors are excluded (they are not the model's) but too
    many of them make the evidence insufficient rather than favourable. Functional correctness and operational
    reliability gate; performance is reported only.
    """
    criteria = definition.criteria
    reasons: list[str] = []
    if bundle.get("schema") != BUNDLE_SCHEMA:
        reasons.append("bundle_schema")
    if bundle.get("capability") != definition.name:
        reasons.append("bundle_capability_mismatch")
    if bundle.get("capability_version") != definition.version:
        reasons.append("bundle_capability_version_mismatch")
    suite = bundle.get("suite") if isinstance(bundle.get("suite"), dict) else {}
    if suite.get("id") != criteria.suite_id or suite.get("version") != criteria.suite_version:
        reasons.append("suite_mismatch")
    independence = bundle.get("independence")
    if independence not in INDEPENDENCE:
        reasons.append("independence_unaccepted")
    elif INDEPENDENCE.index(independence) < INDEPENDENCE.index(criteria.min_independence):
        reasons.append("independence_insufficient")
    envelope = bundle.get("context_envelope")
    if isinstance(envelope, bool) or not isinstance(envelope, int) or envelope < criteria.min_context_envelope:
        reasons.append("context_envelope_insufficient")

    trials = bundle.get("trials")
    if not isinstance(trials, list):
        trials = []
        reasons.append("trials_missing")
    malformed = sum(1 for t in trials if not (isinstance(t, dict) and t.get("outcome") in TRIAL_OUTCOMES
                                              and isinstance(t.get("task_id"), str) and t["task_id"]))
    infra = sum(1 for t in trials if isinstance(t, dict) and t.get("outcome") == "infra_error")
    graded: dict[tuple[bool, str], list[str]] = {}
    for t in trials:
        if isinstance(t, dict) and t.get("outcome") in ("pass", "fail") and isinstance(t.get("task_id"), str):
            graded.setdefault((t.get("gate") is True, t["task_id"]), []).append(t["outcome"])
    gate_tasks = {task: outcomes for (gate, task), outcomes in graded.items() if gate}
    stat_tasks = {task: outcomes for (gate, task), outcomes in graded.items() if not gate}
    gate_failures = sorted(task for task, outcomes in gate_tasks.items() if any(o != "pass" for o in outcomes))
    unstable = sorted(task for task, outcomes in stat_tasks.items() if len(set(outcomes)) > 1)
    passes = sum(1 for outcomes in stat_tasks.values() if all(o == "pass" for o in outcomes))
    lower = wilson_lower_bound(passes, len(stat_tasks), criteria.confidence)
    infra_rate = infra / len(trials) if trials else 1.0
    if malformed:
        reasons.append("trials_malformed")
    if gate_failures:
        reasons.append("deterministic_gate_failed")
    if len(stat_tasks) < criteria.min_tasks:
        reasons.append("insufficient_tasks")
    if lower < criteria.min_pass_lower_bound:
        reasons.append("pass_rate_below_threshold")
    if infra_rate > criteria.max_infra_error_rate:
        reasons.append("insufficient_evidence_infra_errors")
    graded_trials = [t for t in trials if isinstance(t, dict) and t.get("outcome") in ("pass", "fail")]
    latencies = [float(t["latency_ms"]) for t in graded_trials if isinstance(t.get("latency_ms"), (int, float))]
    ttfts = [float(t["ttft_ms"]) for t in graded_trials if isinstance(t.get("ttft_ms"), (int, float))]
    repeats = sorted({len(outcomes) for outcomes in stat_tasks.values()})
    return Assessment(
        qualified=not reasons,
        reasons=tuple(reasons),
        functional={"unit": "task", "tasks": len(stat_tasks), "task_passes": passes,
                    "pass_rate": round(passes / len(stat_tasks), 4) if stat_tasks else None,
                    "pass_lower_bound": round(lower, 4), "confidence": criteria.confidence,
                    "threshold": criteria.min_pass_lower_bound, "repeats_per_task": repeats,
                    "graded_trials": len(graded_trials), "gate_tasks": len(gate_tasks),
                    "gate_failures": gate_failures, "unstable_tasks": unstable},
        operational={"trials": len(trials), "infra_errors": infra, "infra_error_rate": round(infra_rate, 4),
                     "max_infra_error_rate": criteria.max_infra_error_rate, "malformed_trials": malformed},
        performance={"latency_p50_ms": _percentile(latencies, 0.5), "latency_p95_ms": _percentile(latencies, 0.95),
                     "ttft_p50_ms": _percentile(ttfts, 0.5), "ttft_p95_ms": _percentile(ttfts, 0.95)},
    )


# ========================================================================================================= ledgers
@dataclass(frozen=True)
class LedgerRead:
    records: tuple[dict[str, Any], ...]
    intact: bool
    head: str | None
    problems: tuple[str, ...]


def read_ledger(path: Path) -> LedgerRead:
    """A missing ledger is an empty, intact ledger; an unreadable or broken one is not intact."""
    if not path.exists():
        return LedgerRead((), True, None, ())
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        return LedgerRead((), False, None, (f"unreadable: {error.__class__.__name__}",))
    lines = text.splitlines()
    intact, _count, head, problems = verify_lines(lines)
    records = []
    for line in lines:
        if line.strip():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return LedgerRead(tuple(records), intact, head, tuple(problems))


def append_ledger(path: Path, event: str, **fields: Any) -> dict[str, Any]:
    """Durably append one chained record (fsync file and directory). Callers serialise appends."""
    current = read_ledger(path)
    if not current.intact:
        raise OSError(f"refusing to extend a broken ledger at {path}")
    record = {"evidence_id": str(uuid.uuid4()), "event": event, "recorded_at": _now().isoformat(),
              "previous_hash": current.head, **fields}
    record["record_hash"] = record_hash(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
    try:
        os.write(descriptor, (canonical(record) + "\n").encode())
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return record


# =================================================================================================== qualification
@dataclass(frozen=True)
class Qualification:
    qualification_id: str
    capability: str
    capability_version: int
    profile_digest: str
    reasoning: dict[str, Any]
    context_envelope: int
    independence: str
    issued_at: str
    expires_at: str
    authority: str
    bundle: str
    bundle_sha256: str
    grant_evidence_id: str
    state: str
    reasons: tuple[str, ...]
    pass_lower_bound: float
    active_suspensions: tuple[str, ...] = ()

    def describe(self) -> dict[str, Any]:
        out = {k: v for k, v in self.__dict__.items()}
        out["reasons"] = list(self.reasons)
        out["active_suspensions"] = list(self.active_suspensions)
        return out


@dataclass(frozen=True)
class CaisSnapshot:
    """An immutable, fully derived view of qualification state; swapped atomically on reload/suspension."""

    valid: bool
    problems: tuple[str, ...]
    catalog: CapabilityCatalog | None
    qualifications: Mapping[str, Qualification]
    authoritative_head: str | None
    gateway_head: str | None
    anti_rollback: str
    loaded_at: str
    _effective_cache: list = field(default_factory=list, compare=False, repr=False)

    def effective(self, now: datetime) -> dict[str, Qualification]:
        """Qualifications with time-dependent state (expiry, not-yet-valid) applied at ``now``. Only the validity
        window varies with time, so results are reused until the next boundary any qualification crosses."""
        cache = self._effective_cache
        if cache and cache[0] <= now < cache[1]:
            return cache[2]
        out: dict[str, Qualification] = {}
        next_boundary = datetime.max.replace(tzinfo=timezone.utc)
        for qid, q in self.qualifications.items():
            state = q.state
            if state == QUALIFIED:
                issued, expires = _parse_time(q.issued_at), _parse_time(q.expires_at)
                if issued is None or expires is None:
                    state = INVALID
                elif now < issued:
                    state, next_boundary = PENDING, min(next_boundary, issued)
                elif now >= expires:
                    state = EXPIRED
                else:
                    next_boundary = min(next_boundary, expires)
            out[qid] = q if state == q.state else Qualification(**{**q.__dict__, "state": state})
        self._effective_cache[:] = [now, next_boundary, out]
        return out


def _invalid_snapshot(problems: Iterable[str], catalog: CapabilityCatalog | None = None,
                      anti_rollback: str = "unknown") -> CaisSnapshot:
    return CaisSnapshot(False, tuple(problems), catalog, {}, None, None, anti_rollback, _now().isoformat())


def build_snapshot(authority_dir: Path, gateway_ledger: Path | None, head_file: Path | None) -> CaisSnapshot:
    """Derive qualification state from the authoritative directory and the gateway suspension ledger. Any doubt about
    the integrity of either ledger invalidates the whole snapshot (CAIS requests then fail closed)."""
    try:
        catalog = CapabilityCatalog.from_json((authority_dir / "capabilities.json").read_bytes())
    except OSError as error:
        return _invalid_snapshot([f"capabilities_unreadable: {error.__class__.__name__}"])
    except CaisConfigError as error:
        return _invalid_snapshot([f"capabilities_invalid: {error}"])

    authoritative = read_ledger(authority_dir / "ledger.jsonl")
    if not authoritative.intact:
        return _invalid_snapshot([f"authoritative_ledger: {p}" for p in authoritative.problems] or
                                 ["authoritative_ledger_broken"], catalog)
    gateway = read_ledger(gateway_ledger) if gateway_ledger else LedgerRead((), True, None, ())
    if not gateway.intact:
        return _invalid_snapshot([f"gateway_ledger: {p}" for p in gateway.problems] or ["gateway_ledger_broken"], catalog)

    anti_rollback, rollback_problem = _check_head(head_file, authoritative)
    if rollback_problem:
        return _invalid_snapshot([rollback_problem], catalog, anti_rollback)

    problems: list[str] = []
    grants: dict[str, dict[str, Any]] = {}
    removals: dict[str, list[dict[str, Any]]] = {}
    reinstatements: dict[str, list[dict[str, Any]]] = {}
    for record in authoritative.records:
        event = record.get("event")
        if event not in AUTHORITATIVE_EVENTS:
            problems.append(f"authoritative_ledger: unknown event {event!r}")
            return _invalid_snapshot(problems, catalog, anti_rollback)
        qid = record.get("qualification_id")
        if event == "qualification_granted":
            if not isinstance(qid, str) or not qid or qid in grants:
                return _invalid_snapshot([f"authoritative_ledger: duplicate or missing qualification_id {qid!r}"],
                                         catalog, anti_rollback)
            grants[qid] = record
        elif event == "qualification_reinstated":
            reinstatements.setdefault(str(qid), []).append(record)
        elif event in REMOVAL_EVENTS:
            removals.setdefault(str(qid), []).append({**record, "source": "authoritative"})
    for record in gateway.records:
        event = record.get("event")
        if event not in GATEWAY_EVENTS:
            # The gateway may only ever remove eligibility. A grant-type record here is tampering.
            return _invalid_snapshot([f"gateway_ledger: forbidden event {event!r}"], catalog, anti_rollback)
        if event in REMOVAL_EVENTS:
            removals.setdefault(str(record.get("qualification_id")), []).append({**record, "source": "gateway"})

    for qid in set(removals) | set(reinstatements):
        if qid not in grants:
            problems.append(f"reference to unknown qualification {qid!r}")  # recorded, never grants anything

    qualifications: dict[str, Qualification] = {}
    for qid, grant in grants.items():
        qualifications[qid] = _derive(qid, grant, catalog, authority_dir, removals.get(qid, []),
                                      reinstatements.get(qid, []))
    return CaisSnapshot(True, tuple(problems), catalog, qualifications, authoritative.head, gateway.head,
                        anti_rollback, _now().isoformat())


def _check_head(head_file: Path | None, ledger: LedgerRead) -> tuple[str, str | None]:
    """Anti-rollback: the authoritative ledger must extend the longest one this gateway has accepted, so deleting a
    revocation from Git (or restoring an old copy) cannot silently restore eligibility."""
    if head_file is None:
        return "disabled", None
    count = len(ledger.records)
    try:
        if head_file.exists():
            seen = json.loads(head_file.read_text(encoding="utf-8"))
            seen_count, seen_head = int(seen["count"]), seen["head"]
            if count < seen_count or (seen_count and ledger.records[seen_count - 1].get("record_hash") != seen_head):
                return "violated", (f"authoritative_ledger_rollback: accepted {seen_count} records ending "
                                    f"{str(seen_head)[:16]}, now {count}")
    except (OSError, ValueError, KeyError, TypeError) as error:
        return "unreadable", f"anti_rollback_state_unreadable: {error.__class__.__name__}"
    try:
        tmp = head_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"count": count, "head": ledger.head}), encoding="utf-8")
        tmp.replace(head_file)
    except OSError:
        return "degraded", None  # current state is still correct; future rollback detection is not guaranteed
    return "enforced", None


def _derive(qid: str, grant: dict[str, Any], catalog: CapabilityCatalog, authority_dir: Path,
            removals: list[dict[str, Any]], reinstatements: list[dict[str, Any]]) -> Qualification:
    reasons: list[str] = []
    capability = grant.get("capability")
    definition = catalog.capabilities.get(capability) if isinstance(capability, str) else None
    bundle_name = grant.get("bundle") if isinstance(grant.get("bundle"), str) else ""
    lower = 0.0
    reasoning = grant.get("reasoning") if isinstance(grant.get("reasoning"), dict) else {}
    envelope = grant.get("context_envelope") if isinstance(grant.get("context_envelope"), int) else 0
    state = QUALIFIED
    if definition is None:
        state, reasons = INVALID, ["capability_undefined"]
    elif grant.get("capability_version") != definition.version:
        state, reasons = SUPERSEDED, ["capability_version_changed"]
    else:
        reasons = _verify_grant(grant, definition, authority_dir, bundle_name)
        try:
            RoutePolicy.from_config(reasoning or None)
        except (ValueError, TypeError):
            reasons = reasons or ["reasoning_policy_invalid"]
        if not reasons:
            bundle = json.loads((authority_dir / "bundles" / bundle_name).read_bytes())
            assessment = assess_bundle(bundle, definition)
            lower = assessment.functional["pass_lower_bound"]
            if not assessment.qualified:
                reasons = [f"assessment:{r}" for r in assessment.reasons]
            elif reasoning != bundle.get("reasoning") or envelope != bundle.get("context_envelope"):
                reasons = ["grant_scope_exceeds_evidence"]
        if reasons:
            state = INVALID

    # Removal precedence: revoked (terminal) > suspended (until every suspension is explicitly lifted) > qualified.
    lifted = {lid for r in reinstatements for lid in (r.get("lifts") or []) if isinstance(lid, str)}
    revoked = [r for r in removals if r.get("event") == "qualification_revoked"]
    active = tuple(sorted(r["evidence_id"] for r in removals
                          if r.get("event") == "qualification_suspended" and r.get("evidence_id") not in lifted))
    if state not in (INVALID, SUPERSEDED):
        if revoked:
            state = REVOKED
            reasons = [f"revoked:{r.get('reason_code', 'unspecified')}" for r in revoked]
        elif active:
            state = SUSPENDED
            reasons = [f"suspended:{r.get('reason_code', 'unspecified')}" for r in removals
                       if r.get("evidence_id") in active]
    return Qualification(
        qualification_id=qid, capability=str(capability), capability_version=int(grant.get("capability_version") or 0),
        profile_digest=str(grant.get("profile_digest")), reasoning=dict(reasoning), context_envelope=envelope,
        independence=str(grant.get("independence")), issued_at=str(grant.get("issued_at")),
        expires_at=str(grant.get("expires_at")), authority=str(grant.get("authority")), bundle=bundle_name,
        bundle_sha256=str(grant.get("bundle_sha256")), grant_evidence_id=str(grant.get("evidence_id")),
        state=state, reasons=tuple(reasons), pass_lower_bound=lower, active_suspensions=active,
    )


def _verify_grant(grant: dict[str, Any], definition: CapabilityDefinition, authority_dir: Path,
                  bundle_name: str) -> list[str]:
    for key in ("profile", "profile_digest", "issued_at", "expires_at", "authority", "bundle_sha256", "independence"):
        if not grant.get(key):
            return [f"grant_missing_{key}"]
    if not isinstance(grant.get("profile"), dict) or profile_digest(grant["profile"]) != grant["profile_digest"]:
        return ["grant_profile_digest_mismatch"]
    issued, expires = _parse_time(grant["issued_at"]), _parse_time(grant["expires_at"])
    if issued is None or expires is None or expires <= issued:
        return ["grant_validity_window_invalid"]
    if expires - issued > timedelta(days=definition.criteria.max_validity_days):
        return ["grant_validity_exceeds_policy"]
    if not _SAFE_FILE.match(bundle_name):
        return ["bundle_path_invalid"]
    path = authority_dir / "bundles" / bundle_name
    try:
        data = path.read_bytes()
    except OSError:
        return ["bundle_missing"]
    if _sha256_bytes(data) != grant["bundle_sha256"]:
        return ["bundle_digest_mismatch"]
    try:
        bundle = json.loads(data)
    except ValueError:
        return ["bundle_not_json"]
    if not isinstance(bundle, dict):
        return ["bundle_not_object"]
    if bundle.get("profile_digest") != grant["profile_digest"] or not isinstance(bundle.get("profile"), dict) \
            or profile_digest(bundle["profile"]) != grant["profile_digest"]:
        return ["bundle_profile_mismatch"]
    if bundle.get("independence") != grant["independence"]:
        return ["grant_independence_exceeds_evidence"]
    return []


# ======================================================================================================= requests
@dataclass(frozen=True)
class CaisRequirement:
    capability: str
    min_context: int = 0
    priority: str = "quality"
    fallback: str = "qualified_only"

    @classmethod
    def from_headers(cls, get: Callable[[str], str | None]) -> "CaisRequirement | None":
        """None when the request carries no capability header (legacy routing). Raises ValueError on a malformed one."""
        capability = get("X-AIHost-Capability")
        if capability is None:
            return None
        capability = capability.strip()
        if not capability:
            raise ValueError("X-AIHost-Capability must not be empty")
        qualification = (get("X-AIHost-Qualification") or "required").strip().lower()
        if qualification != "required":
            # Only one contract exists: a capability request always requires an effective qualification. A client
            # that does not need one simply omits the capability header.
            raise ValueError("X-AIHost-Qualification must be 'required'")
        raw_context = get("X-AIHost-Min-Context")
        min_context = 0
        if raw_context is not None:
            if not raw_context.strip().isdigit():
                raise ValueError("X-AIHost-Min-Context must be a non-negative integer")
            min_context = int(raw_context)
        priority = (get("X-AIHost-Routing-Priority") or "quality").strip().lower()
        if priority not in PRIORITIES:
            raise ValueError(f"X-AIHost-Routing-Priority must be one of {list(PRIORITIES)}")
        fallback = (get("X-AIHost-Fallback") or "qualified_only").strip().lower()
        if fallback not in FALLBACKS:
            raise ValueError(f"X-AIHost-Fallback must be one of {list(FALLBACKS)}")
        return cls(capability, min_context, priority, fallback)

    def describe(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class Candidate:
    worker_id: str
    qualification: Qualification
    rank_key: tuple[Any, ...]


@dataclass(frozen=True)
class CaisEvaluation:
    decision_id: str
    requirement: CaisRequirement
    candidates: tuple[Candidate, ...]
    rejected: Mapping[str, str]
    failure_class: str | None
    message: str | None
    policy_version: str | None
    snapshot_heads: dict[str, Any]
    required_context: int
    inputs: dict[str, Any] = field(default_factory=dict)

    def describe(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id, "requirement": self.requirement.describe(),
            "policy_version": self.policy_version, "required_context": self.required_context,
            "eligible": [{"worker_id": c.worker_id, "qualification_id": c.qualification.qualification_id,
                          "rank_key": list(c.rank_key)} for c in self.candidates],
            "rejected": dict(sorted(self.rejected.items())), "failure_class": self.failure_class,
            "ledger_heads": self.snapshot_heads, "inputs": self.inputs,
        }


# Rejection reason -> the failure a client sees when nothing better is available, most informative first.
_REASON_FAILURE = (
    ("context_unsupported", "context_unsupported"),
    ("qualification_revoked", "qualification_revoked"),
    ("qualification_suspended", "qualification_suspended"),
    ("qualification_expired", "qualification_expired"),
)


class CaisService:
    """Holds the current snapshot, evaluates requirements and records gateway-side suspensions."""

    def __init__(self, mode: str, authority_dir: str | Path | None, state_dir: str | Path | None, *,
                 evidence: Any = None, metrics: Any = None, clock: Callable[[], datetime] = _now) -> None:
        # An unrecognised mode must neither crash the gateway (legacy routing stays up) nor disable enforcement
        # silently: it enforces with an invalid state, so every capability request fails closed until fixed.
        self.mode = mode if mode in MODES else "enforce"
        self._mode_problem = None if mode in MODES else f"invalid_mode: {mode!r}"
        self.authority_dir = Path(authority_dir) if authority_dir else None
        state = Path(state_dir) if state_dir else None
        self.gateway_ledger = state / "cais-suspensions.jsonl" if state else None
        self.head_file = state / "cais-authoritative-head.json" if state else None
        self.evidence = evidence
        self.metrics = metrics
        self.clock = clock
        self._lock = threading.RLock()
        self._snapshot = _invalid_snapshot(["not_loaded"])
        if self.mode == "enforce":
            self.reload()

    @property
    def enabled(self) -> bool:
        return self.mode == "enforce"

    @property
    def snapshot(self) -> CaisSnapshot:
        with self._lock:
            return self._snapshot

    def reload(self) -> CaisSnapshot:
        with self._lock:
            if self._mode_problem:
                snapshot = _invalid_snapshot([self._mode_problem])
            elif self.authority_dir is None:
                snapshot = _invalid_snapshot(["authority_dir_unconfigured"])
            else:
                try:
                    snapshot = build_snapshot(self.authority_dir, self.gateway_ledger, self.head_file)
                except Exception as error:  # noqa: BLE001 - any failure to derive state fails CAIS closed
                    snapshot = _invalid_snapshot([f"load_failed: {error.__class__.__name__}: {error}"])
            self._snapshot = snapshot
        self._observe(snapshot)
        if self.evidence is not None:
            try:
                self.evidence.append("cais_state_loaded", valid=snapshot.valid, problems=list(snapshot.problems)[:20],
                                     policy_version=snapshot.catalog.policy_version if snapshot.catalog else None,
                                     authoritative_head=snapshot.authoritative_head,
                                     gateway_head=snapshot.gateway_head, anti_rollback=snapshot.anti_rollback,
                                     qualifications={q: s.state for q, s in snapshot.qualifications.items()})
            except Exception:  # noqa: BLE001 - evidence failure must not change the derived state
                pass
        return snapshot

    def _observe(self, snapshot: CaisSnapshot) -> None:
        if self.metrics is None or not hasattr(self.metrics, "cais_state_valid"):
            return
        self.metrics.cais_state_valid.set(1.0 if snapshot.valid else 0.0)
        counts: dict[tuple[str, str], int] = {}
        catalog = snapshot.catalog.capabilities if snapshot.catalog else {}
        for name in catalog:
            for state in STATES:
                counts[(name, state)] = 0
        for q in snapshot.effective(self.clock()).values():
            if q.capability in catalog:
                counts[(q.capability, q.state)] = counts.get((q.capability, q.state), 0) + 1
        for (capability, state), value in counts.items():
            self.metrics.cais_qualifications.set(value, capability=capability, state=state)

    # ------------------------------------------------------------------ removal (fail-safe direction only)
    def suspend(self, qualification_id: str, *, reason_code: str, authority: str, revoke: bool = False,
                detail: str | None = None) -> dict[str, Any]:
        """Record a gateway-side suspension or revocation. It can only remove eligibility; lifting a suspension needs
        an authoritative ``qualification_reinstated`` record, and a revocation needs a new grant."""
        if self.gateway_ledger is None:
            raise OSError("CAIS state directory is not configured; cannot persist a suspension")
        if not re.match(r"^[a-z][a-z0-9_]{0,63}$", reason_code or ""):
            raise ValueError("reason_code must be a short snake_case identifier")
        with self._lock:
            known = self._snapshot.qualifications.get(qualification_id)
            if known is None:
                raise KeyError(qualification_id)
            event = "qualification_revoked" if revoke else "qualification_suspended"
            record = append_ledger(self.gateway_ledger, event, qualification_id=qualification_id,
                                   reason_code=reason_code, authority=authority,
                                   detail=(detail or "")[:500] or None)
            snapshot = self.reload()
        if self.metrics is not None and hasattr(self.metrics, "cais_suspensions_total"):
            self.metrics.cais_suspensions_total.inc(action="revoke" if revoke else "suspend", source="gateway")
        return {"status": "recorded", "event": event, "evidence_id": record["evidence_id"],
                "qualification_id": qualification_id,
                "state": snapshot.qualifications.get(qualification_id).state
                if snapshot.qualifications.get(qualification_id) else None}

    # ------------------------------------------------------------------ evaluation
    def evaluate(self, requirement: CaisRequirement, workers: Iterable[Any], *, required_context: int,
                 restrict_to: set[str] | None = None, latency_ms: Mapping[str, float] | None = None) -> CaisEvaluation:
        """Filter workers to those whose execution profile holds an effective qualification for the requirement, and
        rank them deterministically. ``restrict_to`` narrows to the workers an explicit model/alias/pin names."""
        snapshot = self.snapshot
        decision_id = str(uuid.uuid4())
        heads = {"authoritative": snapshot.authoritative_head, "gateway": snapshot.gateway_head,
                 "anti_rollback": snapshot.anti_rollback}
        policy_version = snapshot.catalog.policy_version if snapshot.catalog else None
        needed = max(requirement.min_context, required_context)

        def deny(failure: str, message: str, rejected: Mapping[str, str] | None = None) -> CaisEvaluation:
            return CaisEvaluation(decision_id, requirement, (), dict(rejected or {}), failure, message, policy_version,
                                  heads, needed)

        if not self.enabled:
            return deny("cais_disabled", "capability-aware routing is not enabled on this gateway")
        if not snapshot.valid or snapshot.catalog is None:
            return deny("qualification_state_unavailable",
                        "authoritative qualification state could not be established; refusing qualified routing")
        definition = snapshot.catalog.capabilities.get(requirement.capability)
        if definition is None:
            return deny("capability_unknown", f"unknown capability {requirement.capability!r}; known: "
                        f"{sorted(snapshot.catalog.capabilities)}")
        effective = snapshot.effective(self.clock())
        by_profile: dict[str, list[Qualification]] = {}
        for q in effective.values():
            if q.capability == definition.name and q.capability_version == definition.version:
                by_profile.setdefault(q.profile_digest, []).append(q)
            elif q.capability == definition.name:
                by_profile.setdefault(q.profile_digest, []).append(q)  # superseded/invalid: kept for the reason
        rejected: dict[str, str] = {}
        candidates: list[Candidate] = []
        for worker in sorted(workers, key=lambda w: w.worker_id):
            if restrict_to is not None and worker.worker_id not in restrict_to:
                rejected[worker.worker_id] = "not_requested"
                continue
            if getattr(worker, "role", "production") != "production":
                rejected[worker.worker_id] = "candidate_role"
                continue
            matches = by_profile.get(profile_digest(profile_identity(worker)), [])
            active = [q for q in matches if q.state == QUALIFIED]
            if not active:
                rejected[worker.worker_id] = _strongest_reason(matches)
                continue
            fitting = [q for q in active if needed <= min(q.context_envelope, int(worker.context_limit))]
            if not fitting:
                rejected[worker.worker_id] = "context_unsupported"
                continue
            # Several effective qualifications for one profile: the strongest evidence, then the newest, then the id.
            best = sorted(fitting, key=lambda q: (-q.pass_lower_bound, q.issued_at, q.qualification_id))[0]
            if requirement.priority == "latency":
                key: tuple[Any, ...] = (round(float((latency_ms or {}).get(worker.worker_id, 1e9)), 1),
                                        -best.pass_lower_bound, worker.worker_id)
            else:
                key = (-best.pass_lower_bound, round(float((latency_ms or {}).get(worker.worker_id, 1e9)), 1),
                       worker.worker_id)
            candidates.append(Candidate(worker.worker_id, best, key))
        candidates.sort(key=lambda c: c.rank_key)
        inputs = {"latency_ms": {c.worker_id: (latency_ms or {}).get(c.worker_id) for c in candidates},
                  "now": self.clock().isoformat()}
        if not candidates:
            failure = "no_qualified_model"
            reasons = set(rejected.values())
            for reason, mapped in _REASON_FAILURE:
                if reason in reasons:
                    failure = mapped
                    break
            if restrict_to is not None and reasons <= {"not_requested"}:
                failure = "policy_denied"
            return CaisEvaluation(decision_id, requirement, (), rejected, failure,
                                  f"no execution profile holds an effective {definition.name!r} qualification "
                                  f"for this request ({failure})", policy_version, heads, needed, inputs)
        if requirement.fallback == "none":
            for extra in candidates[1:]:
                rejected[extra.worker_id] = "fallback_prohibited"
            candidates = candidates[:1]
        return CaisEvaluation(decision_id, requirement, tuple(candidates), rejected, None, None, policy_version,
                              heads, needed, inputs)

    def still_effective(self, qualification_id: str) -> str | None:
        """Re-check at dispatch time (after queueing). None when still qualified, else the state that now applies."""
        q = self.snapshot.effective(self.clock()).get(qualification_id)
        if q is None:
            return INVALID
        return None if q.state == QUALIFIED else q.state

    def status(self) -> dict[str, Any]:
        snapshot = self.snapshot
        return {
            "mode": self.mode, "valid": snapshot.valid, "problems": list(snapshot.problems),
            "policy_version": snapshot.catalog.policy_version if snapshot.catalog else None,
            "catalog_digest": snapshot.catalog.digest if snapshot.catalog else None,
            "capabilities": {n: d.describe() for n, d in (snapshot.catalog.capabilities.items()
                                                          if snapshot.catalog else [])},
            "qualifications": {q: v.describe() for q, v in sorted(snapshot.effective(self.clock()).items())},
            "ledger_heads": {"authoritative": snapshot.authoritative_head, "gateway": snapshot.gateway_head},
            "anti_rollback": snapshot.anti_rollback, "loaded_at": snapshot.loaded_at,
        }


def _strongest_reason(matches: list[Qualification]) -> str:
    if not matches:
        return "no_qualification"
    states = {q.state for q in matches}
    for state, reason in ((REVOKED, "qualification_revoked"), (SUSPENDED, "qualification_suspended"),
                          (EXPIRED, "qualification_expired"), (PENDING, "qualification_pending"),
                          (SUPERSEDED, "qualification_superseded"), (INVALID, "qualification_invalid")):
        if state in states:
            return reason
    return "no_qualification"
