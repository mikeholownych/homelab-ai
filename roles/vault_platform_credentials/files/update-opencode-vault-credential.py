#!/usr/bin/env python3
"""Refresh the operator's OpenCode environment file from the Vault AppRole."""
from __future__ import annotations

import argparse
import json
import os
import ssl
import stat
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


def post(url: str, context: ssl.SSLContext, payload: dict) -> dict:
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, context=context, timeout=20) as response:
            return json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
        status = getattr(error, "code", None)
        raise RuntimeError(f"Vault authentication failed ({status or type(error).__name__})") from None


def get(url: str, context: ssl.SSLContext, token: str) -> dict:
    request = urllib.request.Request(url, headers={"X-Vault-Token": token})
    try:
        with urllib.request.urlopen(request, context=context, timeout=20) as response:
            return json.load(response)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
        status = getattr(error, "code", None)
        raise RuntimeError(f"Vault secret read failed ({status or type(error).__name__})") from None


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("vault-addr", "ca-cert", "role-id-file", "secret-id-file", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    context = ssl.create_default_context(cafile=args.ca_cert)
    base = args.vault_addr.rstrip("/") + "/v1/"
    role_id = Path(args.role_id_file).read_text().strip()
    secret_id = Path(args.secret_id_file).read_text().strip()
    auth = post(base + "auth/approle/login", context, {"role_id": role_id, "secret_id": secret_id})["auth"]
    if "root" in auth.get("policies", []) or not 0 < int(auth.get("lease_duration", 0)) <= 3600:
        raise RuntimeError("Vault issued an out-of-contract AppRole token")
    value = get(base + "secret/data/local-ai/hosts/ai-5820-01/opencode-client-token", context, auth["client_token"])["data"]["data"]["token"]
    if not isinstance(value, str) or not value:
        raise RuntimeError("Vault returned an empty OpenCode credential")
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    before = target.stat() if target.exists() else None
    content = "export T5820_CLIENT_TOKEN='" + value + "'\n"
    if before and target.read_text() == content:
        print(json.dumps({"changed": False}))
        return
    uid = os.getuid() if before is None else before.st_uid
    gid = os.getgid() if before is None else before.st_gid
    mode = 0o600 if before is None else stat.S_IMODE(before.st_mode)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        os.fchmod(fd, mode)
        os.fchown(fd, uid, gid)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    print(json.dumps({"changed": True}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"OpenCode Vault credential refresh failed safely: {error}", file=__import__("sys").stderr)
        raise SystemExit(1)
