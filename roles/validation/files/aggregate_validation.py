#!/usr/bin/env python3
"""Aggregate independent validation checks and produce schema-valid evidence."""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
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

    for check_id, check_spec in spec.items():
        user_check = checks_data.get(check_id, {})
        status = user_check.get("status", "NOT_TESTED")
        severity = user_check.get("severity", check_spec["severity"])
        
        expected_raw = user_check.get("expected", {"summary": check_spec["summary"], "value": check_spec["value"]})
        observed_raw = user_check.get("observed", {"summary": "not observed", "value": None} if status == "NOT_TESTED" else expected_raw)
        evidence_refs = user_check.get("evidence_refs", [f"{check_id}_evidence.json"])

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
            "classification": classification,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate validation checks")
    parser.add_argument("--node-id", default="ai-p620-01", help="Node ID")
    parser.add_argument("--environment", default="production", help="Environment")
    parser.add_argument("--hardware-profile", default="p620_dual_b65", help="Hardware profile")
    parser.add_argument("--git-sha", default="0000000000000000000000000000000000000000", help="Git commit SHA")
    parser.add_argument("--simulated", action="store_true", help="Mark run as simulated")
    parser.add_argument("--input-json", default=None, help="Path to input checks JSON")
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
        spec_path = Path(args.hardware_profile_json)
        if spec_path.exists():
            profile_spec = json.loads(spec_path.read_text(encoding="utf-8"))
        else:
            profile_spec = json.loads(args.hardware_profile_json)

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
