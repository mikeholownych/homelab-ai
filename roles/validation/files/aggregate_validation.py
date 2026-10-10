#!/usr/bin/env python3
"""Aggregate independent validation checks and produce schema-valid evidence."""
from __future__ import annotations

import argparse
import datetime
import json
import os
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

REQUIRED_CHECKS_SPEC = {
    "cpu": {"category": "platform", "classification": "hardware", "severity": "blocking", "summary": "Threadripper PRO 3945WX", "value": "AMD Threadripper PRO 3945WX"},
    "machine_model": {"category": "platform", "classification": "hardware", "severity": "blocking", "summary": "Lenovo 30E1S7NJ00", "value": "30E1S7NJ00"},
    "gpu_count": {"category": "compute", "classification": "hardware", "severity": "blocking", "summary": "2 Intel Arc Pro B65 GPUs", "value": 2},
    "gpu_model": {"category": "compute", "classification": "hardware", "severity": "blocking", "summary": "Intel Arc Pro B65", "value": "Intel Arc Pro B65"},
    "gpu_vram": {"category": "compute", "classification": "hardware", "severity": "blocking", "summary": "32 GiB per GPU", "value": 32.0},
    "level_zero": {"category": "compute", "classification": "runtime", "severity": "blocking", "summary": "2 Level Zero devices", "value": 2},
    "pytorch_xpu": {"category": "compute", "classification": "runtime", "severity": "blocking", "summary": "2 PyTorch XPU devices", "value": 2},
    "pcie_topology": {"category": "bus", "classification": "hardware", "severity": "blocking", "summary": "Gen4 Link", "value": "Gen4"},
    "rebar": {"category": "bus", "classification": "hardware", "severity": "blocking", "summary": "Resizable BAR Enabled", "value": True},
    "vllm_service": {"category": "inference", "classification": "service", "severity": "warning", "summary": "vLLM service healthy", "value": "healthy"},
    "single_gpu_inference": {"category": "inference", "classification": "runtime", "severity": "warning", "summary": "Single-GPU inference passes", "value": "PASS"},
    "dual_gpu_inference": {"category": "inference", "classification": "runtime", "severity": "warning", "summary": "Dual-GPU inference passes", "value": "PASS"},
    "llama_cpp_fallback": {"category": "inference", "classification": "runtime", "severity": "information", "summary": "llama.cpp fallback passes", "value": "PASS"},
    "required_services": {"category": "system", "classification": "service", "severity": "warning", "summary": "Required services active", "value": "active"},
    "scheduled_reconciliation": {"category": "operations", "classification": "operations", "severity": "warning", "summary": "Reconciliation enabled", "value": "enabled"},
    "vault_access": {"category": "security", "classification": "access", "severity": "blocking", "summary": "Vault access succeeds", "value": "accessible"},
    "os_tuning_profile": {"category": "operations", "classification": "operations", "severity": "warning", "summary": "Active tuning profile", "value": "baseline"},
    "os_tuning_governor": {"category": "operations", "classification": "operations", "severity": "warning", "summary": "CPU governor matches profile", "value": "PASS"},
    "os_tuning_thp": {"category": "operations", "classification": "operations", "severity": "warning", "summary": "THP mode matches profile", "value": "PASS"},
    "os_tuning_hugepages": {"category": "operations", "classification": "operations", "severity": "warning", "summary": "HugeTLB state matches profile", "value": "PASS"},
    "os_tuning_sysctl": {"category": "operations", "classification": "operations", "severity": "warning", "summary": "Managed sysctl values active", "value": "PASS"},
    "running_kernel": {"category": "system", "classification": "runtime", "severity": "blocking", "summary": "Expected kernel running", "value": "PASS"},
    "numa_topology": {"category": "platform", "classification": "hardware", "severity": "warning", "summary": "NUMA topology stable", "value": "PASS"},
    "intel_gpu_stack_status": {"category": "compute", "classification": "runtime", "severity": "blocking", "summary": "B65 stack status", "value": "pre_verification_fail_closed"},
}


def wrap_summary_value(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict) and "summary" in raw and "value" in raw:
        return {"summary": str(raw["summary"]), "value": raw["value"]}
    if raw is None:
        return {"summary": "None", "value": None}
    return {"summary": str(raw), "value": raw}


