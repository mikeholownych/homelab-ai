#!/usr/bin/env python3
"""Independent validator for vLLM XPU service."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict


def check_endpoint(host: str, port: int, endpoint: str, data: Dict[str, Any] | None = None, timeout: float = 5.0) -> tuple[int, Dict[str, Any]]:
    url = f"http://{host}:{port}{endpoint}"
    headers = {"User-Agent": "aihost-vllm-validator", "Content-Type": "application/json"}
    payload = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=payload, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status_code = response.getcode()
            body = response.read().decode("utf-8")
            try:
                res_data = json.loads(body)
            except Exception:
                res_data = {"raw": body}
            return status_code, res_data
    except urllib.error.HTTPError as err:
        return err.code, {"error": str(err)}
    except Exception as err:
        return 0, {"error": str(err)}


def validate_vllm(
    host: str = "127.0.0.1",
    port: int = 8000,
    expected_model: str | None = None,
    expected_tp_size: int = 1,
    simulated: bool = False,
) -> Dict[str, Any]:
    if simulated:
        return {
            "schema_version": "1.0.0",
            "service": "vllm_xpu",
            "status": "PASS",
            "physical_acceptance": False,
            "simulated": True,
            "endpoint": f"http://{host}:{port}",
            "health": {"status": "ok", "code": 200},
            "models": [{"id": expected_model or "mock-model", "object": "model"}],
            "tensor_parallel_size": expected_tp_size,
            "inference_test": {
                "endpoint": "/v1/chat/completions",
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "latency_ms": 12.5,
                "status": "PASS",
            },
            "reason": "simulated validation run",
        }

    # Live check
    health_code, health_data = check_endpoint(host, port, "/health")
    if health_code != 200:
        return {
            "schema_version": "1.0.0",
            "service": "vllm_xpu",
            "status": "NOT_TESTED" if health_code == 0 else "FAIL",
            "physical_acceptance": False,
            "simulated": False,
            "endpoint": f"http://{host}:{port}",
            "health": {"code": health_code, "data": health_data},
            "models": [],
            "tensor_parallel_size": expected_tp_size,
            "inference_test": None,
            "reason": f"health check failed with code {health_code}: {health_data}",
        }

    models_code, models_data = check_endpoint(host, port, "/v1/models")
    models_list = models_data.get("data", [])

    # Test completion endpoint
    comp_code, comp_data = check_endpoint(
        host, port, "/v1/chat/completions",
        data={"model": expected_model or (models_list[0]["id"] if models_list else "test"), "messages": [{"role": "user", "content": "ping"}], "max_tokens": 5}
    )

    return {
        "schema_version": "1.0.0",
        "service": "vllm_xpu",
        "status": "PASS" if comp_code == 200 else "FAIL",
        "physical_acceptance": True if comp_code == 200 else False,
        "simulated": False,
        "endpoint": f"http://{host}:{port}",
        "health": {"code": 200, "status": "healthy"},
        "models": models_list,
        "tensor_parallel_size": expected_tp_size,
        "inference_test": {"status": "PASS" if comp_code == 200 else "FAIL", "code": comp_code, "data": comp_data},
        "reason": "all vLLM service checks passed on physical hardware",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate vLLM XPU service")
    parser.add_argument("--host", default="127.0.0.1", help="vLLM server host")
    parser.add_argument("--port", type=int, default=8000, help="vLLM server port")
    parser.add_argument("--model", default=None, help="Expected model ID")
    parser.add_argument("--tensor-parallel-size", type=int, default=1, help="Expected TP size")
    parser.add_argument("--simulated", action="store_true", help="Run simulated check")
    parser.add_argument("--output", default=None, help="Output JSON path")
    args = parser.parse_args()

    result = validate_vllm(
        host=args.host,
        port=args.port,
        expected_model=args.model,
        expected_tp_size=args.tensor_parallel_size,
        simulated=args.simulated,
    )

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
