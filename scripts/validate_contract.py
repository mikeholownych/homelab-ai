from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path
from typing import Any, Callable

import jsonschema
from jsonschema import Draft202012Validator, FormatChecker


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = REPO_ROOT / "schemas"
CONTRACT_TYPES = ("validation", "evidence", "benchmark", "cmdb", "itsm", "manifest")
RECAP_COUNTER_KEYS = ("ok", "changed", "unreachable", "failed", "skipped", "rescued", "ignored")


def get_schema_paths(schema_root: Path | None = None) -> dict[str, Path]:
    resolved_root = schema_root if schema_root is not None else SCHEMA_DIR
    return {
        "validation": resolved_root / "validation.schema.json",
        "evidence": resolved_root / "evidence.schema.json",
        "benchmark": resolved_root / "benchmark.schema.json",
        "cmdb": resolved_root / "cmdb.schema.json",
        "itsm": resolved_root / "itsm.schema.json",
        "manifest": resolved_root / "manifest.schema.json",
    }


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def package_matches_rule(package_name: str, rule: str) -> bool:
    if "*" in rule or "?" in rule or "[" in rule:
        return fnmatch.fnmatch(package_name, rule)
    return package_name == rule or package_name.startswith(f"{rule}-") or package_name.startswith(rule)


def is_package_routine_allowed(
    package_name: str,
    routine_components: dict[str, Any],
    protected_patterns: list[str],
) -> bool:
    if any(package_matches_rule(package_name, pattern) for pattern in protected_patterns):
        return False

    allowlist: set[str] = set()
    exclusions: list[str] = []
    for component in routine_components.values():
        if not isinstance(component, dict):
            continue
        allowlist.update(component.get("package_allowlist", []))
        exclusions.extend(component.get("package_exclusions", []))

    if package_name not in allowlist:
        return False

    return not any(package_matches_rule(package_name, exclusion) for exclusion in exclusions)


def collect_schema_errors(
    contract_type: str,
    payload: dict[str, object],
    *,
    schema_root: Path | None = None,
) -> list[str]:
    schema = load_json(get_schema_paths(schema_root)[contract_type])
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.absolute_path))
    return [format_schema_error(error) for error in errors]


def format_schema_error(error: jsonschema.ValidationError) -> str:
    pointer = ('/' + '/'.join(map(str, error.absolute_path))) if error.absolute_path else '/'
    detail = f"schema validation failed at {pointer} keyword={error.validator}"
    if error.validator == "const":
        detail += f" expected={error.validator_value}"
    elif error.validator == "enum":
        detail += f" expected={','.join(map(str, error.validator_value))}"
    return detail


def expected_validation_truth_table(payload: dict[str, object]) -> tuple[str, str]:
    checks = payload.get("checks", [])
    if not isinstance(checks, list):
        return "BLOCKED", "blocked"

    blocking_failures = sum(1 for check in checks if isinstance(check, dict) and check.get("status") == "BLOCKED")
    failed_checks = sum(1 for check in checks if isinstance(check, dict) and check.get("status") == "FAIL")
    not_tested = sum(1 for check in checks if isinstance(check, dict) and check.get("status") == "NOT_TESTED")

    if blocking_failures > 0:
        return "BLOCKED", "blocked"
    if failed_checks > 0:
        return "FAIL", "degraded"
    if not_tested > 0:
        return "NOT_TESTED", "incomplete"
    return "PASS", "healthy"


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

    expected_status, expected_classification = expected_validation_truth_table(payload)
    top_status = payload.get("status")
    classification = summary.get("classification")
    if top_status != expected_status:
        errors.append(f"top-level status must be {expected_status} for the observed validation outcomes")
    if classification != expected_classification:
        errors.append(
            f"summary classification must be {expected_classification} when top-level status is {expected_status}"
        )

    if expected_status == "PASS" and (blocking_failures != 0 or failed_checks != 0 or not_tested != 0):
        errors.append("PASS status requires zero failed, blocked, and NOT_TESTED checks")

    return errors


