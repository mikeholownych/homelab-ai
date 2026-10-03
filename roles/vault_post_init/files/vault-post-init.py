#!/usr/bin/env python3
"""Converge the non-secret Vault configuration after operator initialization."""
from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import stat
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


AUDIT_PATH = "file/"
AUDIT_FILE = "/var/log/vault/audit.log"
KV_PATH = "secret/"
WORKLOAD_POLICY = """path \"secret/data/local-ai/services/orchestrator-gateway/client-token\" { capabilities = [\"read\"] }
path \"secret/data/local-ai/hosts/ai-5820-01/opencode-client-token\" { capabilities = [\"read\"] }
path \"secret/data/local-ai/services/vllm/api-key\" { capabilities = [\"read\"] }
path \"secret/data/local-ai/services/inference/worker1-api-key\" { capabilities = [\"read\"] }
path \"secret/data/local-ai/services/inference/worker2-api-key\" { capabilities = [\"read\"] }
"""
SNAPSHOT_POLICY = 'path "sys/storage/raft/snapshot" { capabilities = ["read", "sudo"] }\n'
APPROLES = {
    "t5820-platform": {
        "token_policies": ["t5820-platform"],
        "token_ttl": 600,
        "token_max_ttl": 3600,
        "secret_id_ttl": 0,
        "secret_id_num_uses": 0,
        "bind_secret_id": True,
        "token_type": "default",
    },
    "vault-snapshot-export": {
        "token_policies": ["vault-snapshot-export"],
        "token_ttl": 300,
        "token_max_ttl": 600,
        "secret_id_ttl": 0,
        "secret_id_num_uses": 0,
        "bind_secret_id": True,
        "token_type": "default",
    },
}
SEEDS = {
    "gateway_client": ("local-ai/services/orchestrator-gateway/client-token", "token"),
    "opencode_client": ("local-ai/hosts/ai-5820-01/opencode-client-token", "token"),
    "vllm_compat": ("local-ai/services/vllm/api-key", "key"),
    "worker1": ("local-ai/services/inference/worker1-api-key", "key"),
    "worker2": ("local-ai/services/inference/worker2-api-key", "key"),
}
ROTATABLE = tuple(SEEDS)
# Records superseded by the engine-neutral worker slots. Their values were exposed, so every version is
# permanently removed (KV v2 metadata delete) instead of being left behind unreferenced.
RETIRED_PATHS = (
    "local-ai/services/vllm/worker1-api-key",
    "local-ai/services/vllm/worker2-api-key",
)
SAFE_NAME = re.compile(r"^[a-z0-9_-]+$")


class VaultError(RuntimeError):
    pass


class VaultAPI:
    def __init__(self, address: str, ca_file: Path, token_file: Path):
        for path, label in ((ca_file, "CA certificate"), (token_file, "root token")):
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
                raise VaultError(f"{label} source must be a regular file")
        if token_file.stat().st_mode & 0o077:
            raise VaultError("root token source must not be accessible to group or other")
        self.base = address.rstrip("/") + "/v1/"
        self.context = ssl.create_default_context(cafile=str(ca_file))
        self.token = token_file.read_text(encoding="utf-8").strip()
        if not self.token:
            raise VaultError("root token source is empty")

    def request(self, method: str, path: str, payload=None, allow_missing=False):
        headers = {"X-Vault-Token": self.token, "Content-Type": "application/json"}
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.base + path, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, context=self.context, timeout=15) as response:
                raw = response.read()
                return response.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as error:
            if allow_missing and error.code == 404:
                return 404, {}
            if method == "GET" and path == "sys/health" and error.code == 503:
                try:
                    health = json.loads(error.read())
                except (json.JSONDecodeError, UnicodeDecodeError):
                    raise VaultError("Vault health returned an invalid sealed-state response") from None
                if not isinstance(health, dict) or health.get("initialized") is not True or health.get("sealed") is not True:
                    raise VaultError("Vault health returned an unexpected HTTP 503 state") from None
                return 503, health
            raise VaultError(f"Vault API operation failed with HTTP {error.code}") from None
        except (urllib.error.URLError, TimeoutError, ssl.SSLError) as error:
            raise VaultError(f"Vault API operation failed ({type(error).__name__})") from None


def atomic_private_write(path: Path, value: str) -> bool:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.parent.stat().st_mode & 0o077:
        raise VaultError("AppRole handoff directory must not be accessible to group or other")
    if path.exists() and path.is_symlink():
        raise VaultError("AppRole handoff files must not be symlinks")
    content = (value + "\n").encode("utf-8")
    if path.exists() and path.read_bytes() == content:
        if stat.S_IMODE(path.stat().st_mode) == 0o400:
            return False
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o400)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return True


def ensure_mount(api: VaultAPI, path: str, expected_type: str, options: dict | None = None) -> bool:
    status, result = api.request("GET", "sys/mounts", allow_missing=False)
    mounts = result.get("data", {})
    current = mounts.get(path)
    if current is None:
        payload = {"type": expected_type}
        if options:
            payload["options"] = options
        api.request("POST", "sys/mounts/" + path.rstrip("/"), payload)
        return True
    if current.get("type") != expected_type:
        raise VaultError(f"Vault mount {path} has an unexpected engine type")
    for name, value in (options or {}).items():
        if current.get("options", {}).get(name) != value:
            raise VaultError(f"Vault mount {path} has conflicting {name} configuration")
    return False


