from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

PRODUCTION_ROOTS = (
    ".github",
    "group_vars",
    "host_vars",
    "playbooks",
    "roles",
)

PRODUCTION_FILES = (
    ".ansible-lint",
    ".yamllint",
    "Makefile",
    "ansible.cfg",
    "requirements.txt",
    "requirements.yml",
)

SCANNED_SUFFIXES = {".cfg", ".ini", ".j2", ".txt", ".yaml", ".yml"}
SCANNED_FILENAMES = {"Makefile"}

LATEST_VALUE_PATTERN = re.compile(
    r"""
    ^
    \s*
    (?:
        image(?:_tag)? |
        tag |
        version |
        state
    )
    \s*:\s*
    ["']?
    latest
    ["']?
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)
BANNED_PATTERNS = {
    "ansible_vault_env_reference": re.compile(r"\$ANSIBLE_VAULT"),
    "curl_pipe_shell": re.compile(r"curl\b[^\n|]*\|\s*(?:bash|sh)\b", re.IGNORECASE),
    "wget_pipe_shell": re.compile(r"wget\b[^\n|]*\|\s*(?:bash|sh)\b", re.IGNORECASE),
    "blanket_ignore_errors": re.compile(
        r"^\s*ignore_errors\s*:\s*(?:true|yes)\s*$", re.IGNORECASE | re.MULTILINE
    ),
}
APPROLE_SECRET_ID_PATTERN = re.compile(
    r"""
    ^
    \s*
    (?:
        vault_approle_secret_id |
        approle_secret_id |
        secret_id
    )
    \s*:\s*
    (?P<value>.+?)
    \s*$
    """,
    re.IGNORECASE | re.MULTILINE | re.VERBOSE,
)
APPROLE_ALLOWED_TOKENS = {
    "example",
    "example-secret-id",
    "placeholder",
    "changeme",
    "{{ vault_approle_secret_id }}",
    "{{ approle_secret_id }}",
    "{{ secret_id }}",
    "!vault |",
}


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


def contains_mutable_latest_violation(content: str) -> bool:
    return any(LATEST_VALUE_PATTERN.match(line) for line in content.splitlines())


def contains_approle_secret_id_literal(content: str) -> bool:
    for match in APPROLE_SECRET_ID_PATTERN.finditer(content):
        raw_value = match.group("value").strip()
        normalized_value = raw_value.strip("'\"").strip()
        if normalized_value in APPROLE_ALLOWED_TOKENS:
            continue
        if normalized_value.startswith("{{") or normalized_value.startswith("!vault"):
            continue
        return True
    return False


def find_banned_content(content: str) -> list[str]:
    violations: list[str] = []
    if contains_mutable_latest_violation(content):
        violations.append("mutable_latest")
    for label, pattern in BANNED_PATTERNS.items():
        if pattern.search(content):
            violations.append(label)
    if contains_approle_secret_id_literal(content):
        violations.append("approle_secret_id_literal")
    return violations


class NoSecretsPatternTests(unittest.TestCase):
    def test_iter_production_files_scans_playbooks_directory(self) -> None:
        production_files = {path.relative_to(REPO_ROOT).as_posix() for path in iter_production_files()}

        self.assertIn("playbooks/baseline.yml", production_files)
        self.assertNotIn("baseline.yml", production_files)

    def test_mutable_latest_detects_real_key_value_usage_only(self) -> None:
        self.assertTrue(contains_mutable_latest_violation('tag: "latest"\n'))
        self.assertTrue(contains_mutable_latest_violation("state: latest\n"))
        self.assertFalse(contains_mutable_latest_violation("latest_release_channel: stable\n"))
        self.assertFalse(contains_mutable_latest_violation("msg: latest packages are handled elsewhere\n"))

    def test_pipe_to_shell_detects_curl_and_wget_variants(self) -> None:
        self.assertIn("curl_pipe_shell", find_banned_content("shell: curl -fsSL https://example.test/install.sh | bash\n"))
        self.assertIn("curl_pipe_shell", find_banned_content("shell: curl https://example.test/bootstrap | sh -s -- --flag\n"))
        self.assertIn("wget_pipe_shell", find_banned_content("shell: wget -qO- https://example.test/install | bash\n"))
        self.assertEqual([], find_banned_content("shell: curl -fsSLO https://example.test/archive.tar.gz\n"))

    def test_approle_secret_id_detection_catches_literal_values_and_allows_templates(self) -> None:
        self.assertTrue(contains_approle_secret_id_literal("vault_approle_secret_id: super-secret-id\n"))
        self.assertTrue(contains_approle_secret_id_literal("approle_secret_id: 01234567-89ab-cdef\n"))
        self.assertFalse(contains_approle_secret_id_literal("approle_secret_id: '{{ vault_approle_secret_id }}'\n"))
        self.assertFalse(contains_approle_secret_id_literal("secret_id: placeholder\n"))


class NoSecretsRepositoryTests(unittest.TestCase):
    def test_repository_contains_no_banned_patterns(self) -> None:
        violations: list[str] = []
        for path in iter_production_files():
            relative_path = path.relative_to(REPO_ROOT)
            content = path.read_text(encoding="utf-8")
            for violation in find_banned_content(content):
                violations.append(f"{relative_path}: {violation}")

        self.assertEqual([], violations, f"Found banned content: {violations}")


if __name__ == "__main__":
    unittest.main()
