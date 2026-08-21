#!/usr/bin/env python3
"""Independently validate every configured PyTorch XPU device."""
import argparse
import json
from pathlib import Path


def validate(torch, expected_count):
    result = {
        "schema_version": "1.0.0", "status": "FAIL", "physical_acceptance": False,
        "torch_version": getattr(torch, "__version__", "unknown"), "devices": [],
        "expected_count": expected_count, "observed_count": 0,
    }
    if not torch.xpu.is_available():
        result["error"] = "torch.xpu is unavailable"
        return result
    count = torch.xpu.device_count()
    result["device_count"] = count
    result["observed_count"] = count
    if count != expected_count:
        result["error"] = f"expected {expected_count} XPU devices, observed {count}"
        return result
    try:
        for index in range(count):
            props = torch.xpu.get_device_properties(index)
            left = torch.tensor(1.0, device=f"xpu:{index}")
            right = torch.tensor(2.0, device=f"xpu:{index}")
            value = (left + right).item()
            torch.xpu.synchronize(index)
            if value != 3.0:
                raise RuntimeError(f"device {index} returned {value}, expected 3.0")
            result["devices"].append({
                "index": index, "name": props.name,
                "memory_gib": round(props.total_memory / 1024**3, 3), "tensor_result": value,
            })
    except Exception as exc:  # runtime boundary must be represented as structured evidence
        result["error"] = str(exc)
        return result
    result["status"] = "PASS"
    return result


def write_result(path, result):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-count", type=int, required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--validation-output", required=True)
    args = parser.parse_args()
    try:
        import torch
    except ImportError as exc:
        result = {
            "schema_version": "1.0.0", "status": "FAIL", "physical_acceptance": False,
            "expected_count": args.expected_count, "observed_count": 0,
            "devices": [], "error": "torch import failed", "detail": str(exc),
        }
    else:
        result = validate(torch, args.expected_count)
    write_result(args.output, result)
    write_result(args.validation_output, result)
    print(json.dumps(result, sort_keys=True))
    raise SystemExit(0 if result["status"] == "PASS" else 2)


if __name__ == "__main__":
    main()
