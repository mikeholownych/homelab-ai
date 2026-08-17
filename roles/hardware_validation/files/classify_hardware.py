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
    expected_model = profile["platform"]["machine_type_model"]
    checks.append(_check("machine_model", expected_model, product_name, expected_model in product_name,
                         "blocking", "The hardware profile is valid only for its declared machine type."))
    cpu_model = observed.get("cpu", {}).get("model", "")
    cpu_ok = any(pattern in cpu_model for pattern in profile["cpu"]["model_patterns"])
    checks.append(_check("cpu_model", profile["cpu"]["model_patterns"], cpu_model, cpu_ok,
                         "blocking", "CPU identity must match the version-controlled platform profile."))
    expected_gpus = profile["gpu"]["count_expected"]
    gpus = observed.get("gpus", [])
    checks.append(_check("gpu_count", expected_gpus, len(gpus), len(gpus) == expected_gpus,
                         "blocking", "All intended accelerators must enumerate."))
    models = [gpu.get("model", "") for gpu in gpus]
    model_ok = len(gpus) == expected_gpus and all("Intel Arc Pro B65" in model for model in models)
    checks.append(_check("gpu_model_match", "Intel Arc Pro B65", models, model_ok,
                         "blocking", "Unexpected accelerators invalidate the runtime baseline."))
    memory_target = profile["gpu"]["expected_models"][0]["memory_gib"]["approximate"]
    memory_tolerance = profile["gpu"]["expected_models"][0]["memory_gib"]["tolerance_gib"]
    gpu_memory = [gpu.get("memory_gib") for gpu in gpus]
    gpu_memory_ok = len(gpu_memory) == expected_gpus and all(
        isinstance(value, (int, float)) and abs(value - memory_target) <= memory_tolerance
        for value in gpu_memory
    )
    checks.append(_check("gpu_memory", f"{memory_target} GiB +/- {memory_tolerance} GiB", gpu_memory,
                         gpu_memory_ok, "blocking", "Each GPU must expose its expected large memory BAR."))
    l0_count = sum(bool(gpu.get("level_zero")) for gpu in gpus)
    checks.append(_check("level_zero_detected", expected_gpus, l0_count, l0_count == expected_gpus,
                         "blocking", "Each accelerator requires a Level Zero device."))
    pci = observed.get("pci", [])
    rebar_ok = len(pci) == expected_gpus and all(item.get("rebar_enabled") is True for item in pci)
    checks.append(_check("resizable_bar_enabled", True, [item.get("rebar_enabled") for item in pci],
                         rebar_ok, "blocking", "Large BAR is required for the intended GPU memory mapping."))
    above4g = observed.get("firmware", {}).get("above_4g_decoding")
    checks.append(_check("above_4g_decoding_enabled", True, above4g, above4g is True,
                         "blocking", "Above 4G decoding is required for dual large-memory GPUs."))
    ratio_min = profile["pcie"]["material_degradation"]["minimum_negotiated_to_slot_ratio"]
    unhealthy = []
    for index, link in enumerate(pci):
        slot_width = int(link.get("slot_width") or 0)
        current_width = int(link.get("current_width") or 0)
        generation = int(link.get("current_generation") or 0)
        expected_generation = min(int(link.get("max_generation") or 0),
                                  profile["pcie"]["host_link"]["max_generation"])
        if not slot_width or current_width / slot_width < ratio_min or generation < expected_generation:
            unhealthy.append({"gpu": index, "slot_width": slot_width, "current_width": current_width,
                              "expected_generation": expected_generation, "current_generation": generation})
    checks.append(_check("pcie_link_health", f">={ratio_min} of each physical slot capability", unhealthy,
                         len(pci) == expected_gpus and not unhealthy, "blocking",
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
    return {"schema_version": "1.0.0", "simulated": simulated, "physical_acceptance": False if simulated else not blocking,
            "status": "blocking" if blocking else "warning" if warning else "pass", "checks": checks}


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
        severity = "blocking" if any(item["severity"] == "blocking" for item in failed) else \
            "warning" if failed else "informational"
        return {"simulated": observed.get("simulated", False), "expected": expected, "observed": actual,
                "severity": severity, "status": "fail" if failed else "pass", "rationale": rationale,
                "checks": relevant}

    documents = {
        "hardware.json": evidence(profile, observed,
                                  {"machine_model", "cpu_model", "gpu_count", "gpu_model_match",
                                   "gpu_memory", "level_zero_detected"},
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
    raise SystemExit(2 if result["status"] == "blocking" else 0)


if __name__ == "__main__":
    main()