def _expected_harness_checks(profile: Dict[str, Any] | None) -> Dict[str, Dict[str, Any]]:
    """Derive harness expected values from the selected hardware profile.

    Returns an empty dict for no profile so callers keep P620 (REQUIRED_CHECKS_SPEC)
    defaults untouched. Any key present here overrides the matching base spec entry.
    """
    if not profile:
        return {}
    platform = profile.get("platform") or {}
    patterns = (profile.get("cpu") or {}).get("model_patterns") or []
    cpu_expected = patterns[0] if patterns else "unknown"
    count = (profile.get("gpu") or {}).get("count_expected") or 0
    approved = (profile.get("gpu") or {}).get("approved_pci_devices") or []
    expected = (profile.get("gpu") or {}).get("expected_models") or []
    model = approved[0].get("model", "unknown") if approved else "unknown"
    vram_raw = None
    if expected:
        memory = expected[0].get("memory_gib") or {}
        vram_raw = memory.get("approximate")
    vram = float(vram_raw) if isinstance(vram_raw, (int, float)) else "unknown"
    generation = (profile.get("pcie") or {}).get("host_link") or {}
    position = f"Gen{generation.get('expected_negotiated_generation')}" \
        if isinstance(generation.get("expected_negotiated_generation"), int) else "unknown"
    return {
        "cpu": {"category": "platform", "classification": "hardware", "severity": "blocking",
                "summary": cpu_expected, "value": cpu_expected},
        "machine_model": {"category": "platform", "classification": "hardware", "severity": "blocking",
                          "summary": platform.get("machine_type_model", "unknown"),
                          "value": platform.get("machine_type_model", "unknown")},
        "gpu_count": {"category": "compute", "classification": "hardware", "severity": "blocking",
                      "summary": f"{count} GPU(s)", "value": count},
        "gpu_model": {"category": "compute", "classification": "hardware", "severity": "blocking",
                      "summary": model, "value": model},
        "gpu_vram": {"category": "compute", "classification": "hardware", "severity": "blocking",
                     "summary": f"{vram} GiB per GPU", "value": vram},
        "level_zero": {"category": "compute", "classification": "runtime", "severity": "blocking",
                       "summary": f"{count} Level Zero devices", "value": count},
        "pytorch_xpu": {"category": "compute", "classification": "runtime", "severity": "blocking",
                        "summary": f"{count} PyTorch XPU devices", "value": count},
        "pcie_topology": {"category": "bus", "classification": "hardware", "severity": "blocking",
                          "summary": f"{position} Link", "value": position},
        "rebar": {"category": "bus", "classification": "hardware", "severity": "blocking",
                  "summary": "Resizable BAR Enabled", "value": True},
    }


def classify_drift(
    predicted_changes: int,
    actual_changes: int,
    unresolved_changes: int,
    validation_status: str,
    has_blocking_failure: bool,
) -> str:
    if has_blocking_failure or validation_status in ("BLOCKED", "FAIL"):
        return "blocking_drift"
    if unresolved_changes > 0:
        return "unresolved_drift"
    if actual_changes > 0 and validation_status == "PASS":
        return "remediated_drift"
    if predicted_changes == 0 and actual_changes == 0 and validation_status == "PASS":
        return "no_drift"
    return "unresolved_drift"


