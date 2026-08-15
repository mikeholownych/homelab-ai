from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_validation_payload(payload: dict[str, object]) -> list[str]:
    errors: list[str] = []
    checks = payload.get("checks", [])
    if not isinstance(checks, list):
      return ["checks must be a list"]

    blocking_failures = sum(1 for check in checks if isinstance(check, dict) and check.get("status") == "BLOCKED")
    failed_checks = sum(1 for check in checks if isinstance(check, dict) and check.get("status") == "FAIL")
    warnings = sum(1 for check in checks if isinstance(check, dict) and check.get("severity") == "warning")
    not_tested = sum(1 for check in checks if isinstance(check, dict) and check.get("status") == "NOT_TESTED")

    summary = payload.get("summary", {})
    if not isinstance(summary, dict):
        return ["summary must be an object"]

    if summary.get("blocking_failures") != blocking_failures:
        errors.append("summary blocking_failures does not match actual BLOCKED checks")
    if summary.get("failed_checks") != failed_checks:
        errors.append("summary failed_checks does not match actual FAIL checks")
    if summary.get("warnings") != warnings:
        errors.append("summary warnings does not match actual warning severities")
    if summary.get("not_tested") != not_tested:
        errors.append("summary not_tested does not match actual NOT_TESTED checks")

    top_status = payload.get("status")
    if top_status == "PASS" and (blocking_failures > 0 or failed_checks > 0):
        errors.append("top-level status PASS is inconsistent with failing or blocked checks")

    if summary.get("classification") == "healthy" and (blocking_failures > 0 or failed_checks > 0):
        errors.append("healthy classification is inconsistent with failing or blocked checks")

    return errors


def validate_itsm_payload(payload: dict[str, object]) -> list[str]:
    errors: list[str] = []
    selected_action = payload.get("selected_action")
    permitted_actions = payload.get("permitted_actions", [])
    if selected_action is not None and selected_action not in permitted_actions:
        errors.append("selected_action must be contained within permitted_actions")

    status = payload.get("status")
    approval_state = payload.get("approval_state")
    execution_status = (
        payload.get("execution_result", {})
        .get("observed", {})
        .get("status")
        if isinstance(payload.get("execution_result"), dict)
        else None
    )
    validation_status = (
        payload.get("validation_result", {})
        .get("observed", {})
        .get("status")
        if isinstance(payload.get("validation_result"), dict)
        else None
    )
    executed_action = payload.get("executed_action")

    if status == "IMPLEMENTED":
        if approval_state != "APPROVED":
            errors.append("IMPLEMENTED status requires approval_state APPROVED")
        if selected_action is None:
            errors.append("IMPLEMENTED status requires selected_action")
        if executed_action is None:
            errors.append("IMPLEMENTED status requires executed_action")
        if execution_status not in {"PASS", "SUCCEEDED"}:
            errors.append("IMPLEMENTED status requires execution_result observed status PASS or SUCCEEDED")
        if validation_status != "PASS":
            errors.append("IMPLEMENTED status requires validation_result observed status PASS")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("contract_type", choices=("validation", "itsm"))
    parser.add_argument("json_path")
    args = parser.parse_args(argv)

    payload = load_json(Path(args.json_path))
    if not isinstance(payload, dict):
        print("payload must be a JSON object", file=sys.stderr)
        return 1

    if args.contract_type == "validation":
        errors = validate_validation_payload(payload)
    else:
        errors = validate_itsm_payload(payload)

    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
