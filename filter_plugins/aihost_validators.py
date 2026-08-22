from __future__ import annotations

import ipaddress
from pathlib import PurePosixPath
from typing import Iterable


def invalid_cidrs(values: Iterable[object]) -> list[str]:
    invalid: list[str] = []
    for value in values:
        try:
            ipaddress.ip_network(str(value), strict=False)
        except ValueError:
            invalid.append(str(value))
    return invalid


def invalid_ports(values: Iterable[object]) -> list[str]:
    invalid: list[str] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int):
            invalid.append(str(value))
            continue
        port = value
        if port < 1 or port > 65535:
            invalid.append(str(value))
    return invalid


def invalid_logrotate_paths(values: Iterable[object]) -> list[str]:
    invalid: list[str] = []
    allowed_root = PurePosixPath("/var/log/local-ai")

    for value in values:
        if not isinstance(value, str):
            invalid.append(str(value))
            continue

        candidate = PurePosixPath(value)
        if not candidate.is_absolute():
            invalid.append(value)
            continue

        if candidate == PurePosixPath("/var/log/*.log"):
            invalid.append(value)
            continue

        if candidate.parent != allowed_root:
            invalid.append(value)
            continue

        if candidate.name in {"", ".", ".."}:
            invalid.append(value)
            continue

        if "/" in candidate.name:
            invalid.append(value)
            continue

    return invalid


class FilterModule:
    def filters(self) -> dict[str, object]:
        return {
            "aihost_invalid_cidrs": invalid_cidrs,
            "aihost_invalid_ports": invalid_ports,
            "aihost_invalid_logrotate_paths": invalid_logrotate_paths,
            "aihost_boot_param_allowed": self.boot_param_allowed,
            "aihost_model_stamp": model_stamp,
        }

    @staticmethod
    def boot_param_allowed(value: object, patterns: Iterable[object]) -> bool:
        import re

        string_value = str(value)
        return any(re.match(str(pattern), string_value) for pattern in patterns)


def model_stamp(model: dict) -> str:
    """Stable stamp identifying a pinned model revision and its artifact hashes."""
    hashes = ",".join(sorted(str(artifact["sha256"]) for artifact in model.get("artifacts", [])))
    return f"{model.get('repo_id', '')}|{model.get('revision', '')}|{hashes}"