def validate_evidence_payload(payload: dict[str, object]) -> list[str]:
    run = payload.get("run")
    finalization = payload.get("finalization")
    if not isinstance(run, dict) or not isinstance(finalization, dict):
        return []

    errors: list[str] = []
    ansible = run.get("ansible")
    if not isinstance(ansible, dict):
        return ["run.ansible must be an object"]

    recap = ansible.get("recap")
    if recap is None:
        errors.append("run.ansible.recap is required for durable evidence manifests")
        return errors
    if not isinstance(recap, dict):
        errors.append("run.ansible.recap must be an object")
        return errors

    totals = recap.get("totals")
    hosts = recap.get("hosts")
    if not isinstance(totals, dict):
        errors.append("run.ansible.recap.totals must be an object")
    if not isinstance(hosts, dict) or not hosts:
        errors.append("run.ansible.recap.hosts must be a non-empty object")

    state = finalization.get("state")
    status = payload.get("status")
    exit_code = ansible.get("exit_code")
    failed = totals.get("failed") if isinstance(totals, dict) else None
    unreachable = totals.get("unreachable") if isinstance(totals, dict) else None

    if state == "complete" and status != "captured":
        errors.append("finalization.state complete requires top-level status captured")
    if state == "complete" and exit_code != 0:
        errors.append("finalization.state complete requires ansible exit_code 0")
    if state == "complete" and (failed != 0 or unreachable != 0):
        errors.append("finalization.state complete requires zero failed and unreachable recap totals")
    if state == "incomplete" and finalization.get("reason") in (None, ""):
        errors.append("finalization.state incomplete requires a non-empty reason")

    return errors


def validate_recap_structure(recap: object, *, pointer: str) -> list[str]:
    if not isinstance(recap, dict):
        return [f"{pointer} must be an object"]

    allowed_keys = {"totals", "hosts"}
    recap_keys = set(recap)
    errors: list[str] = []
    if recap_keys != allowed_keys:
        errors.append(f"{pointer} must contain exactly totals and hosts")

    totals = recap.get("totals")
    hosts = recap.get("hosts")
    if not isinstance(totals, dict):
        errors.append(f"{pointer}/totals must be an object")
        return errors
    if not isinstance(hosts, dict) or not hosts:
        errors.append(f"{pointer}/hosts must be a non-empty object")
        return errors

    if set(totals) != set(RECAP_COUNTER_KEYS):
        errors.append(f"{pointer}/totals must contain exactly the supported recap counters")

    computed_totals = {key: 0 for key in RECAP_COUNTER_KEYS}
    for host_name, host_counters in hosts.items():
        if not isinstance(host_name, str) or not host_name:
            errors.append(f"{pointer}/hosts must use non-empty string host names")
            continue
        if not isinstance(host_counters, dict):
            errors.append(f"{pointer}/hosts/{host_name} must be an object")
            continue
        if set(host_counters) != set(RECAP_COUNTER_KEYS):
            errors.append(f"{pointer}/hosts/{host_name} must contain exactly the supported recap counters")
            continue
        for key in RECAP_COUNTER_KEYS:
            value = host_counters.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                errors.append(f"{pointer}/hosts/{host_name}/{key} must be a non-negative integer")
                continue
            computed_totals[key] += value

    for key in RECAP_COUNTER_KEYS:
        value = totals.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            errors.append(f"{pointer}/totals/{key} must be a non-negative integer")
            continue
        if computed_totals[key] != value:
            errors.append(f"{pointer}/totals/{key} must equal the sum of per-host recap counters")

    return errors


def validate_manifest_payload(payload: dict[str, object]) -> list[str]:
    errors: list[str] = []
    run = payload.get("run")
    finalization = payload.get("finalization")
    if not isinstance(run, dict):
        return ["run must be an object"]
    if not isinstance(finalization, dict):
        return ["finalization must be an object"]

    recap = None
    ansible = run.get("ansible")
    if not isinstance(ansible, dict):
        errors.append("/run/ansible must be an object")
    else:
        recap = ansible.get("recap")
        if recap is None:
            if payload.get("status") != "incomplete":
                errors.append("/run/ansible/recap must be present unless status is incomplete")
        else:
            errors.extend(validate_recap_structure(recap, pointer="/run/ansible/recap"))

    state = finalization.get("state")
    status = payload.get("status")
    if state == "complete" and status != "captured":
        errors.append("/finalization/state complete requires top-level status captured")
    if state == "incomplete" and finalization.get("reason") in (None, ""):
        errors.append("/finalization/reason must be present when finalization is incomplete")

    if state == "complete":
        if not isinstance(ansible, dict) or not isinstance(recap, dict):
            errors.append("/run/ansible/recap must be present when finalization is complete")
        else:
            exit_code = ansible.get("exit_code")
            if exit_code != 0:
                errors.append("/run/ansible/exit_code must be 0 when finalization is complete")
            totals = recap.get("totals", {})
            if isinstance(totals, dict) and (totals.get("failed") != 0 or totals.get("unreachable") != 0):
                errors.append("/run/ansible/recap totals failed and unreachable must be 0 when finalization is complete")

    return errors


