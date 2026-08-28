from __future__ import annotations

import ipaddress
import re
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
            "aihost_catalog_invalid_entries": catalog_invalid_entries,
            "aihost_catalog_excess_variants": catalog_excess_variants,
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


def as_positive_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def catalog_invalid_entries(catalog: dict) -> list[str]:
    """Return human-readable problems with the curated model catalog structure."""
    problems: list[str] = []
    per_device = as_positive_float(catalog.get("model_catalog_per_device_vram_gib"))
    reserve = catalog.get("model_catalog_kv_cache_reserve_gib")
    if per_device is None:
        problems.append("model_catalog_per_device_vram_gib must be a positive number")
    if as_positive_float(reserve) is None or (isinstance(reserve, (int, float)) and reserve < 0):
        problems.append("model_catalog_kv_cache_reserve_gib must be a non-negative number")
    entries = catalog.get("model_catalog_entries", [])
    if not entries:
        problems.append("model_catalog_entries must be non-empty")
        return problems
    seen_ids: set[str] = set()
    for entry in entries:
        entry_id = str(entry.get("id", ""))
        if not entry_id:
            problems.append("catalog entry missing id")
            continue
        if entry_id in seen_ids:
            problems.append(f"duplicate catalog id: {entry_id}")
        seen_ids.add(entry_id)
        repo_id = str(entry.get("repo_id", ""))
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]+", repo_id):
            problems.append(f"{entry_id}: invalid repo_id {repo_id!r}")
        variants = entry.get("variants", [])
        if not variants:
            problems.append(f"{entry_id}: must declare at least one variant")
            continue
        for variant in variants:
            quant = str(variant.get("quant", ""))
            label = f"{entry_id}/{quant}"
            if as_positive_float(variant.get("size_gib")) is None:
                problems.append(f"{label}: size_gib must be a positive number")
            tp = variant.get("recommended_tensor_parallel")
            if tp is not None and tp not in (1, 2):
                problems.append(f"{label}: recommended_tensor_parallel must be 1, 2, or null")
    return problems


def catalog_excess_variants(catalog: dict) -> list[str]:
    """Return deployable catalog variants whose per-device share exceeds the VRAM pool.

    A variant is deployable when recommended_tensor_parallel is set; tp=null marks
    an intentionally excluded size (listed for honesty). The two B65 cards form a
    multi-device pool, and each variant must fit its per-device share plus a
    KV-cache/runtime reserve inside one card's memory.
    """
    per_device = as_positive_float(catalog.get("model_catalog_per_device_vram_gib"))
    reserve = as_positive_float(catalog.get("model_catalog_kv_cache_reserve_gib"))
    if per_device is None or reserve is None:
        return []
    excess: list[str] = []
    for entry in catalog.get("model_catalog_entries", []):
        entry_id = str(entry.get("id", ""))
        for variant in entry.get("variants", []):
            tp = variant.get("recommended_tensor_parallel")
            size = as_positive_float(variant.get("size_gib"))
            if tp is None or size is None:
                continue
            share = size / float(tp)
            if share + reserve > per_device:
                quant = str(variant.get("quant", ""))
                excess.append(f"{entry_id}/{quant}: {share:.1f} + {reserve:.0f} > {per_device:.0f} GiB/device")
    return excess
