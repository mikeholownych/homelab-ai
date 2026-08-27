#!/usr/bin/env python3
"""Pure expected/observed hardware classifier and evidence splitter."""

import argparse
import json
from pathlib import Path


def _check(rule, expected, observed, passed, severity, rationale):
    return {"rule": rule, "expected": expected, "observed": observed,
            "status": "pass" if passed else "fail", "severity": "informational" if passed else severity,
            "rationale": rationale}


def classify(profile, observed):
    checks = []
    product_name = observed.get("dmi", {}).get("product_name", "")
    platform = profile["platform"]
    expected_model = platform["machine_type_model"]
    aliases = [pattern for pattern in platform.get("product_name_patterns", [])
               if pattern != expected_model]
    machine_ok = expected_model in product_name or any(pattern in product_name for pattern in aliases)
    checks.append(_check("machine_model", expected_model, product_name, machine_ok,
                         "blocking", "The hardware profile is valid only for its declared machine type."))
    cpu_model = observed.get("cpu", {}).get("model", "")
    cpu_ok = any(pattern in cpu_model for pattern in profile["cpu"]["model_patterns"])
    checks.append(_check("cpu_model", profile["cpu"]["model_patterns"], cpu_model, cpu_ok,
                         "blocking", "CPU identity must match the version-controlled platform profile."))
    expected_gpus = profile["gpu"]["count_expected"]
    gpus = observed.get("gpus", [])
    pci = observed.get("pci", [])
    approved = {(str(item["vendor_id"]).lower(), str(item["device_id"]).lower()): item["model"]
                for item in profile["gpu"]["approved_pci_devices"]}
    approved_ids = set(approved)
    approved_gpus = [gpu for gpu in gpus
                     if (str(gpu.get("vendor_id", "")).lower(),
                         str(gpu.get("device_id", "")).lower()) in approved_ids]
    approved_pci = [item for item in pci
                    if (str(item.get("vendor_id", "")).lower(),
                        str(item.get("device_id", "")).lower()) in approved_ids]
    checks.append(_check("gpu_count", expected_gpus, [gpu.get("bdf") for gpu in approved_gpus],
                         len(approved_gpus) == expected_gpus, "blocking",
                         "All intended accelerators must enumerate; only approved PCI devices count."))
    identities = [{"bdf": gpu.get("bdf"), "vendor_id": gpu.get("vendor_id"),
                   "device_id": gpu.get("device_id")} for gpu in approved_gpus]
    pci_by_bdf = {str(item.get("bdf", "")).lower(): item for item in pci if item.get("bdf")}
    model_ok = len(approved_gpus) == expected_gpus and all(
        str(gpu.get("bdf", "")).lower() in pci_by_bdf
        and str(pci_by_bdf[str(gpu.get("bdf", "")).lower()].get("vendor_id", "")).lower() ==
        str(gpu.get("vendor_id", "")).lower()
        and str(pci_by_bdf[str(gpu.get("bdf", "")).lower()].get("device_id", "")).lower() ==
        str(gpu.get("device_id", "")).lower()
        for gpu in approved_gpus
    )
    checks.append(_check("gpu_model_match", profile["gpu"]["approved_pci_devices"], identities, model_ok,
                         "blocking", "GPU identity is resolved only from approved vendor/device PCI IDs."))
    unexpected = [{"bdf": gpu.get("bdf"), "vendor_id": gpu.get("vendor_id"),
                   "device_id": gpu.get("device_id")} for gpu in gpus
                  if (str(gpu.get("vendor_id", "")).lower(),
                      str(gpu.get("device_id", "")).lower()) not in approved_ids]
    checks.append(_check("unexpected_gpu_devices", "only approved accelerator PCI IDs", unexpected,
                         not unexpected, "warning",
                         "Anything outside the approved accelerator set must be removed from the certified design."))
    memory_target = profile["gpu"]["expected_models"][0]["memory_gib"]["approximate"]
    memory_tolerance = profile["gpu"]["expected_models"][0]["memory_gib"]["tolerance_gib"]
    level_zero = observed.get("level_zero_devices", [])
    pci_bdfs = {str(gpu.get("bdf", "")).lower() for gpu in approved_gpus}
    level_zero_by_bdf = {str(device.get("bdf", "")).lower(): device for device in level_zero
                         if device.get("bdf")}
    trustworthy_l0 = (len(level_zero) == expected_gpus and set(level_zero_by_bdf) == pci_bdfs and
                      all(device.get("memory_source") == "level_zero_global_memory"
                          for device in level_zero))
    gpu_memory = [level_zero_by_bdf.get(bdf, {}).get("memory_gib") for bdf in sorted(pci_bdfs)]
    gpu_memory_ok = len(gpu_memory) == expected_gpus and all(
        isinstance(value, (int, float)) and abs(value - memory_target) <= memory_tolerance
        for value in gpu_memory
    )
    checks.append(_check("gpu_memory", f"{memory_target} GiB +/- {memory_tolerance} GiB", gpu_memory,
                         trustworthy_l0 and gpu_memory_ok, "blocking",
                         "VRAM must come from BDF-correlated Level Zero global-memory diagnostics, never BAR size."))
    checks.append(_check("level_zero_detected", {"count": expected_gpus, "bdfs": sorted(pci_bdfs)},
                         level_zero, trustworthy_l0, "blocking",
                         "Exactly two trustworthy Level Zero devices must bind one-to-one to GPU PCI BDFs."))
    rebar_targets = [item.get("rebar_enabled") for item in approved_pci]
    rebar_ok = len(approved_pci) == expected_gpus and all(value is True for value in rebar_targets)
    checks.append(_check("resizable_bar_enabled", True, rebar_targets,
                         rebar_ok, "blocking", "Large BAR is required for the intended GPU memory mapping."))
    above4g = observed.get("firmware", {}).get("above_4g_decoding", {})
    above4g_value = above4g.get("value") if isinstance(above4g, dict) else None
    if above4g_value is None:
        checks.append({"rule": "above_4g_decoding_enabled", "expected": True, "observed": above4g,
                       "status": profile["firmware"]["above_4g_decoding"]["undiscoverable_status"],
                       "severity": "informational",
                       "rationale": "Linux does not expose an authoritative setting; commissioning must verify BIOS."})
    else:
        checks.append(_check("above_4g_decoding_enabled", True, above4g, above4g_value is True,
                             "blocking", "Only an explicit sourced BIOS observation may satisfy this check."))
    ratio_min = profile["pcie"]["material_degradation"]["minimum_negotiated_to_slot_ratio"]
    unhealthy = []
    for index, link in enumerate(approved_pci):
        slot_width = int(link.get("slot_width") or 0)
        current_width = int(link.get("current_width") or 0)
        generation = int(link.get("current_generation") or 0)
        expected_generation = profile["pcie"]["host_link"]["expected_negotiated_generation"]
        if not slot_width or current_width / slot_width < ratio_min or generation < expected_generation:
            unhealthy.append({"gpu": index, "slot_width": slot_width, "current_width": current_width,
                              "expected_generation": expected_generation, "current_generation": generation})
    checks.append(_check("pcie_link_health", f">={ratio_min} of each physical slot capability", unhealthy,
                         len(approved_pci) == expected_gpus and not unhealthy, "blocking",
                         "Negotiated width is compared with that GPU's actual physical slot capability."))
    memory = observed.get("memory", {}).get("total_gib")
    target = profile["memory"]["installed_gib"]["expected"]
    tolerance = profile["memory"]["installed_gib"]["tolerance_gib"]
    checks.append(_check("memory_capacity", target, memory,
                         isinstance(memory, (int, float)) and abs(memory - target) <= tolerance,
                         "warning", "Initial memory capacity is allowed to vary within policy tolerance."))
    psus = observed.get("power_supplies", [])
    checks.append({"rule": "psu_inventory", "expected": "record where discoverable", "observed": psus,
                   "status": "pass" if psus else "not_tested", "severity": "informational",
                   "rationale": "Workstation PSU telemetry is not always exposed by firmware."})
    simulated = observed.get("simulated") is True
    blocking = any(item["status"] == "fail" and item["severity"] == "blocking" for item in checks)
    warning = any(item["status"] == "fail" and item["severity"] == "warning" for item in checks)
    required_incomplete = (
        profile["firmware"]["above_4g_decoding"]["required"] is True
        and any(item["rule"] == "above_4g_decoding_enabled" and item["status"] == "not_tested"
                for item in checks)
    )
    return {"schema_version": "1.0.0", "simulated": simulated, "physical_acceptance": False,
            "status": "blocking" if blocking else "not_tested" if required_incomplete else
            "warning" if warning else "pass", "checks": checks}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True)
    parser.add_argument("--observed", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    profile = json.loads(Path(args.profile).read_text())
    observed = json.loads(Path(args.observed).read_text())
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    result = classify(profile, observed)
    def evidence(expected, actual, rules, rationale):
        relevant = [item for item in result["checks"] if item["rule"] in rules]
        failed = [item for item in relevant if item["status"] == "fail"]
        unproven = [item for item in relevant if item["status"] == "not_tested"]
        severity = "blocking" if any(item["severity"] == "blocking" for item in failed) else \
            "warning" if failed else "informational"
        return {"simulated": observed.get("simulated", False), "expected": expected, "observed": actual,
                "severity": severity, "status": "fail" if failed else "not_tested" if unproven else "pass",
                "rationale": rationale,
                "checks": relevant}

    documents = {
        "hardware.json": evidence(profile, observed,
                                  {"machine_model", "cpu_model", "gpu_count", "gpu_model_match",
                                   "gpu_memory", "level_zero_detected", "unexpected_gpu_devices"},
                                  "Platform and accelerator comparison against the selected Git profile."),
        "pci.json": evidence(profile["pcie"], observed.get("pci", []),
                             {"pcie_link_health", "resizable_bar_enabled"},
                             "Link health uses each observed physical slot capability."),
        "memory.json": evidence(profile["memory"], observed.get("memory", {}), {"memory_capacity"},
                                "Capacity and DIMM topology are recorded independently."),
        "storage.json": evidence("discovered", observed.get("storage", []), set(),
                                 "NVMe identity, size, and firmware are discovery data."),
        "firmware.json": evidence(profile["firmware"], observed.get("firmware", {}),
                                  {"above_4g_decoding_enabled", "psu_inventory"},
                                  "BIOS, device firmware, decoding state, and discoverable PSU data."),
    }
    for name, document in documents.items():
        (output / name).write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, separators=(",", ":")))
    raise SystemExit(2 if result["status"] == "blocking" else 3 if result["status"] == "not_tested" else 0)


if __name__ == "__main__":
    main()