def get_nested_status(payload: dict[str, object], key: str) -> Any:
    section = payload.get(key)
    if not isinstance(section, dict):
        return None
    observed = section.get("observed")
    if not isinstance(observed, dict):
        return None
    return observed.get("status")


def validate_itsm_payload(payload: dict[str, object]) -> list[str]:
    errors: list[str] = []
    selected_action = payload.get("selected_action")
    executed_action = payload.get("executed_action")
    permitted_actions = payload.get("permitted_actions", [])
    if not isinstance(permitted_actions, list):
        return ["permitted_actions must be a list"]

    if selected_action is not None and selected_action not in permitted_actions:
        errors.append("selected_action must be contained within permitted_actions")
    if executed_action is not None and executed_action not in permitted_actions:
        errors.append("executed_action must be contained within permitted_actions")
    if selected_action is not None and executed_action is not None and selected_action != executed_action:
        errors.append("executed_action must equal selected_action")

    status = payload.get("status")
    approval_state = payload.get("approval_state")
    execution_status = get_nested_status(payload, "execution_result")
    validation_status = get_nested_status(payload, "validation_result")

    if status == "PENDING":
        if approval_state != "PENDING":
            errors.append("PENDING status requires approval_state PENDING")
        if executed_action is not None:
            errors.append("PENDING status requires executed_action to be null")
        if execution_status != "NOT_TESTED":
            errors.append("PENDING status requires execution_result observed status NOT_TESTED")
        if validation_status != "NOT_TESTED":
            errors.append("PENDING status requires validation_result observed status NOT_TESTED")
    elif status == "APPROVED":
        if approval_state != "APPROVED":
            errors.append("APPROVED status requires approval_state APPROVED")
        if executed_action is not None:
            errors.append("APPROVED status requires executed_action to be null before execution starts")
        if execution_status != "NOT_TESTED":
            errors.append("APPROVED status requires execution_result observed status NOT_TESTED")
        if validation_status != "NOT_TESTED":
            errors.append("APPROVED status requires validation_result observed status NOT_TESTED")
    elif status == "IMPLEMENTED":
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
    elif status == "REJECTED":
        if approval_state != "REJECTED":
            errors.append("REJECTED status requires approval_state REJECTED")
        if executed_action is not None:
            errors.append("REJECTED status may not include an executed_action")
        if execution_status != "NOT_TESTED":
            errors.append("REJECTED status requires execution_result observed status NOT_TESTED")
        if validation_status != "NOT_TESTED":
            errors.append("REJECTED status requires validation_result observed status NOT_TESTED")
    elif status == "FAILED":
        if approval_state != "APPROVED":
            errors.append("FAILED status requires approval_state APPROVED")
        if selected_action is None or executed_action is None:
            errors.append("FAILED status requires selected_action and executed_action")
        if execution_status not in {"FAIL", "BLOCKED"} and validation_status not in {"FAIL", "BLOCKED"}:
            errors.append("FAILED status requires a FAIL or BLOCKED execution_result or validation_result")
    elif status == "NOT_REQUIRED":
        if approval_state != "NOT_REQUIRED":
            errors.append("NOT_REQUIRED status requires approval_state NOT_REQUIRED")
        if selected_action is not None or executed_action is not None:
            errors.append("NOT_REQUIRED status requires selected_action and executed_action to be null")
        if execution_status != "NOT_TESTED":
            errors.append("NOT_REQUIRED status requires execution_result observed status NOT_TESTED")
        if validation_status != "NOT_TESTED":
            errors.append("NOT_REQUIRED status requires validation_result observed status NOT_TESTED")

    return errors


SEMANTIC_VALIDATORS: dict[str, Callable[[dict[str, object]], list[str]]] = {
    "validation": validate_validation_payload,
    "evidence": validate_evidence_payload,
    "benchmark": lambda payload: [],
    "cmdb": lambda payload: [],
    "itsm": validate_itsm_payload,
    "manifest": validate_manifest_payload,
}


def collect_semantic_errors(contract_type: str, payload: dict[str, object]) -> list[str]:
    return SEMANTIC_VALIDATORS[contract_type](payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("contract_type", choices=CONTRACT_TYPES)
    parser.add_argument("json_path")
    args = parser.parse_args(argv)

    payload = load_json(Path(args.json_path))
    if not isinstance(payload, dict):
        print("payload must be a JSON object", file=sys.stderr)
        return 1

    schema_errors = collect_schema_errors(args.contract_type, payload)
    semantic_errors = collect_semantic_errors(args.contract_type, payload)
    if schema_errors or semantic_errors:
        for error in schema_errors:
            print(error, file=sys.stderr)
        for error in semantic_errors:
            print(error, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
