from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]

PRODUCTION_SCAN_ROOTS = (
    ".github",
    "group_vars",
    "host_vars",
    "inventory",
    "playbooks",
    "roles",
    "scripts",
)

PRODUCTION_ROOTS = (
    ".github",
    "group_vars",
    "host_vars",
    "inventory",
    "playbooks",
    "roles",
    "scripts",
)

PRODUCTION_FILES = (
    ".ansible-lint",
    ".yamllint",
    "Makefile",
    "ansible.cfg",
    "requirements.txt",
    "requirements.yml",
)

EXCLUDED_RELATIVE_PATHS = (
    Path("docs"),
    Path("evidence"),
    Path("tests/fixtures"),
)
EXCLUDED_PATH_PARTS = {
    ".git",
    ".pytest_cache",
    ".venv",
    ".worktrees",
    "__pycache__",
    ".ansible",
}
TEXT_FILE_SUFFIXES = {
    ".cfg",
    ".conf",
    ".env",
    ".ini",
    ".j2",
    ".py",
    ".service",
    ".sh",
    ".txt",
    ".yaml",
    ".yml",
}
TEXT_FILENAMES = {"Makefile"}
REQUIREMENTS_PIN_PATTERN = re.compile(
    r"^pyyaml==(?P<version>\S+)\s*\\?$", re.IGNORECASE | re.MULTILINE
)
YAML_SUFFIXES = {".yaml", ".yml"}

RAW_BANNED_PATTERNS = {
    "ansible_vault_env_reference": re.compile(r"\$ANSIBLE_VAULT"),
}
PIPE_TO_SHELL_PATTERNS = {
    "curl_pipe_shell": re.compile(r"\bcurl\b[\s\S]*?\|\s*(?:bash|sh)\b", re.IGNORECASE),
    "wget_pipe_shell": re.compile(r"\bwget\b[\s\S]*?\|\s*(?:bash|sh)\b", re.IGNORECASE),
}
RAW_COMMAND_SEGMENT_PATTERNS = {
    "curl_pipe_shell": re.compile(
        r"(?:^|[;&(|=:,]\s*|\bthen\b\s*)(?:sudo\s+)?(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*curl\b[\s\S]*?\|\s*(?:bash|sh)\b",
        re.IGNORECASE,
    ),
    "wget_pipe_shell": re.compile(
        r"(?:^|[;&(|=:,]\s*|\bthen\b\s*)(?:sudo\s+)?(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*wget\b[\s\S]*?\|\s*(?:bash|sh)\b",
        re.IGNORECASE,
    ),
}
COMMAND_KEYS = {"shell", "ansible.builtin.shell", "command", "ansible.builtin.command"}
ACTION_KEY = "action"
ACTION_COMMAND_PATTERN = re.compile(
    r"^(?:ansible\.builtin\.)?(?:shell|command)\b(?P<command>[\s\S]*)$",
    re.IGNORECASE,
)
LATEST_EXACT_KEYS = {"tag", "version", "state", "image", "container_image", "image_tag"}
LATEST_LIST_KEYS = {"images", "container_images"}
DOCKER_IMAGE_MODULE_KEYS = {"community.docker.docker_image", "docker_image"}
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
    "!vault |",
}
APPROLE_ALLOWED_JINJA_EXPRESSION = re.compile(r"^\{\{\s*[^}]+\s*\}\}$")


def is_path_excluded(path: Path, repo_root: Path) -> bool:
    relative_path = path.relative_to(repo_root)

    if any(part in EXCLUDED_PATH_PARTS for part in relative_path.parts):
        return True
    return any(
        relative_path == excluded_path or excluded_path in relative_path.parents
        for excluded_path in EXCLUDED_RELATIVE_PATHS
    )


def is_probably_binary(data: bytes) -> bool:
    if b"\x00" in data:
        return True
    if not data:
        return False

    text_bytes = bytearray({7, 8, 9, 10, 12, 13, 27})
    text_bytes.extend(range(0x20, 0x7F))
    non_text = sum(byte not in text_bytes for byte in data)
    return (non_text / len(data)) > 0.30


def is_scannable_text_file(path: Path) -> bool:
    data = path.read_bytes()
    if is_probably_binary(data):
        return False
    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return not is_probably_binary(data)


