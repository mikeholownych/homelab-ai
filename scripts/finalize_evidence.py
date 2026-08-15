from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from scripts import validate_contract


TARGET_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
RECAP_PATTERN = re.compile(
    r"^(?P<host>\S+)\s*:\s*"
    r"ok=(?P<ok>\d+)\s+"
    r"changed=(?P<changed>\d+)\s+"
    r"unreachable=(?P<unreachable>\d+)\s+"
    r"failed=(?P<failed>\d+)\s+"
    r"skipped=(?P<skipped>\d+)\s+"
    r"rescued=(?P<rescued>\d+)\s+"
    r"ignored=(?P<ignored>\d+)\s*$"
)
RECAP_COUNTER_KEYS = ("ok", "changed", "unreachable", "failed", "skipped", "rescued", "ignored")
SUPPORTED_CONTRACTS = {
    "validation.json": "validation",
    "benchmark.json": "benchmark",
    "cmdb.json": "cmdb",
    "itsm.json": "itsm",
}
TRANSIENT_SUFFIXES = (".tmp", ".swp", ".swo", ".lock", "~")


def utc_timestamp_now() -> str:
    return __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_json_error(path: Path, exc: Exception) -> str:
    if isinstance(exc, json.JSONDecodeError):
        return f"{path.name} json_decode_error"
    if isinstance(exc, OSError):
        return f"{path.name} io_error"
    return f"{path.name} json_error"


def safe_contract_error(path: Path) -> str:
    return f"{path.name} validation_error"


def is_transient_relative_path(relative_path: str) -> bool:
    name = Path(relative_path).name
    if name == "SHA256SUMS":
        return True
    if name.startswith(".tmp-"):
        return True
    return name.endswith(TRANSIENT_SUFFIXES)


def default_target_for_run_dir(run_dir: Path) -> str:
    candidate = run_dir.parent.name
    if TARGET_PATTERN.fullmatch(candidate):
        return candidate
    return "unknown-target"


def default_manifest(run_dir: Path, repo_root: Path) -> dict[str, Any]:
    now = utc_timestamp_now()
    target = default_target_for_run_dir(run_dir)
    return {
        "schema_version": "1.1.0",
        "generated_at": now,
        "git_sha": "0" * 40,
        "simulated": False,
        "status": "incomplete",
        "collection_target": {
            "node_id": target,
            "adapter": "ansible",
        },
        "artifacts": [
            {
                "id": "ansible-log",
                "kind": "text/plain",
                "expected": {
                    "summary": "Ansible combined stdout and stderr log",
                    "path": "ansible.log",
                },
                "observed": {
                    "summary": "Pending finalization",
                    "status": "unavailable",
                    "reason": "pending finalization",
                },
            },
            {
                "id": "ansible-run",
                "kind": "application/json",
                "expected": {
                    "summary": "Ansible execution metadata",
                    "path": "ansible-run.json",
                },
                "observed": {
                    "summary": "Pending finalization",
                    "status": "unavailable",
                    "reason": "pending finalization",
                },
            },
        ],
        "run": {
            "directory_name": run_dir.name,
            "started_at": now,
            "finished_at": now,
            "inventory": "inventory/unknown/hosts.yml",
            "playbook": "validate.yml",
            "limit": target,
            "lock": {
                "path": "",
                "status": "acquired",
            },
            "repository": {
                "root": str(repo_root),
                "clean": True,
                "allowlist": ["evidence/", ".pytest_cache/", ".mypy_cache/", ".ansible/"],
            },
            "ansible": {
                "exit_code": 0,
                "recap": None,
            },
            "validation": {
                "status": "NOT_TESTED",
                "classification": "incomplete",
            },
        },
        "finalization": {
            "state": "incomplete",
            "reason": "pending finalization",
            "completed_at": now,
        },
    }


def load_json_document(path: Path) -> tuple[Any | None, str | None]:
    try:
        return load_json(path), None
    except Exception as exc:  # pragma: no cover - exercised via CLI subprocess tests
        return None, safe_json_error(path, exc)


