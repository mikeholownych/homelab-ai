"""Operator CLI for the CAIS authoritative ledger (docs/design/07, docs/operations/cais.md).

Runs on the controller against the Git working tree (``inventory/production/cais`` by default); the result is reviewed,
committed and delivered read-only to the gateway by Ansible. The gateway re-verifies every grant at load, so this tool
is a convenience and a pre-commit check, not a trust anchor.

  python3 -m orchestrator_runtime.cais_cli assess    <dir> --bundle FILE
  python3 -m orchestrator_runtime.cais_cli grant     <dir> --bundle FILE --authority WHO [--valid-days N]
  python3 -m orchestrator_runtime.cais_cli suspend   <dir> QID --reason CODE --authority WHO
  python3 -m orchestrator_runtime.cais_cli revoke    <dir> QID --reason CODE --authority WHO
  python3 -m orchestrator_runtime.cais_cli reinstate <dir> QID --lifts EVIDENCE_ID[,..] --reason CODE --authority WHO
  python3 -m orchestrator_runtime.cais_cli verify    <dir> [--gateway-ledger FILE] [--workers SPECS.json]

There is deliberately no ``--force``: a bundle that does not meet the current criteria cannot be granted. An
administrative exception is expressed by changing the versioned criteria (reviewed in Git), never by rewriting evidence.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

from . import cais


def _load_bundle(path: Path) -> tuple[dict[str, Any], bytes]:
    data = path.read_bytes()
    bundle = json.loads(data)
    if not isinstance(bundle, dict):
        raise SystemExit("bundle must be a JSON object")
    return bundle, data


def _catalog(directory: Path) -> cais.CapabilityCatalog:
    return cais.CapabilityCatalog.from_json((directory / "capabilities.json").read_bytes())


def _assess(directory: Path, bundle: dict[str, Any]) -> tuple[cais.CapabilityDefinition, cais.Assessment]:
    catalog = _catalog(directory)
    definition = catalog.capabilities.get(str(bundle.get("capability")))
    if definition is None:
        raise SystemExit(f"capability {bundle.get('capability')!r} is not defined in {directory}/capabilities.json")
    return definition, cais.assess_bundle(bundle, definition)


def cmd_assess(args: argparse.Namespace) -> int:
    bundle, _ = _load_bundle(Path(args.bundle))
    _definition, assessment = _assess(Path(args.dir), bundle)
    print(json.dumps(assessment.describe(), indent=1, sort_keys=True))
    return 0 if assessment.qualified else 1


def cmd_grant(args: argparse.Namespace) -> int:
    directory = Path(args.dir)
    bundle, data = _load_bundle(Path(args.bundle))
    definition, assessment = _assess(directory, bundle)
    if not assessment.qualified:
        print(json.dumps({"granted": False, "assessment": assessment.describe()}, indent=1, sort_keys=True))
        return 1
    profile = bundle.get("profile")
    if not isinstance(profile, dict) or cais.profile_digest(profile) != bundle.get("profile_digest"):
        raise SystemExit("bundle profile digest does not match its profile identity")
    days = args.valid_days or definition.criteria.max_validity_days
    if days > definition.criteria.max_validity_days:
        raise SystemExit(f"--valid-days exceeds the policy maximum of {definition.criteria.max_validity_days}")
    digest = cais._sha256_bytes(data)
    run_id = re.sub(r"[^A-Za-z0-9._-]", "-", str(bundle.get("run_id") or digest[7:23]))[:120]
    name = f"{run_id}.json"
    target = directory / "bundles" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and cais._sha256_bytes(target.read_bytes()) != digest:
        raise SystemExit(f"a different bundle already exists at {target}")
    shutil.copyfile(args.bundle, target)
    issued = cais._now().replace(microsecond=0)
    qid = f"q-{definition.name}-{bundle['profile_digest'][7:19]}-{digest[7:15]}"
    record = cais.append_ledger(
        directory / "ledger.jsonl", "qualification_granted", qualification_id=qid, capability=definition.name,
        capability_version=definition.version, profile=profile, profile_digest=bundle["profile_digest"],
        reasoning=bundle.get("reasoning") or {}, context_envelope=bundle.get("context_envelope"),
        independence=bundle.get("independence"), bundle=name, bundle_sha256=digest,
        issued_at=issued.isoformat(), expires_at=(issued + timedelta(days=days)).isoformat(),
        authority=args.authority, assessment=assessment.describe())
    print(json.dumps({"granted": True, "qualification_id": qid, "evidence_id": record["evidence_id"],
                      "expires_at": record["expires_at"]}, indent=1))
    return 0


def _removal(args: argparse.Namespace, event: str, **extra: Any) -> int:
    directory = Path(args.dir)
    snapshot = cais.build_snapshot(directory, None, None)
    if args.qualification_id not in snapshot.qualifications:
        raise SystemExit(f"unknown qualification {args.qualification_id!r}")
    record = cais.append_ledger(directory / "ledger.jsonl", event, qualification_id=args.qualification_id,
                                reason_code=args.reason, authority=args.authority, **extra)
    print(json.dumps({"event": event, "evidence_id": record["evidence_id"]}, indent=1))
    return 0


def cmd_reinstate(args: argparse.Namespace) -> int:
    lifts = [item for item in args.lifts.split(",") if item]
    if not lifts:
        raise SystemExit("--lifts must name the suspension evidence ids being lifted")
    return _removal(args, "qualification_reinstated", lifts=lifts)


def cmd_verify(args: argparse.Namespace) -> int:
    directory = Path(args.dir)
    snapshot = cais.build_snapshot(directory, Path(args.gateway_ledger) if args.gateway_ledger else None, None)
    out: dict[str, Any] = {"valid": snapshot.valid, "problems": list(snapshot.problems),
                           "policy_version": snapshot.catalog.policy_version if snapshot.catalog else None,
                           "qualifications": {q: {"state": v.state, "capability": v.capability,
                                                  "profile_digest": v.profile_digest, "reasons": list(v.reasons),
                                                  "expires_at": v.expires_at}
                                              for q, v in snapshot.effective(cais._now()).items()}}
    if args.workers:
        workers = json.loads(Path(args.workers).read_text(encoding="utf-8"))
        out["workers"] = {w["worker_id"]: cais.profile_digest(cais.profile_identity(w)) for w in workers}
    print(json.dumps(out, indent=1, sort_keys=True))
    return 0 if snapshot.valid else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cais_cli", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("assess"); p.add_argument("dir"); p.add_argument("--bundle", required=True)
    p.set_defaults(func=cmd_assess)
    p = sub.add_parser("grant"); p.add_argument("dir"); p.add_argument("--bundle", required=True)
    p.add_argument("--authority", required=True); p.add_argument("--valid-days", type=int)
    p.set_defaults(func=cmd_grant)
    for name, event in (("suspend", "qualification_suspended"), ("revoke", "qualification_revoked")):
        p = sub.add_parser(name); p.add_argument("dir"); p.add_argument("qualification_id")
        p.add_argument("--reason", required=True); p.add_argument("--authority", required=True)
        p.set_defaults(func=lambda a, e=event: _removal(a, e))
    p = sub.add_parser("reinstate"); p.add_argument("dir"); p.add_argument("qualification_id")
    p.add_argument("--lifts", required=True); p.add_argument("--reason", required=True)
    p.add_argument("--authority", required=True); p.set_defaults(func=cmd_reinstate)
    p = sub.add_parser("verify"); p.add_argument("dir"); p.add_argument("--gateway-ledger")
    p.add_argument("--workers"); p.set_defaults(func=cmd_verify)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