def read_scannable_text(path: Path) -> str | None:
    data = path.read_bytes()
    if is_probably_binary(data):
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def iter_production_files() -> list[Path]:
    explicit_paths = [REPO_ROOT / relpath for relpath in PRODUCTION_FILES]
    rooted_paths: list[Path] = []

    for root_name in PRODUCTION_SCAN_ROOTS:
        root_path = REPO_ROOT / root_name
        if not root_path.exists():
            continue
        for path in root_path.rglob("*"):
            if path.is_file() and not is_path_excluded(path, REPO_ROOT) and is_scannable_text_file(path):
                rooted_paths.append(path)

    all_paths = explicit_paths + rooted_paths
    existing = [
        path
        for path in all_paths
        if path.exists()
        and path.is_file()
        and not is_path_excluded(path, REPO_ROOT)
        and (
            path in explicit_paths
            or path.name in TEXT_FILENAMES
            or path.suffix in TEXT_FILE_SUFFIXES
            or is_scannable_text_file(path)
        )
    ]
    return sorted(set(existing))


def iter_yaml_nodes(node: object):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from iter_yaml_nodes(value)
    elif isinstance(node, list):
        for item in node:
            yield from iter_yaml_nodes(item)


def load_yaml_documents(content: str) -> list[object]:
    try:
        return list(yaml.safe_load_all(content))
    except yaml.YAMLError:
        return []


def is_latest_sensitive_key(key: str) -> bool:
    normalized_key = key.strip().lower()
    if normalized_key in LATEST_EXACT_KEYS:
        return True
    return normalized_key.endswith(("_image", "_tag", "_version"))


def value_has_mutable_latest(value: object) -> bool:
    if isinstance(value, str):
        normalized_value = value.strip().strip("'\"").lower()
        return normalized_value == "latest" or normalized_value.endswith(":latest")
    if isinstance(value, list):
        return any(value_has_mutable_latest(item) for item in value)
    return False


def contains_mutable_latest_violation(content: str) -> bool:
    for document in load_yaml_documents(content):
        for mapping in iter_yaml_nodes(document):
            for key, value in mapping.items():
                if not isinstance(key, str):
                    continue
                normalized_key = key.strip().lower()
                if normalized_key in DOCKER_IMAGE_MODULE_KEYS and isinstance(value, dict):
                    image_name = value.get("name")
                    if value_has_mutable_latest(image_name):
                        return True
                if not is_latest_sensitive_key(key):
                    if normalized_key in LATEST_LIST_KEYS and value_has_mutable_latest(value):
                        return True
                    continue
                if value_has_mutable_latest(value):
                    return True
    return False


def find_pipe_to_shell_violation(content: str, source_name: str) -> list[str]:
    violations: list[str] = []
    if Path(source_name).suffix in YAML_SUFFIXES:
        for document in load_yaml_documents(content):
            for mapping in iter_yaml_nodes(document):
                for key, value in mapping.items():
                    if not isinstance(key, str) or not isinstance(value, str):
                        continue
                    normalized_key = key.strip().lower()
                    if normalized_key in COMMAND_KEYS:
                        for label, pattern in PIPE_TO_SHELL_PATTERNS.items():
                            if pattern.search(normalize_shell_command(value)):
                                violations.append(label)
                    elif normalized_key == ACTION_KEY:
                        action_match = ACTION_COMMAND_PATTERN.match(value.strip())
                        if action_match:
                            action_command = normalize_shell_command(action_match.group("command"))
                            for label, pattern in PIPE_TO_SHELL_PATTERNS.items():
                                if pattern.search(action_command):
                                    violations.append(label)
        return violations

    for candidate in iter_raw_command_candidates(content, source_name):
        for label, pattern in RAW_COMMAND_SEGMENT_PATTERNS.items():
            if pattern.search(candidate):
                violations.append(label)
    return violations


def normalize_shell_command(command: str) -> str:
    normalized = re.sub(r"\\\s*\n\s*", " ", command)
    normalized = re.sub(r"\n\s*\|\s*", " | ", normalized)
    return normalized


