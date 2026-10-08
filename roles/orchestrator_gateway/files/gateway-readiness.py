#!/usr/bin/env python3
"""Wait for each T5820 worker using its own configured API credential."""
import json
import os
import time
import urllib.error
import urllib.request


def ready(spec):
    token_path = spec.get("token_file", "")
    if not os.path.isabs(token_path):
        root = os.environ.get("CREDENTIALS_DIRECTORY", "")
        if not root:
            return False
        token_path = os.path.join(root, token_path)
    try:
        token = open(token_path, encoding="utf-8").read().strip()
        endpoint = spec["endpoint"].rstrip("/") + "/v1/models"
        request = urllib.request.Request(endpoint, headers={"Authorization": "Bearer " + token})
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status == 200
    except (OSError, KeyError, TypeError, ValueError, urllib.error.URLError):
        return False


def required_specs(specs):
    """Ignore inventory workers deliberately stopped for candidate qualification."""
    return [spec for spec in specs if spec.get("state", "running") != "stopped"]


def main():
    try:
        specs = json.loads(os.environ["ORCHESTRATOR_WORKER_SPECS"])
        if not isinstance(specs, list) or not specs:
            return 78
        specs = required_specs(specs)
        if not specs:
            return 78
        timeout = int(os.environ.get("ORCHESTRATOR_GATEWAY_DEPENDENCY_TIMEOUT_SECONDS", "1200"))
    except (KeyError, TypeError, ValueError):
        return 78
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(ready(spec) for spec in specs):
            return 0
        time.sleep(10)
    return 78


if __name__ == "__main__":
    raise SystemExit(main())
