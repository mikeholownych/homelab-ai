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
SUPPORTED_CONTRACTS = {
    "evidence.json": "evidence",
    "validation.json": "validation",
    "benchmark.json": "benchmark",
    "cmdb.json": "cmdb",
    "itsm.json": "itsm",
}
TRANSIENT_PATTERN = re.compile(r"(^|/)\.?[^/]*\.tmp(?:\..+)?$")


def utc_timestamp_now() -> str:
    return __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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
    in_recap = False
    hosts: dict[str, dict[str, int]] = {}
    totals: dict[str, int] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("PLAY RECAP"):
            in_recap = True
            hosts = {}
            totals = {
                "ok": 0,
                "changed": 0,
                "unreachable": 0,
                "failed": 0,
                "skipped": 0,
                "rescued": 0,
                "ignored": 0,
            }
            continue
        if not in_recap:
            continue
        match = RECAP_PATTERN.match(line)
        if not match:
            continue
        counters = {key: int(match.group(key)) for key in totals}
        host = match.group("host")
        hosts[host] = counters
        for key, value in counters.items():
            totals[key] += value

    if not hosts:
        raise ValueError("ansible recap was not found or could not be parsed")

    return {
        "totals": totals,
        "hosts": hosts,
    }


def sanitize_reason(message: str) -> str:
    return " ".join(message.strip().split())


def classify_manifest_status(manifest: dict[str, Any], recap: dict[str, Any]) -> tuple[str, str | None]:
    exit_code = manifest["run"]["ansible"]["exit_code"]
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
        reasons.append(f"ansible exit_code {exit_code}")
    if failed:
        reasons.append(f"recap failed={failed}")
    if unreachable:
        reasons.append(f"recap unreachable={unreachable}")
    if missing_artifacts:
        reasons.append(f"missing artifacts: {', '.join(sorted(missing_artifacts))}")
    return "incomplete", "; ".join(reasons)


def discover_recap(run_dir: Path, manifest: dict[str, Any], ansible_run: dict[str, Any]) -> dict[str, Any]:
    recap = ansible_run.get("recap")
    if isinstance(recap, dict):
        return recap
    if isinstance(recap, str) and recap.strip():
        return parse_recap(recap)
    manifest_recap = manifest.get("run", {}).get("ansible", {}).get("recap")
    if isinstance(manifest_recap, dict):
        return manifest_recap
    log_path = run_dir / "ansible.log"
    if log_path.exists():
        return parse_recap(log_path.read_text(encoding="utf-8"))
    raise ValueError("ansible recap is missing")


def update_artifact_observations(manifest: dict[str, Any], run_dir: Path) -> None:
    observed_at = manifest["generated_at"]
    for artifact in manifest["artifacts"]:
        expected_path = artifact["expected"]["path"]
        artifact_path = run_dir / expected_path
        if artifact_path.exists() and artifact_path.is_file():
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


def component_files_for_checksums(run_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in run_dir.rglob("*"):
        if not path.is_file():
            continue
        relative_path = path.relative_to(run_dir).as_posix()
        if relative_path == "SHA256SUMS":
            continue
        if TRANSIENT_PATTERN.search(relative_path):
            continue
        files.append(path)
    return sorted(files, key=lambda path: path.relative_to(run_dir).as_posix())


def write_checksums(run_dir: Path) -> None:
    lines = [
        f"{sha256_file(path)}  {path.relative_to(run_dir).as_posix()}"
        for path in component_files_for_checksums(run_dir)
    ]
    atomic_write_text(run_dir / "SHA256SUMS", "\n".join(lines) + ("\n" if lines else ""))


def validate_component_json(run_dir: Path, repo_root: Path, schema_root: Path) -> list[str]:
    errors: list[str] = []
    for path in sorted(run_dir.glob("*.json")):
        contract_type = SUPPORTED_CONTRACTS.get(path.name)
        if contract_type is None:
            continue
        payload = load_json(path)
        if not isinstance(payload, dict):
            errors.append(f"{path.name}: payload must be a JSON object")
            continue
        schema_errors = validate_contract.collect_schema_errors(
            contract_type,
            payload,
            schema_root=schema_root,
        )
        semantic_errors = validate_contract.collect_semantic_errors(contract_type, payload)
        for error in schema_errors + semantic_errors:
            errors.append(f"{path.name}: {sanitize_reason(error)}")
    return errors


def finalize_run(run_dir: Path, repo_root: Path, schema_root: Path) -> tuple[int, dict[str, Any]]:
    manifest_path = run_dir / "manifest.json"
    ansible_run_path = run_dir / "ansible-run.json"
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict):
        raise ValueError("manifest.json must contain a JSON object")
    ansible_run = load_json(ansible_run_path)
    if not isinstance(ansible_run, dict):
        raise ValueError("ansible-run.json must contain a JSON object")

    manifest["generated_at"] = utc_timestamp_now()
    manifest["git_sha"] = ansible_run.get("git_sha", manifest.get("git_sha"))
    manifest["simulated"] = bool(ansible_run.get("simulated", manifest.get("simulated", False)))
    manifest["run"]["inventory"] = ansible_run.get("inventory", manifest["run"]["inventory"])
    manifest["run"]["playbook"] = ansible_run.get("playbook", manifest["run"]["playbook"])
    manifest["run"]["limit"] = ansible_run.get("limit", manifest["run"]["limit"])
    manifest["run"]["started_at"] = ansible_run.get("started_at", manifest["run"]["started_at"])
    manifest["run"]["finished_at"] = ansible_run.get("finished_at", manifest["run"]["finished_at"])
    manifest["run"]["ansible"]["exit_code"] = int(ansible_run.get("exit_code", manifest["run"]["ansible"]["exit_code"]))
    if "validation" in ansible_run and isinstance(ansible_run["validation"], dict):
        manifest["run"]["validation"] = ansible_run["validation"]

    try:
        recap = discover_recap(run_dir, manifest, ansible_run)
    except ValueError as exc:
        manifest["status"] = "incomplete"
        manifest["finalization"] = {
            "state": "incomplete",
            "reason": sanitize_reason(str(exc)),
            "completed_at": utc_timestamp_now(),
        }
        atomic_write_json(manifest_path, manifest)
        return 1, manifest

    manifest["run"]["ansible"]["recap"] = recap
    update_artifact_observations(manifest, run_dir)
    manifest["status"], incomplete_reason = classify_manifest_status(manifest, recap)

    component_errors = validate_component_json(run_dir, repo_root, schema_root)
    if component_errors:
        manifest["status"] = "incomplete"
        manifest["finalization"] = {
            "state": "incomplete",
            "reason": sanitize_reason(component_errors[0]),
            "completed_at": utc_timestamp_now(),
        }
        atomic_write_json(manifest_path, manifest)
        return 1, manifest

    manifest["finalization"] = {
        "state": "complete" if manifest["status"] == "captured" else "incomplete",
        "reason": incomplete_reason,
        "completed_at": utc_timestamp_now(),
    }
    atomic_write_json(manifest_path, manifest)
    write_checksums(run_dir)
    return 0, manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--schema-root", required=True)
    args = parser.parse_args(argv)

    exit_code, manifest = finalize_run(
        run_dir=Path(args.run_dir),
        repo_root=Path(args.repo_root),
        schema_root=Path(args.schema_root),
    )
    if exit_code != 0:
        print(manifest["finalization"]["reason"], file=__import__("sys").stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
