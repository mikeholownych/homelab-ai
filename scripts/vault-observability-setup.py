#!/usr/bin/env python3
"""One-time, idempotent Vault setup for the observability stack (Grafana secrets).

Creates (or updates) the read-only policy and AppRole ``t5820-observability`` for ``secret/data/local-ai/observability/*``,
generates the three distinct Grafana secrets (``password``, ``secret_key``, ``renderer_token``) directly into
``secret/local-ai/observability/grafana-admin`` when absent (or with --rotate), and writes the AppRole RoleID/SecretID to
protected files under ``<handoff-dir>/observability-approle/`` (mode 0400, directory 0700). No secret value is ever printed:
stdout is a JSON object of booleans. Uses the operator's root token file and CA exactly like roles/vault_post_init.
"""
from __future__ import annotations

import argparse
import json
import secrets
import ssl
import stat
import string
import sys
import urllib.error
import urllib.request
from pathlib import Path

POLICY_NAME = "t5820-observability"
POLICY = 'path "secret/data/local-ai/observability/*" { capabilities = ["read"] }\n'
ROLE = {"token_policies": [POLICY_NAME], "token_ttl": 600, "token_max_ttl": 3600, "secret_id_ttl": 0,
        "secret_id_num_uses": 0, "bind_secret_id": True, "token_type": "default"}
KV_PATH = "secret/data/local-ai/observability/grafana-admin"
FIELDS = {"password": 32, "secret_key": 48, "renderer_token": 40}
ALPHABET = string.ascii_letters + string.digits


def new_secrets() -> dict[str, str]:
    """Three independent random values (never derived from each other)."""
    values = {name: "".join(secrets.choice(ALPHABET) for _ in range(length)) for name, length in FIELDS.items()}
    if len(set(values.values())) != len(values):  # astronomically unlikely, but the role refuses duplicates
        return new_secrets()
    return values


class Vault:
    def __init__(self, address: str, ca: Path, token_file: Path):
        if token_file.stat().st_mode & 0o077:
            raise SystemExit("root token file must not be accessible to group or other")
        self.base = address.rstrip("/") + "/v1/"
        self.context = ssl.create_default_context(cafile=str(ca))
        self.token = token_file.read_text(encoding="utf-8").strip()

    def call(self, method: str, path: str, payload=None, allow_missing=False):
        req = urllib.request.Request(self.base + path, method=method, headers={
            "X-Vault-Token": self.token, "Content-Type": "application/json"},
            data=None if payload is None else json.dumps(payload).encode())
        try:
            with urllib.request.urlopen(req, context=self.context, timeout=15) as response:
                raw = response.read()
                return response.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as error:
            if allow_missing and error.code == 404:
                return 404, {}
            raise SystemExit(f"Vault {method} {path} failed with HTTP {error.code}") from None


def write_private(path: Path, value: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    if path.exists():
        path.chmod(0o600)
    path.write_text(value + "\n", encoding="utf-8")
    path.chmod(stat.S_IRUSR)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-addr", default="https://10.0.8.254:8200")
    parser.add_argument("--ca-cert", type=Path, required=True)
    parser.add_argument("--root-token-file", type=Path, required=True)
    parser.add_argument("--handoff-dir", type=Path, required=True)
    parser.add_argument("--rotate", action="store_true", help="replace the three Grafana secrets even if present")
    args = parser.parse_args()
    vault = Vault(args.vault_addr, args.ca_cert, args.root_token_file)
    result = {"policy_written": False, "role_written": False, "secret_written": False, "approle_files_written": False}
    vault.call("PUT", f"sys/policies/acl/{POLICY_NAME}", {"policy": POLICY})
    result["policy_written"] = True
    vault.call("POST", f"auth/approle/role/{POLICY_NAME}", ROLE)
    result["role_written"] = True
    status, _ = vault.call("GET", KV_PATH, allow_missing=True)
    if status == 404 or args.rotate:
        vault.call("POST", KV_PATH, {"data": new_secrets()})
        result["secret_written"] = True
    approle_dir = args.handoff_dir / "observability-approle"
    if not (approle_dir / "role-id").exists() or not (approle_dir / "secret-id").exists():
        _, role_id = vault.call("GET", f"auth/approle/role/{POLICY_NAME}/role-id")
        _, secret_id = vault.call("POST", f"auth/approle/role/{POLICY_NAME}/secret-id", {})
        write_private(approle_dir / "role-id", role_id["data"]["role_id"])
        write_private(approle_dir / "secret-id", secret_id["data"]["secret_id"])
        result["approle_files_written"] = True
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
