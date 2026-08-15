from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

PRODUCTION_ROOTS = (
    ".github",
    "group_vars",
    "host_vars",
    "roles",
)

PRODUCTION_FILES = (
    ".ansible-lint",
    ".yamllint",
    "Makefile",
    "ansible.cfg",
    "baseline.yml",
    "benchmark.yml",
    "bootstrap.yml",
    "drift-check.yml",
    "facts-export.yml",
    "patch.yml",
    "requirements.txt",
    "requirements.yml",
    "site.yml",
    "upgrade.yml",
    "validate.yml",
)

SCANNED_SUFFIXES = {".cfg", ".ini", ".j2", ".txt", ".yaml", ".yml"}
SCANNED_FILENAMES = {"Makefile"}

BANNED_PATTERNS = {
    "ansible_vault_env_reference": re.compile(r"\$ANSIBLE_VAULT"),
    "mutable_latest": re.compile(r"(?<![\\w-])latest(?![\\w-])", re.IGNORECASE),
    "curl_pipe_shell": re.compile(r"curl\b[^\\n|]*\|\s*(?:sh|bash)\b", re.IGNORECASE),
    "wget_pipe_shell": re.compile(r"wget\b[^\\n|]*\|\s*(?:sh|bash)\b", re.IGNORECASE),
    "blanket_ignore_errors": re.compile(
        r"^\s*ignore_errors\s*:\s*(?:true|yes)\s*$", re.IGNORECASE | re.MULTILINE
    ),
}
APPROLE_SECRET_ID_PATTERN = re.compile(
    r"^\s*secret_id\s*:\s*['\"]?([A-Za-z0-9][A-Za-z0-9-]{7,})['\"]?\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def iter_production_files() -> list[Path]:
    explicit_paths = [REPO_ROOT / relpath for relpath in PRODUCTION_FILES]
    rooted_paths: list[Path] = []

    for root_name in PRODUCTION_ROOTS:
        root_path = REPO_ROOT / root_name
        if not root_path.exists():
            continue
        for path in root_path.rglob("*"):
            if path.is_file() and (
                path.suffix in SCANNED_SUFFIXES or path.name in SCANNED_FILENAMES
            ):
                rooted_paths.append(path)

    all_paths = explicit_paths + rooted_paths
    existing = [path for path in all_paths if path.exists() and path.is_file()]
    return sorted(set(existing))


class NoSecretsTests(unittest.TestCase):
    def test_repository_contains_no_banned_patterns(self) -> None:
        violations: list[str] = []
        for path in iter_production_files():
            relative_path = path.relative_to(REPO_ROOT)
            content = path.read_text(encoding="utf-8")
            for label, pattern in BANNED_PATTERNS.items():
                if pattern.search(content):
                    violations.append(f"{relative_path}: {label}")

            for match in APPROLE_SECRET_ID_PATTERN.finditer(content):
                value = match.group(1).lower()
                if value not in {"example", "placeholder", "changeme"}:
                    violations.append(f"{relative_path}: approle_secret_id_literal")

        self.assertEqual([], violations, f"Found banned content: {violations}")


if __name__ == "__main__":
    unittest.main()