def iter_raw_command_candidates(content: str, source_name: str):
    sanitized_content = strip_jinja_comments(content) if Path(source_name).suffix == ".j2" else content
    lines = sanitized_content.splitlines()
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if not stripped or stripped.startswith("#") or stripped.startswith("{#"):
            index += 1
            continue

        if line.startswith("\t"):
            candidate, next_index = collect_recipe_command(lines, index)
            if candidate is not None:
                yield candidate
            index = next_index
            continue

        if contains_raw_pipe_launcher(stripped):
            candidate, next_index = collect_raw_shell_command(lines, index)
            yield candidate
            index = next_index
            continue

        index += 1


def strip_jinja_comments(content: str) -> str:
    return re.sub(r"{#.*?#}", "", content, flags=re.DOTALL)


def contains_raw_pipe_launcher(command: str) -> bool:
    normalized = command.strip()
    return bool(
        re.search(
            r"(?:^|[;&]|\bthen\b)\s*(?:sudo\s+)?(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*(?:curl|wget)\b",
            normalized,
            re.IGNORECASE,
        )
    )


def collect_recipe_command(lines: list[str], start_index: int) -> tuple[str | None, int]:
    line = lines[start_index].lstrip()
    command = line.lstrip("@").strip()
    index = start_index + 1

    while index < len(lines):
        next_line = lines[index]
        next_stripped = next_line.strip()
        if not next_line.startswith("\t"):
            break
        if command.endswith("\\") or next_stripped.startswith("|"):
            command = f"{command.rstrip('\\').rstrip()} {next_stripped.lstrip('@').strip()}"
            index += 1
            continue
        break

    if re.match(r"^(?:echo|printf)\b", command):
        return None, index
    return normalize_shell_command(command), index


def collect_raw_shell_command(lines: list[str], start_index: int) -> tuple[str, int]:
    command = lines[start_index].strip()
    index = start_index + 1

    while index < len(lines):
        next_line = lines[index].strip()
        if command.endswith("\\") or next_line.startswith("|"):
            command = f"{command.rstrip('\\').rstrip()} {next_line}"
            index += 1
            continue
        break

    return normalize_shell_command(command), index


def contains_approle_secret_id_literal(content: str) -> bool:
    for match in APPROLE_SECRET_ID_PATTERN.finditer(content):
        raw_value = match.group("value").strip()
        normalized_value = raw_value.strip("'\"").strip()
        if normalized_value in APPROLE_ALLOWED_TOKENS:
            continue
        if APPROLE_ALLOWED_JINJA_EXPRESSION.fullmatch(normalized_value):
            continue
        if normalized_value.startswith("!vault"):
            continue
        return True
    return False


def find_banned_content(content: str, source_name: str = "inline.yml") -> list[str]:
    violations: list[str] = []
    if contains_mutable_latest_violation(content):
        violations.append("mutable_latest")
    for label, pattern in RAW_BANNED_PATTERNS.items():
        if pattern.search(content):
            violations.append(label)
    violations.extend(find_pipe_to_shell_violation(content, source_name))
    if re.search(r"^\s*ignore_errors\s*:\s*(?:true|yes)\s*$", content, re.IGNORECASE | re.MULTILINE):
        violations.append("blanket_ignore_errors")
    if contains_approle_secret_id_literal(content):
        violations.append("approle_secret_id_literal")
    return sorted(set(violations))


