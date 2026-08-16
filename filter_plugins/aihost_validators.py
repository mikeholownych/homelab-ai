from __future__ import annotations

import ipaddress
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
        try:
            port = int(value)
        except (TypeError, ValueError):
            invalid.append(str(value))
            continue
        if port < 1 or port > 65535:
            invalid.append(str(value))
    return invalid


class FilterModule:
    def filters(self) -> dict[str, object]:
        return {
            "aihost_invalid_cidrs": invalid_cidrs,
            "aihost_invalid_ports": invalid_ports,
            "aihost_boot_param_allowed": self.boot_param_allowed,
        }

    @staticmethod
    def boot_param_allowed(value: object, patterns: Iterable[object]) -> bool:
        import re

        string_value = str(value)
        return any(re.match(str(pattern), string_value) for pattern in patterns)