def atomic_write_json(path: Path, payload: object) -> None:
    atomic_write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_file: tempfile.NamedTemporaryFile[str] | None = None
    try:
        temp_file = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".tmp-",
            delete=False,
        )
        with temp_file:
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_file.name, path)
    finally:
        if temp_file is not None:
            temp_path = Path(temp_file.name)
            if temp_path.exists():
                temp_path.unlink()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_recap(text: str) -> dict[str, dict[str, object]]:
    totals = {key: 0 for key in RECAP_COUNTER_KEYS}
    hosts: dict[str, dict[str, int]] = {}
    seen_recap = False
    in_recap = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("PLAY RECAP"):
            seen_recap = True
            in_recap = True
            continue
        if not in_recap:
            continue

        match = RECAP_PATTERN.match(line)
        if match:
            counters = {key: int(match.group(key)) for key in RECAP_COUNTER_KEYS}
            host = match.group("host")
            host_totals = hosts.setdefault(host, {key: 0 for key in RECAP_COUNTER_KEYS})
            for key, value in counters.items():
                host_totals[key] += value
                totals[key] += value
            continue

        if any(token in line for token in ("ok=", "changed=", "unreachable=", "failed=", "skipped=", "rescued=", "ignored=")):
            raise ValueError("ansible recap contains a malformed host line")

        if line.startswith(("PLAY ", "TASK ", "RUN ", "META:")):
            in_recap = False

    if not seen_recap or not hosts:
        raise ValueError("ansible recap was not found or could not be parsed")

    return {
        "totals": totals,
        "hosts": hosts,
    }


def sanitize_reason(message: str) -> str:
    return " ".join(message.strip().split())


def expected_validation_artifact(manifest: dict[str, Any]) -> bool:
    return any(
        artifact.get("expected", {}).get("path") == "validation.json"
        for artifact in manifest.get("artifacts", [])
        if isinstance(artifact, dict)
    )