def ensure_policy(api: VaultAPI, name: str, policy: str) -> bool:
    if not SAFE_NAME.fullmatch(name):
        raise VaultError("Invalid policy name")
    status, result = api.request("GET", "sys/policies/acl/" + name, allow_missing=True)
    if status == 200 and result.get("data", {}).get("policy", "").strip() == policy.strip():
        return False
    api.request("PUT", "sys/policies/acl/" + name, {"policy": policy})
    return True


def ensure_approle_mount(api: VaultAPI) -> bool:
    _, result = api.request("GET", "sys/auth")
    current = result.get("data", {}).get("approle/")
    if current is None:
        api.request("POST", "sys/auth/approle", {"type": "approle"})
        return True
    if current.get("type") != "approle":
        raise VaultError("Vault auth mount approle/ has an unexpected type")
    return False


def ensure_approle(api: VaultAPI, name: str, config: dict) -> bool:
    status, result = api.request("GET", "auth/approle/role/" + name, allow_missing=True)
    if status == 200:
        current = result.get("data", {})
        if all(current.get(key) == value for key, value in config.items()):
            return False
    api.request("POST", "auth/approle/role/" + name, config)
    return True


def login(api: VaultAPI, role_id: str, secret_id: str) -> bool:
    try:
        _, result = api.request(
            "POST", "auth/approle/login", {"role_id": role_id, "secret_id": secret_id}
        )
        return bool(result.get("auth", {}).get("client_token"))
    except VaultError as error:
        if "HTTP 400" in str(error):
            return False
        raise


def ensure_handoff_credentials(api: VaultAPI, name: str, directory: Path) -> bool:
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory_info = directory.lstat()
    if not stat.S_ISDIR(directory_info.st_mode) or stat.S_ISLNK(directory_info.st_mode) or directory_info.st_mode & 0o077:
        raise VaultError("AppRole handoff directory must be private and must not be a symlink")
    role_id_path = directory / "role-id"
    secret_id_path = directory / "secret-id"
    for path in (role_id_path, secret_id_path):
        if path.exists() or path.is_symlink():
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_mode & 0o077:
                raise VaultError("AppRole handoff files must be private regular files")
    status, role_result = api.request(
        "GET", f"auth/approle/role/{name}/role-id", allow_missing=True
    )
    if status != 200:
        raise VaultError(f"Vault AppRole {name} did not provide a RoleID")
    actual_role_id = role_result.get("data", {}).get("role_id", "")
    if not actual_role_id:
        raise VaultError(f"Vault AppRole {name} returned an empty RoleID")

    current_role_id = role_id_path.read_text().strip() if role_id_path.is_file() else ""
    current_secret_id = secret_id_path.read_text().strip() if secret_id_path.is_file() else ""
    role_changed = current_role_id != actual_role_id
    secret_valid = bool(current_secret_id) and not role_changed and login(
        api, actual_role_id, current_secret_id
    )
    secret_id_changed = False
    if not secret_valid:
        _, generated = api.request(
            "POST", f"auth/approle/role/{name}/secret-id", {}
        )
        current_secret_id = generated.get("data", {}).get("secret_id", "")
        if not current_secret_id:
            raise VaultError(f"Vault AppRole {name} failed to issue a SecretID")
        if not login(api, actual_role_id, current_secret_id):
            raise VaultError(f"Vault AppRole {name} issued a SecretID that failed validation")
        secret_id_changed = True
    changed = atomic_private_write(role_id_path, actual_role_id) or role_changed
    changed = atomic_private_write(secret_id_path, current_secret_id) or secret_id_changed or changed
    return changed


def seed_missing_records(api: VaultAPI, seed_dir: Path) -> list[str]:
    created = []
    for name, (path, key) in SEEDS.items():
        source = seed_dir / name
        info = source.lstat()
        if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise VaultError(f"Bootstrap source for {name} must be a regular file")
        if info.st_mode & 0o077:
            raise VaultError(f"Bootstrap source for {name} must be private")
        status, _ = api.request("GET", "secret/data/" + path, allow_missing=True)
        if status == 404:
            value = source.read_text(encoding="utf-8").rstrip("\r\n")
            if not value:
                raise VaultError(f"Bootstrap source for {name} is empty")
            api.request("POST", "secret/data/" + path, {"data": {key: value}})
            created.append(name)
    return created


def remove_retired_records(api: VaultAPI) -> list[str]:
    removed = []
    for path in RETIRED_PATHS:
        status, _ = api.request("GET", "secret/metadata/" + path, allow_missing=True)
        if status == 200:
            api.request("DELETE", "secret/metadata/" + path)
            removed.append(path)
    return removed