class NoSecretsPatternTests(unittest.TestCase):
    def test_iter_production_files_scans_playbooks_directory(self) -> None:
        production_files = {path.relative_to(REPO_ROOT).as_posix() for path in iter_production_files()}

        self.assertIn("playbooks/baseline.yml", production_files)
        self.assertNotIn("baseline.yml", production_files)

    def test_mutable_latest_detects_real_container_reference_usage(self) -> None:
        self.assertTrue(contains_mutable_latest_violation('tag: "latest"\n'))
        self.assertTrue(contains_mutable_latest_violation("container_image: latest\n"))
        self.assertTrue(
            contains_mutable_latest_violation(
                "container_images:\n"
                "  - ghcr.io/example/service:latest\n"
            )
        )
        self.assertTrue(
            contains_mutable_latest_violation(
                "image: ghcr.io/example/service:latest\n"
            )
        )
        self.assertTrue(
            contains_mutable_latest_violation(
                "community.docker.docker_image:\n"
                "  name: ghcr.io/example/service:latest\n"
            )
        )
        self.assertFalse(contains_mutable_latest_violation("latest_release_channel: stable\n"))
        self.assertFalse(contains_mutable_latest_violation("msg: latest packages are handled elsewhere\n"))

    def test_pipe_to_shell_detects_actual_shell_commands(self) -> None:
        self.assertIn("curl_pipe_shell", find_banned_content("shell: curl -fsSL https://example.test/install.sh | bash\n"))
        self.assertIn("curl_pipe_shell", find_banned_content("shell: curl https://example.test/bootstrap | sh -s -- --flag\n"))
        self.assertIn("wget_pipe_shell", find_banned_content("shell: wget -qO- https://example.test/install | bash\n"))
        self.assertIn(
            "curl_pipe_shell",
            find_banned_content(
                "action: ansible.builtin.shell set -o pipefail && curl -fsSL https://example.test/install.sh | bash\n"
            ),
        )
        self.assertIn(
            "curl_pipe_shell",
            find_banned_content(
                "shell: |\n"
                "  curl -fsSL https://example.test/install.sh\n"
                "  | bash\n"
            ),
        )
        self.assertEqual([], find_banned_content("shell: curl -fsSLO https://example.test/archive.tar.gz\n"))

    def test_pipe_to_shell_does_not_flag_comments_or_explanatory_strings(self) -> None:
        self.assertEqual(
            [],
            find_banned_content(
                '# Do not run curl https://example.test/install.sh | bash in docs.\n'
            ),
        )
        self.assertEqual(
            [],
            find_banned_content(
                'msg: "Avoid cargo-culting curl https://example.test/install.sh | bash"\n'
            ),
        )
        self.assertEqual(
            [],
            find_banned_content(
                'notes: "The string curl https://example.test/install.sh | bash is documentation only."\n'
            ),
        )
        self.assertEqual(
            [],
            find_banned_content(
                '@echo "Avoid curl https://example.test/install.sh | bash in docs."\n'
            , source_name="Makefile"),
        )
        self.assertEqual(
            [],
            find_banned_content(
                '{# Example only: curl https://example.test/install.sh | bash #}\n'
            ),
        )
        self.assertEqual(
            [],
            find_banned_content(
                "notes: |\n"
                "  curl https://example.test/install.sh | bash\n"
                "  is forbidden in real commands but this field is explanatory.\n"
            ),
        )

    def test_pipe_to_shell_detects_makefile_recipes_and_line_continuations(self) -> None:
        self.assertIn(
            "curl_pipe_shell",
            find_banned_content(
                "install:\n"
                "\tcurl -fsSL https://example.test/install.sh | bash\n"
            , source_name="Makefile"),
        )
        self.assertIn(
            "wget_pipe_shell",
            find_banned_content(
                "install:\n"
                "\twget -qO- https://example.test/install.sh \\\n"
                "\t| sh\n"
            , source_name="Makefile"),
        )

    def test_pipe_to_shell_detects_j2_shell_templates_and_skips_j2_comments(self) -> None:
        self.assertIn(
            "curl_pipe_shell",
            find_banned_content(
                "#!/usr/bin/env bash\n"
                "curl -fsSL {{ installer_url }} | bash\n"
            , source_name="templates/install.sh.j2"),
        )
        self.assertIn(
            "curl_pipe_shell",
            find_banned_content(
                "#!/usr/bin/env bash\n"
                "sudo curl -fsSL {{ installer_url }} | bash\n"
            , source_name="templates/install.sh.j2"),
        )
        self.assertIn(
            "curl_pipe_shell",
            find_banned_content(
                "#!/usr/bin/env bash\n"
                "if command -v curl >/dev/null; then curl -fsSL {{ installer_url }} | bash; fi\n"
            , source_name="templates/install.sh.j2"),
        )
        self.assertEqual(
            [],
            find_banned_content(
                "{# curl https://example.test/install.sh | bash #}\n"
            , source_name="templates/install.sh.j2"),
        )
        self.assertEqual(
            [],
            find_banned_content(
                "{#\n"
                "curl https://example.test/install.sh | bash\n"
                "#}\n"
                "printf 'safe template'\n"
            , source_name="templates/install.sh.j2"),
        )

    def test_approle_secret_id_detection_catches_literal_values_and_allows_templates(self) -> None:
        self.assertTrue(contains_approle_secret_id_literal("vault_approle_secret_id: super-secret-id\n"))
        self.assertTrue(contains_approle_secret_id_literal("approle_secret_id: 01234567-89ab-cdef\n"))
        self.assertTrue(
            contains_approle_secret_id_literal(
                'approle_secret_id: "{{ lookup_value }} literal-secret"\n'
            )
        )
        self.assertFalse(contains_approle_secret_id_literal("approle_secret_id: '{{ vault_approle_secret_id }}'\n"))
        self.assertFalse(contains_approle_secret_id_literal("secret_id: placeholder\n"))

    def test_requirements_txt_pins_pyyaml_directly(self) -> None:
        content = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
        match = REQUIREMENTS_PIN_PATTERN.search(content)

        self.assertIsNotNone(match, "requirements.txt must pin PyYAML directly")
        self.assertEqual("6.0.3", match.group("version"))