def is_safe_regular_file(path: Path, run_dir: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    try:
        path.resolve(strict=True).relative_to(run_dir.resolve())
    except (FileNotFoundError, ValueError):
        return False
    return True


def update_artifact_observations(manifest: dict[str, Any], run_dir: Path) -> None:
    observed_at = manifest["generated_at"]
    for artifact in manifest["artifacts"]:
        expected_path = artifact["expected"]["path"]
        artifact_path = run_dir / expected_path
        if artifact_path.exists() and is_safe_regular_file(artifact_path, run_dir):
            artifact["observed"] = {
                "summary": f"Captured {artifact['id']}",
                "path": expected_path,
                "sha256": sha256_file(artifact_path),
                "observed_at": observed_at,
            }
        else:
            artifact["observed"] = {
                "summary": f"Expected artifact missing for {artifact['id']}",
                "status": "unavailable",
                "reason": f"missing file: {expected_path}",
            }


def component_files_for_checksums(run_dir: Path) -> tuple[list[Path], list[str]]:
    files: list[Path] = []
    issues: list[str] = []
    resolved_run_dir = run_dir.resolve()
    for path in sorted(run_dir.rglob("*"), key=lambda item: item.relative_to(run_dir).as_posix()):
        relative_path = path.relative_to(run_dir).as_posix()
        if is_transient_relative_path(relative_path):
            continue
        if path.is_symlink():
            issues.append(f"{relative_path} symlink_not_allowed")
            continue
        if not path.is_file():
            continue
        try:
            path.resolve(strict=True).relative_to(resolved_run_dir)
        except (FileNotFoundError, ValueError):
            issues.append(f"{relative_path} outside_run_dir")
            continue
        files.append(path)
    return files, issues


def write_checksums(run_dir: Path) -> list[str]:
    files, issues = component_files_for_checksums(run_dir)
    lines = [f"{sha256_file(path)}  {path.relative_to(run_dir).as_posix()}" for path in files]
    atomic_write_text(run_dir / "SHA256SUMS", "\n".join(lines) + ("\n" if lines else ""))
    return issues


def validate_component_json(run_dir: Path, schema_root: Path) -> list[str]:
    errors: list[str] = []
    for path in sorted(run_dir.glob("*.json")):
        contract_type = SUPPORTED_CONTRACTS.get(path.name)
        if contract_type is None:
            continue
        payload, load_error = load_json_document(path)
        if load_error is not None:
            errors.append(load_error)
            continue
        if not isinstance(payload, dict):
            errors.append(f"{path.name} / keyword=type")
            continue
        try:
            schema_errors = validate_contract.collect_schema_errors(contract_type, payload, schema_root=schema_root)
            semantic_errors = validate_contract.collect_semantic_errors(contract_type, payload)
        except Exception:
            errors.append(safe_contract_error(path))
            continue
        for error in schema_errors + semantic_errors:
            errors.append(f"{path.name} {sanitize_reason(error)}")
    return errors


def validate_manifest_payload(manifest: dict[str, Any], schema_root: Path) -> list[str]:
    try:
        schema_errors = validate_contract.collect_schema_errors("manifest", manifest, schema_root=schema_root)
        semantic_errors = validate_contract.collect_semantic_errors("manifest", manifest)
    except Exception:
        return ["manifest.json validation_error"]
    return [f"manifest.json {sanitize_reason(error)}" for error in schema_errors + semantic_errors]


def discover_recap(run_dir: Path, manifest: dict[str, Any], ansible_run: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    for source in (
        ansible_run.get("recap"),
        manifest.get("run", {}).get("ansible", {}).get("recap"),
    ):
        if isinstance(source, dict):
            return source, None
        if isinstance(source, str) and source.strip():
            try:
                return parse_recap(source), None
            except ValueError as exc:
                return None, sanitize_reason(str(exc))

    log_path = run_dir / "ansible.log"
    if log_path.exists():
        try:
            return parse_recap(log_path.read_text(encoding="utf-8")), None
        except (OSError, ValueError) as exc:
            return None, sanitize_reason(str(exc))
    return None, "ansible recap is missing"


def classify_manifest_status(manifest: dict[str, Any], recap: dict[str, Any] | None) -> tuple[str, str | None]:
    exit_code = manifest["run"]["ansible"]["exit_code"]
    if recap is None:
        return "incomplete", "/run/ansible/recap unavailable"

    failed = recap["totals"]["failed"]
    unreachable = recap["totals"]["unreachable"]
    missing_artifacts = [
        artifact["expected"]["path"]
        for artifact in manifest["artifacts"]
        if artifact.get("observed", {}).get("status") == "unavailable"
    ]
    if exit_code == 0 and failed == 0 and unreachable == 0 and not missing_artifacts:
        return "captured", None

    reasons: list[str] = []
    if exit_code != 0:
        reasons.append(f"/run/ansible/exit_code nonzero")
    if failed:
        reasons.append(f"/run/ansible/recap/totals/failed nonzero")
    if unreachable:
        reasons.append(f"/run/ansible/recap/totals/unreachable nonzero")
    if missing_artifacts:
        reasons.append(f"/artifacts missing {', '.join(sorted(missing_artifacts))}")
    return "incomplete", "; ".join(reasons)


def finalize_run(run_dir: Path, repo_root: Path, schema_root: Path) -> tuple[int, dict[str, Any]]:
    manifest_path = run_dir / "manifest.json"
    ansible_run_path = run_dir / "ansible-run.json"
    errors: list[str] = []
    manifest_payload, manifest_error = load_json_document(manifest_path)
    ansible_run_payload, ansible_run_error = load_json_document(ansible_run_path)

    manifest = manifest_payload if isinstance(manifest_payload, dict) else default_manifest(run_dir, repo_root)
    if manifest_error is not None:
        errors.append(manifest_error)
    elif manifest_payload is not None and not isinstance(manifest_payload, dict):
        errors.append("manifest.json / keyword=type")

    ansible_run: dict[str, Any]
    if isinstance(ansible_run_payload, dict):
        ansible_run = ansible_run_payload
    else:
        ansible_run = {}
        if ansible_run_error is not None:
            errors.append(ansible_run_error)
        elif ansible_run_payload is not None:
            errors.append("ansible-run.json / keyword=type")

    manifest["generated_at"] = utc_timestamp_now()
    manifest["git_sha"] = ansible_run.get("git_sha", manifest.get("git_sha"))
    manifest["simulated"] = bool(ansible_run.get("simulated", manifest.get("simulated", False)))
    manifest["run"]["inventory"] = ansible_run.get("inventory", manifest["run"]["inventory"])
    manifest["run"]["playbook"] = ansible_run.get("playbook", manifest["run"]["playbook"])
    manifest["run"]["limit"] = ansible_run.get("limit", manifest["run"]["limit"])
    manifest["run"]["started_at"] = ansible_run.get("started_at", manifest["run"]["started_at"])
    manifest["run"]["finished_at"] = ansible_run.get("finished_at", manifest["run"]["finished_at"])
    try:
        manifest["run"]["ansible"]["exit_code"] = int(ansible_run.get("exit_code", manifest["run"]["ansible"]["exit_code"]))
    except (TypeError, ValueError):
        errors.append("ansible-run.json /exit_code invalid")
        manifest["run"]["ansible"]["exit_code"] = 1
    manifest["run"]["validation"] = {
        "status": "NOT_TESTED",
        "classification": "incomplete",
    }

    recap, recap_error = discover_recap(run_dir, manifest, ansible_run)
    if recap_error is not None:
        errors.append(recap_error)
        recap = None
    elif recap is not None:
        recap_errors = validate_contract.validate_recap_structure(recap, pointer="/run/ansible/recap")
        if recap_errors:
            errors.append(sanitize_reason(recap_errors[0]))
            recap = None
    manifest["run"]["ansible"]["recap"] = recap

    validation_path = run_dir / "validation.json"
    if validation_path.exists():
        validation_payload, validation_error = load_json_document(validation_path)
        if validation_error is not None:
            errors.append(validation_error)
        elif not isinstance(validation_payload, dict):
            errors.append("validation.json / keyword=type")
        else:
            try:
                validation_errors = validate_contract.collect_schema_errors(
                    "validation",
                    validation_payload,
                    schema_root=schema_root,
                )
                validation_errors.extend(validate_contract.collect_semantic_errors("validation", validation_payload))
            except Exception:
                validation_errors = [safe_contract_error(validation_path)]
            if validation_errors:
                errors.append(f"validation.json {sanitize_reason(validation_errors[0])}" if not validation_errors[0].startswith("validation.json") else sanitize_reason(validation_errors[0]))
            else:
                manifest["run"]["validation"] = {
                    "status": validation_payload["status"],
                    "classification": validation_payload["summary"]["classification"],
                }
    elif expected_validation_artifact(manifest):
        errors.append("validation.json / missing")

    update_artifact_observations(manifest, run_dir)
    manifest_status, status_reason = classify_manifest_status(manifest, recap)
    if errors:
        manifest["status"] = "incomplete"
    else:
        manifest["status"] = manifest_status

    component_errors = validate_component_json(run_dir, schema_root)
    if component_errors:
        errors.append(component_errors[0])
        manifest["status"] = "incomplete"

    completed_at = utc_timestamp_now()
    manifest["finalization"] = {
        "state": "complete" if not errors and manifest["status"] == "captured" else "incomplete",
        "reason": errors[0] if errors else status_reason,
        "completed_at": completed_at,
    }

    manifest_errors = validate_manifest_payload(manifest, schema_root)
    if manifest_errors:
        errors.append(manifest_errors[0])
        manifest["status"] = "incomplete"
        manifest["finalization"] = {
            "state": "incomplete",
            "reason": manifest_errors[0],
            "completed_at": utc_timestamp_now(),
        }

    atomic_write_json(manifest_path, manifest)
    try:
        checksum_issues = write_checksums(run_dir)
    except Exception:
        checksum_issues = ["SHA256SUMS write_error"]
    if checksum_issues:
        errors.append(checksum_issues[0])
        manifest["status"] = "incomplete"
        manifest["finalization"] = {
            "state": "incomplete",
            "reason": checksum_issues[0],
            "completed_at": utc_timestamp_now(),
        }
        atomic_write_json(manifest_path, manifest)
        try:
            write_checksums(run_dir)
        except Exception:
            pass

    return (0 if not errors and manifest["finalization"]["state"] == "complete" else 1), manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--schema-root", required=True)
    args = parser.parse_args(argv)

    try:
        exit_code, manifest = finalize_run(
            run_dir=Path(args.run_dir),
            repo_root=Path(args.repo_root),
            schema_root=Path(args.schema_root),
        )
    except Exception:
        run_dir = Path(args.run_dir)
        repo_root = Path(args.repo_root)
        manifest = default_manifest(run_dir, repo_root)
        manifest["finalization"] = {
            "state": "incomplete",
            "reason": "finalizer unexpected_error",
            "completed_at": utc_timestamp_now(),
        }
        try:
            atomic_write_json(run_dir / "manifest.json", manifest)
            write_checksums(run_dir)
        except Exception:
            pass
        exit_code = 1
    if exit_code != 0:
        print(manifest["finalization"]["reason"], file=__import__("sys").stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