def build_validation_document(
    node_id: str,
    environment: str,
    hardware_profile: str,
    git_sha: str,
    simulated: bool,
    checks_data: Dict[str, Dict[str, Any]],
    generated_at: str | None = None,
    hardware_profile_spec: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    if not generated_at:
        generated_at = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    spec = {**REQUIRED_CHECKS_SPEC, **_expected_harness_checks(hardware_profile_spec)}
    checks: List[Dict[str, Any]] = []
    has_blocked = False
    has_fail = False
    has_not_tested = False
    blocking_failures = 0
    failed_checks = 0
    warnings = 0
    not_tested = 0
    not_applicable = 0

    for check_id, check_spec in spec.items():
        user_check = checks_data.get(check_id, {})
        status = user_check.get("status", "NOT_TESTED")
        severity = user_check.get("severity", check_spec["severity"])
        
        expected_raw = user_check.get("expected", {"summary": check_spec["summary"], "value": check_spec["value"]})
        if status == "NOT_TESTED":
            observed_raw = user_check.get("observed", {"summary": "not observed", "value": None})
        elif status == "NOT_APPLICABLE":
            observed_raw = user_check.get("observed", {"summary": "not applicable for architecture/profile", "value": "NOT_APPLICABLE"})
        else:
            observed_raw = user_check.get("observed", expected_raw)
        evidence_refs = user_check.get("evidence_refs", [f"{check_id}_evidence.json"])

        if severity == "warning":
            warnings += 1

        if status == "BLOCKED":
            has_blocked = True
            blocking_failures += 1
        elif status == "FAIL":
            if severity == "blocking":
                status = "BLOCKED"
                has_blocked = True
                blocking_failures += 1
            else:
                has_fail = True
                failed_checks += 1
        elif status == "NOT_TESTED":
            has_not_tested = True
            not_tested += 1
        elif status == "NOT_APPLICABLE":
            not_applicable += 1

        checks.append({
            "id": check_id,
            "category": check_spec["category"],
            "classification": check_spec["classification"],
            "severity": severity,
            "status": status,
            "expected": wrap_summary_value(expected_raw),
            "observed": wrap_summary_value(observed_raw),
            "evidence_refs": evidence_refs,
        })

    if has_blocked:
        overall_status = "BLOCKED"
        classification = "blocked"
    elif has_fail:
        overall_status = "FAIL"
        classification = "degraded"
    elif has_not_tested:
        overall_status = "NOT_TESTED"
        classification = "incomplete"
    else:
        overall_status = "PASS"
        classification = "healthy"

    return {
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "git_sha": git_sha,
        "simulated": simulated,
        "status": overall_status,
        "node": {
            "id": node_id,
            "environment": environment,
            "hardware_profile": hardware_profile,
        },
        "checks": checks,
        "summary": {
            "blocking_failures": blocking_failures,
            "failed_checks": failed_checks,
            "warnings": warnings,
            "not_tested": not_tested,
            "not_applicable": not_applicable,
            "classification": classification,
        },
    }


def _evidence_check(rule_status: Any, expected: Any, observed: Any, ref: str) -> Dict[str, Any]:
    status = {"pass": "PASS", "fail": "FAIL"}.get(str(rule_status).lower(), "NOT_TESTED")
    return {"status": status, "expected": wrap_summary_value(expected), "observed": wrap_summary_value(observed),
            "evidence_refs": [ref]}


def _unreadable(ref: str, error: Exception) -> Dict[str, Any]:
    return {"status": "NOT_TESTED", "expected": wrap_summary_value("readable evidence"),
            "observed": wrap_summary_value(f"evidence unreadable: {type(error).__name__}"), "evidence_refs": [ref]}


# Evidence rule -> validation check id. A check is filled only from a rule the evidence actually records.
_HARDWARE_RULES = {"cpu_model": "cpu", "machine_model": "machine_model", "gpu_count": "gpu_count",
                   "gpu_model_match": "gpu_model", "gpu_memory": "gpu_vram", "level_zero_detected": "level_zero"}
_PCI_RULES = {"pcie_link_health": "pcie_topology", "resizable_bar_enabled": "rebar"}


def discover_evidence_checks(
    evidence_dir: str | Path | None,
    profile_spec: Dict[str, Any] | None,
    checks_data: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Fill checks that have no explicit input from evidence files the collectors wrote.

    Every status and observed value comes from the evidence document itself; a check without evidence stays absent
    (and is reported NOT_TESTED), and unreadable evidence is reported NOT_TESTED with the reason. Nothing is defaulted
    to PASS: a verdict must point at an observation."""
    if not evidence_dir or not Path(evidence_dir).exists():
        return checks_data
    ev_path = Path(evidence_dir)

    search_dirs = [ev_path, ev_path / "manual"]

    for name, rules in (("hardware.json", _HARDWARE_RULES), ("pci.json", _PCI_RULES)):
        found = next((d / name for d in search_dirs if (d / name).exists()), None)
        if found is None:
            continue
        try:
            records = json.loads(found.read_text(encoding="utf-8")).get("checks", [])
        except (OSError, ValueError, AttributeError) as error:
            for check_id in rules.values():
                checks_data.setdefault(check_id, _unreadable(found.name, error))
            continue
        for record in records:
            check_id = rules.get(record.get("rule")) if isinstance(record, dict) else None
            if check_id and check_id not in checks_data:
                checks_data[check_id] = _evidence_check(record.get("status"), record.get("expected"),
                                                        record.get("observed"), found.name)

    xpu_file = next((d / "xpu-validation.json" for d in search_dirs if (d / "xpu-validation.json").exists()), None)
    if xpu_file is not None and "pytorch_xpu" not in checks_data:
        try:
            doc = json.loads(xpu_file.read_text(encoding="utf-8"))
            checks_data["pytorch_xpu"] = _evidence_check(doc.get("status"), doc.get("expected_device_count"),
                                                         doc.get("device_count"), xpu_file.name)
        except (OSError, ValueError, AttributeError) as error:
            checks_data["pytorch_xpu"] = _unreadable(xpu_file.name, error)

    return checks_data


def _systemctl(*args: str) -> str:
    try:
        return subprocess.run(["systemctl", *args], capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _vault_login(config_path: Path) -> Dict[str, Any]:
    """AppRole login with the node's own Vault client config; the token is revoked at once and nothing is printed."""
    expected = wrap_summary_value("AppRole login succeeds")
    refs = [str(config_path)]
    if not config_path.exists():
        return {"status": "NOT_TESTED", "expected": expected, "observed": wrap_summary_value("no Vault client config"),
                "evidence_refs": refs}
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        body = json.dumps({"role_id": Path(cfg["role_id_file"]).read_text(encoding="utf-8").strip(),
                           "secret_id": Path(cfg["secret_id_file"]).read_text(encoding="utf-8").strip()}).encode()
        context = ssl.create_default_context(cafile=cfg["ca_cert"])
        addr = cfg["vault_addr"].rstrip("/")
    except (OSError, ValueError, KeyError) as error:
        return {"status": "NOT_TESTED", "expected": expected,
                "observed": wrap_summary_value(f"Vault client config unusable: {type(error).__name__}"), "evidence_refs": refs}
    try:
        request = urllib.request.Request(addr + "/v1/auth/approle/login", body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, context=context, timeout=10) as response:
            auth = json.load(response)["auth"]
        revoke = urllib.request.Request(addr + "/v1/auth/token/revoke-self", b"", {"X-Vault-Token": auth["client_token"]})
        urllib.request.urlopen(revoke, context=context, timeout=10).close()
    except urllib.error.HTTPError as error:
        return {"status": "FAIL", "expected": expected, "observed": wrap_summary_value(f"login refused: HTTP {error.code}"),
                "evidence_refs": refs}
    except (OSError, ValueError, KeyError) as error:
        return {"status": "FAIL", "expected": expected,
                "observed": wrap_summary_value(f"Vault unreachable or invalid reply: {type(error).__name__}"), "evidence_refs": refs}
    return {"status": "PASS", "expected": expected,
            "observed": wrap_summary_value(f"login ok at {addr}, policies {sorted(auth.get('policies') or [])}"),
            "evidence_refs": refs}


def observe_live_checks(
    checks_data: Dict[str, Dict[str, Any]],
    *,
    required_units: list[str],
    reconcile_timer: str | None,
    vault_config: str | None,
) -> Dict[str, Dict[str, Any]]:
    """Checks the aggregator observes itself on the managed node (it runs there as root). A check whose input is not
    configured stays NOT_TESTED; an observed problem is a FAIL with the observed state, never a PASS."""
    if required_units and "required_services" not in checks_data:
        states = {unit: _systemctl("is-active", unit) or "unknown" for unit in required_units}
        inactive = sorted(f"{unit}={state}" for unit, state in states.items() if state != "active")
        checks_data["required_services"] = {
            "status": "FAIL" if inactive else "PASS",
            "expected": wrap_summary_value(f"{len(states)} units active"),
            "observed": wrap_summary_value("all active" if not inactive else "not active: " + ", ".join(inactive)),
            "evidence_refs": ["systemctl is-active"]}
    if reconcile_timer and "scheduled_reconciliation" not in checks_data:
        enabled, active = _systemctl("is-enabled", reconcile_timer) or "unknown", _systemctl("is-active", reconcile_timer) or "unknown"
        checks_data["scheduled_reconciliation"] = {
            "status": "PASS" if (enabled, active) == ("enabled", "active") else "FAIL",
            "expected": wrap_summary_value(f"{reconcile_timer} enabled and active"),
            "observed": wrap_summary_value(f"{reconcile_timer} {enabled}/{active}"),
            "evidence_refs": ["systemctl is-enabled/is-active"]}
    if vault_config and "vault_access" not in checks_data:
        checks_data["vault_access"] = _vault_login(Path(vault_config))
    return checks_data


def apply_not_applicable(checks_data: Dict[str, Dict[str, Any]], declarations: list[str]) -> Dict[str, Dict[str, Any]]:
    """Operator-declared applicability (``CHECK=REASON``, from inventory): the check does not apply to this host's
    configuration, and the reason is recorded. An observed result for the same check always wins."""
    for declaration in declarations:
        check_id, sep, reason = declaration.partition("=")
        if not sep or not check_id.strip() or not reason.strip():
            raise ValueError(f"--not-applicable needs CHECK=REASON, got {declaration!r}")
        checks_data.setdefault(check_id.strip(), {
            "status": "NOT_APPLICABLE", "expected": wrap_summary_value("not applicable"),
            "observed": wrap_summary_value(reason.strip()), "evidence_refs": ["inventory:validation_not_applicable"]})
    return checks_data


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate validation checks")
    parser.add_argument("--node-id", default="ai-p620-01", help="Node ID")
    parser.add_argument("--environment", default="production", help="Environment")
    parser.add_argument("--hardware-profile", default="p620_dual_b65", help="Hardware profile")
    parser.add_argument("--git-sha", default="0000000000000000000000000000000000000000", help="Git commit SHA")
    parser.add_argument("--simulated", action="store_true", help="Mark run as simulated")
    parser.add_argument("--input-json", default=None, help="Path to input checks JSON")
    parser.add_argument("--evidence-dir", default=None, help="Path to evidence directory")
    parser.add_argument("--required-unit", action="append", default=[], help="systemd unit that must be active (repeatable)")
    parser.add_argument("--reconcile-timer", default=None, help="systemd timer that runs scheduled reconciliation")
    parser.add_argument("--vault-config", default=None, help="Vault client config (platform-credentials.json) to test")
    parser.add_argument("--not-applicable", action="append", default=[], metavar="CHECK=REASON",
                        help="Declare a check not applicable to this host's configuration (repeatable)")
    parser.add_argument("--output", default=None, help="Path to write validation.json")
    parser.add_argument("--text-summary", default=None, help="Path to write summary txt")
    parser.add_argument("--hardware-profile-json", default=None,
                        help="Expected hardware profile JSON (path or inline) for harness value derivation")
    args = parser.parse_args()

    checks_data: Dict[str, Dict[str, Any]] = {}
    if args.input_json and Path(args.input_json).exists():
        checks_data = json.loads(Path(args.input_json).read_text(encoding="utf-8"))

    profile_spec: Dict[str, Any] | None = None
    if args.hardware_profile_json:
        try:
            spec_path = Path(args.hardware_profile_json)
            if spec_path.exists():
                profile_spec = json.loads(spec_path.read_text(encoding="utf-8"))
            else:
                profile_spec = json.loads(args.hardware_profile_json)
        except OSError:
            profile_spec = json.loads(args.hardware_profile_json)

    if args.evidence_dir:
        checks_data = discover_evidence_checks(args.evidence_dir, profile_spec, checks_data)
    checks_data = apply_not_applicable(checks_data, args.not_applicable)
    checks_data = observe_live_checks(checks_data, required_units=args.required_unit,
                                      reconcile_timer=args.reconcile_timer, vault_config=args.vault_config)

    doc = build_validation_document(
        node_id=args.node_id,
        environment=args.environment,
        hardware_profile=args.hardware_profile,
        git_sha=args.git_sha,
        simulated=args.simulated,
        checks_data=checks_data,
        hardware_profile_spec=profile_spec,
    )

    formatted_json = json.dumps(doc, indent=2)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(formatted_json, encoding="utf-8")

    if args.text_summary:
        sum_path = Path(args.text_summary)
        sum_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"Validation Status: {doc['status']} ({doc['summary']['classification']})",
            f"Node: {doc['node']['id']} ({doc['node']['environment']})",
            f"Hardware Profile: {doc['node']['hardware_profile']}",
            f"Simulated: {doc['simulated']}",
            f"Blocking Failures: {doc['summary']['blocking_failures']}",
            f"Failed Checks: {doc['summary']['failed_checks']}",
            f"Not Tested: {doc['summary']['not_tested']}",
            f"Not Applicable: {doc['summary'].get('not_applicable', 0)}",
            "",
            "Checks:",
        ]
        for c in doc["checks"]:
            lines.append(f"  - [{c['status']}] {c['id']} (expected: {c['expected']['summary']}, observed: {c['observed']['summary']})")
        sum_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(formatted_json)
    return 0 if doc["status"] in ("PASS", "NOT_TESTED") else 1


if __name__ == "__main__":
    sys.exit(main())