class NoSecretsRepositoryTests(unittest.TestCase):
    def test_production_scope_scans_declared_text_files_and_excludes_non_production_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            fixtures = {
                "scripts/bootstrap.sh": "curl -fsSL https://example.test/install.sh | bash\n",
                "scripts/audit.py": 'VAULT_ENV = "$ANSIBLE_VAULT_PASSWORD_FILE"\n',
                "roles/security/files/banner.txt": "approle_secret_id: literal-secret\n",
                "roles/security/templates/runtime.env": "TOKEN_SOURCE=$ANSIBLE_VAULT_PASSWORD_FILE\n",
                "roles/security/templates/agent.service": "ExecStart=/bin/sh -c 'curl -fsSL https://example.test/install.sh | bash'\n",
                "roles/security/files/entrypoint": "wget -qO- https://example.test/install.sh | sh\n",
                "docs/reference.sh": "curl -fsSL https://example.test/install.sh | bash\n",
                "tests/fixtures/example.env": "approle_secret_id: literal-secret\n",
                ".venv/bin/activate": "curl -fsSL https://example.test/install.sh | bash\n",
                "evidence/run.log": "approle_secret_id: literal-secret\n",
            }
            for relpath, content in fixtures.items():
                path = temp_root / relpath
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            original_root = globals()["REPO_ROOT"]
            try:
                globals()["REPO_ROOT"] = temp_root
                scanned_paths = {
                    path.relative_to(temp_root).as_posix() for path in iter_production_files()
                }
                violations = []
                for path in iter_production_files():
                    relative_path = path.relative_to(temp_root).as_posix()
                    content = read_scannable_text(path)
                    if content is None:
                        continue
                    for violation in find_banned_content(content, relative_path):
                        violations.append(f"{relative_path}: {violation}")
            finally:
                globals()["REPO_ROOT"] = original_root

        self.assertIn("scripts/bootstrap.sh", scanned_paths)
        self.assertIn("scripts/audit.py", scanned_paths)
        self.assertIn("roles/security/files/banner.txt", scanned_paths)
        self.assertIn("roles/security/templates/runtime.env", scanned_paths)
        self.assertIn("roles/security/templates/agent.service", scanned_paths)
        self.assertIn("roles/security/files/entrypoint", scanned_paths)
        self.assertNotIn("docs/reference.sh", scanned_paths)
        self.assertNotIn("tests/fixtures/example.env", scanned_paths)
        self.assertNotIn(".venv/bin/activate", scanned_paths)
        self.assertNotIn("evidence/run.log", scanned_paths)
        self.assertIn("scripts/bootstrap.sh: curl_pipe_shell", violations)
        self.assertIn("scripts/audit.py: ansible_vault_env_reference", violations)
        self.assertIn("roles/security/files/banner.txt: approle_secret_id_literal", violations)
        self.assertIn("roles/security/files/entrypoint: wget_pipe_shell", violations)

    def test_repository_contains_no_banned_patterns(self) -> None:
        violations: list[str] = []
        for path in iter_production_files():
            relative_path = path.relative_to(REPO_ROOT)
            content = read_scannable_text(path)
            if content is None:
                continue
            for violation in find_banned_content(content, relative_path.as_posix()):
                violations.append(f"{relative_path}: {violation}")

        self.assertEqual([], violations, f"Found banned content: {violations}")


if __name__ == "__main__":
    unittest.main()
