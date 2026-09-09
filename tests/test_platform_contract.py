from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_ROOT = REPO_ROOT / "inventory" / "production"


def load_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_supported_platforms_declare_exact_release_metadata() -> None:
    group_vars = load_yaml(PRODUCTION_ROOT / "group_vars" / "all.yml")

    assert group_vars["supported_platforms"] == {
        "24.04": {
            "codename": "noble",
            "apt_suites": ["noble", "noble-updates", "noble-backports", "noble-security"],
        },
        "26.04": {
            "codename": "resolute",
            "apt_suites": ["resolute", "resolute-updates", "resolute-backports", "resolute-security"],
        },
    }


def test_supported_platform_apt_suites_do_not_overlap() -> None:
    group_vars = load_yaml(PRODUCTION_ROOT / "group_vars" / "all.yml")
    supported_platforms = group_vars["supported_platforms"]

    suites_2404 = set(supported_platforms["24.04"]["apt_suites"])
    suites_2604 = set(supported_platforms["26.04"]["apt_suites"])

    assert suites_2404.isdisjoint(suites_2604)


def test_ai_5820_01_declares_platform_release_and_codename() -> None:
    host_vars = load_yaml(PRODUCTION_ROOT / "host_vars" / "ai-5820-01.yml")

    assert host_vars["platform_release"] == "26.04"
    assert host_vars["platform_codename"] == "resolute"
