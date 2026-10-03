#!/usr/bin/env python3
"""Refresh the operator's OpenCode environment file from the Vault AppRole."""
from __future__ import annotations

import argparse
import json
import os
import shlex
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


def atomic_bytes(target: Path, content: bytes, mode: int, uid: int, gid: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        os.fchown(fd, uid, gid)
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as output:
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


def backup_output(target: Path, backup: Path) -> None:
    if target.is_symlink():
        raise RuntimeError("OpenCode environment file must not be a symlink")
    exists = target.exists()
    metadata = target.stat() if exists else None
    atomic_bytes(backup, target.read_bytes() if exists else b"", 0o600, os.getuid(), os.getgid())
    atomic_bytes(
        Path(str(backup) + ".json"),
        json.dumps({
            "exists": exists,
            "mode": stat.S_IMODE(metadata.st_mode) if metadata else 0o600,
            "uid": metadata.st_uid if metadata else os.getuid(),
            "gid": metadata.st_gid if metadata else os.getgid(),
        }).encode(),
        0o600,
        os.getuid(),
        os.getgid(),
    )


def restore_output(target: Path, backup: Path) -> None:
    if target.is_symlink():
        raise RuntimeError("OpenCode environment file must not be a symlink")
    metadata = json.loads(Path(str(backup) + ".json").read_text())
    if not metadata["exists"]:
        target.unlink(missing_ok=True)
        return
    atomic_bytes(target, backup.read_bytes(), metadata["mode"], metadata["uid"], metadata["gid"])


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("vault-addr", "ca-cert", "role-id-file", "secret-id-file", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--backup-file")
    parser.add_argument("--backup-only", action="store_true")
    parser.add_argument("--restore-from")
    args = parser.parse_args()
    target = Path(args.output)
    if args.restore_from:
        restore_output(target, Path(args.restore_from))
        print(json.dumps({"restored": True}))
        return
    if args.backup_only:
        if not args.backup_file:
            raise RuntimeError("Backup path is required")
        backup_output(target, Path(args.backup_file))
        print(json.dumps({"backup_created": True}))
        return
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
    if target.is_symlink():
        raise RuntimeError("OpenCode environment file must not be a symlink")
    before = target.stat() if target.exists() else None
    content = "export T5820_CLIENT_TOKEN=" + shlex.quote(value) + "\n"
    if before and target.read_text() == content:
        print(json.dumps({"changed": False}))
        return
    uid = os.getuid() if before is None else before.st_uid
    gid = os.getgid() if before is None else before.st_gid
    mode = 0o600 if before is None else stat.S_IMODE(before.st_mode)
    if args.backup_file:
        backup_output(target, Path(args.backup_file))
    atomic_bytes(target, content.encode("utf-8"), mode, uid, gid)
    print(json.dumps({"changed": True}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"OpenCode Vault credential refresh failed safely: {error}", file=__import__("sys").stderr)
        raise SystemExit(1)