def rotate_records(api: VaultAPI, names: list[str]) -> list[str]:
    """Write a fresh random value (new KV version) for each named record. Values are never printed."""
    import secrets
    import string

    rotated = []
    for name in names:
        if name not in SEEDS:
            raise VaultError(f"Unknown rotatable record: {name}")
        path, key = SEEDS[name]
        alphabet = string.ascii_letters + string.digits
        value = "".join(secrets.choice(alphabet) for _ in range(43))
        api.request("POST", "secret/data/" + path, {"data": {key: value}})
        rotated.append(name)
    return rotated


def unseal_if_needed(api: VaultAPI, health: dict, unseal_file: Path) -> dict:
    if not health.get("initialized"):
        raise VaultError("Vault must be initialized before post-initialization convergence")
    if not health.get("sealed"):
        return health
    info = unseal_file.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_mode & 0o077:
        raise VaultError("Unseal source must be a private regular file")
    share = unseal_file.read_text(encoding="utf-8").strip()
    if not share:
        raise VaultError("Unseal source is empty")
    api.request("POST", "sys/unseal", {"key": share})
    status, health = api.request("GET", "sys/health")
    if status != 200:
        raise VaultError("Vault health did not return HTTP 200 after unseal")
    if health.get("initialized") is not True:
        raise VaultError("Vault is not initialized after unseal")
    if health.get("sealed"):
        raise VaultError("Vault remains sealed after the supplied recovery share")
    return health


def converge(address: str, ca_file: Path, token_file: Path, handoff: Path, seed_dir: Path, unseal_file: Path | None = None, rotate: list[str] | None = None) -> dict:
    api = VaultAPI(address, ca_file, token_file)
    health_status, health = api.request("GET", "sys/health")
    if health_status == 503:
        if health.get("initialized") is not True or health.get("sealed") is not True:
            raise VaultError("Vault health returned an unexpected HTTP 503 state")
    elif health_status != 200:
        raise VaultError(f"Vault health returned unexpected HTTP {health_status}")
    if unseal_file is not None:
        health = unseal_if_needed(api, health, unseal_file)
    if not health.get("initialized") or health.get("sealed"):
        raise VaultError("Vault must already be initialized and unsealed; initialization is never performed here")
    api.request("GET", "sys/mounts")

    changed = []
    status, audit = api.request("GET", "sys/audit")
    devices = audit.get("data", {}) if status == 200 else {}
    existing_audit = devices.get(AUDIT_PATH)
    if existing_audit is None:
        api.request(
            "PUT", "sys/audit/" + AUDIT_PATH.rstrip("/"),
            {"type": "file", "options": {"file_path": AUDIT_FILE}},
        )
        changed.append("audit-device")
    elif existing_audit.get("type") != "file" or existing_audit.get("options", {}).get("file_path") != AUDIT_FILE:
        raise VaultError("Vault audit device exists with conflicting type or destination")

    if ensure_mount(api, KV_PATH, "kv", {"version": "2"}):
        changed.append("kv-v2-mount")
    if ensure_approle_mount(api):
        changed.append("approle-auth-mount")
    if ensure_policy(api, "t5820-platform", WORKLOAD_POLICY):
        changed.append("t5820-platform-policy")
    if ensure_policy(api, "vault-snapshot-export", SNAPSHOT_POLICY):
        changed.append("vault-snapshot-export-policy")
    for name, config in APPROLES.items():
        if ensure_approle(api, name, config):
            changed.append(name + "-approle")

    seeded = seed_missing_records(api, seed_dir)
    if seeded:
        changed.append("workload-secret-bootstrap")
    removed = remove_retired_records(api)
    if removed:
        changed.append("retired-records-removed")
    rotated = rotate_records(api, rotate or [])
    if rotated:
        changed.append("rotated-records")
    workload_handoff_changed = ensure_handoff_credentials(
        api, "t5820-platform", handoff / "approle"
    )
    snapshot_handoff_changed = ensure_handoff_credentials(
        api, "vault-snapshot-export", handoff / "snapshot-approle"
    )
    if workload_handoff_changed:
        changed.append("t5820-approle-handoff")
    if snapshot_handoff_changed:
        changed.append("snapshot-approle-handoff")
    return {
        "changed": bool(changed),
        "changed_resources": changed,
        "workload_handoff_changed": workload_handoff_changed,
        "snapshot_handoff_changed": snapshot_handoff_changed,
        "seeded_records": seeded,
        "rotated_records": rotated,
        "retired_records_removed": removed,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault-addr", required=True)
    parser.add_argument("--ca-cert", required=True)
    parser.add_argument("--root-token-file", required=True)
    parser.add_argument("--handoff-dir", required=True)
    parser.add_argument("--seed-dir", required=True)
    parser.add_argument("--unseal-key-file", required=True)
    parser.add_argument("--rotate", action="append", default=[], choices=ROTATABLE,
                        help="write a fresh random value for this record (repeatable)")
    args = parser.parse_args()
    result = converge(
        args.vault_addr,
        Path(args.ca_cert),
        Path(args.root_token_file),
        Path(args.handoff_dir),
        Path(args.seed_dir),
        Path(args.unseal_key_file),
        args.rotate,
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Vault post-initialization convergence failed safely: {error}", file=__import__("sys").stderr)
        raise SystemExit(1)
