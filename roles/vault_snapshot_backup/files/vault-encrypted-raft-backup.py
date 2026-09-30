#!/usr/bin/env python3
"""Export one TLS-verified Vault Raft snapshot, encrypt it, and verify SMB copy."""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import ssl
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


def run(command: list[str]) -> None:
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
    except Exception as error:
        raise RuntimeError(f"Encrypted NAS backup operation failed ({type(error).__name__})") from None


def main() -> None:
    required = (
        "VAULT_BACKUP_ADDR",
        "VAULT_BACKUP_CA",
        "VAULT_BACKUP_ROLE_ID_FILE",
        "VAULT_BACKUP_SECRET_ID_FILE",
        "VAULT_BACKUP_PASSPHRASE_FILE",
        "VAULT_BACKUP_SMB_SHARE",
        "VAULT_BACKUP_SMB_DIRECTORY",
    )
    if any(not os.environ.get(name) for name in required):
        raise RuntimeError("Encrypted snapshot backup configuration is incomplete")
    role_id_path = Path(os.environ["VAULT_BACKUP_ROLE_ID_FILE"])
    secret_id_path = Path(os.environ["VAULT_BACKUP_SECRET_ID_FILE"])
    passphrase_path = Path(os.environ["VAULT_BACKUP_PASSPHRASE_FILE"])
    for path in (role_id_path, secret_id_path, passphrase_path):
        metadata = path.stat()
        if metadata.st_uid != 0 or metadata.st_mode & 0o077:
            raise RuntimeError("Backup recovery material must be root-owned and inaccessible to group or other")
    context = ssl.create_default_context(cafile=os.environ["VAULT_BACKUP_CA"])
    api = os.environ["VAULT_BACKUP_ADDR"].rstrip("/") + "/v1/"
    login = urllib.request.Request(
        api + "auth/approle/login",
        data=json.dumps({"role_id": role_id_path.read_text().strip(), "secret_id": secret_id_path.read_text().strip()}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(login, context=context, timeout=20) as response:
            auth = json.load(response)["auth"]
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
        status = getattr(error, "code", None)
        raise RuntimeError(f"Snapshot AppRole authentication failed ({status or type(error).__name__})") from None
    if "root" in auth.get("policies", []) or not 0 < int(auth.get("lease_duration", 0)) <= 600:
        raise RuntimeError("Vault issued an out-of-contract snapshot token")
    req = urllib.request.Request(
        api + "sys/storage/raft/snapshot",
        headers={"X-Vault-Token": auth["client_token"]},
    )
    try:
        with urllib.request.urlopen(req, context=context, timeout=60) as response:
            snapshot = response.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
        status = getattr(error, "code", None)
        raise RuntimeError(f"Vault snapshot export failed ({status or type(error).__name__})") from None
    if len(snapshot) < 1024:
        raise RuntimeError("Vault returned an unexpectedly small Raft snapshot")

    day = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
    filename = f"vault-raft-{day}.snap.gpg"
    with tempfile.TemporaryDirectory(prefix="vault-snapshot-", dir="/run") as temporary:
        directory = Path(temporary)
        gnupg = directory / "gnupg"
        gnupg.mkdir(mode=0o700)
        plain = directory / "snapshot.snap"
        encrypted = directory / filename
        downloaded = directory / "downloaded.gpg"
        restored = directory / "verified.snap"
        plain.write_bytes(snapshot)
        os.chmod(plain, 0o600)
        run([
            "gpg", "--homedir", str(gnupg), "--batch", "--yes", "--pinentry-mode", "loopback",
            "--passphrase-file", str(passphrase_path), "--symmetric",
            "--cipher-algo", "AES256", "--output", str(encrypted), str(plain),
        ])
        run([
            "gpg", "--homedir", str(gnupg), "--batch", "--yes", "--pinentry-mode", "loopback",
            "--passphrase-file", str(passphrase_path), "--decrypt",
            "--output", str(restored), str(encrypted),
        ])
        digest = hashlib.sha256(snapshot).digest()
        if hashlib.sha256(restored.read_bytes()).digest() != digest:
            raise RuntimeError("Local encrypted snapshot verification failed")
        remote_directory = os.environ["VAULT_BACKUP_SMB_DIRECTORY"]
        share = os.environ["VAULT_BACKUP_SMB_SHARE"]
        run(["smbclient", share, "-N", "-m", "SMB3", "-D", remote_directory, "-c", f"put {encrypted} {filename}"])
        run(["smbclient", share, "-N", "-m", "SMB3", "-D", remote_directory, "-c", f"get {filename} {downloaded}"])
        run([
            "gpg", "--homedir", str(gnupg), "--batch", "--yes", "--pinentry-mode", "loopback",
            "--passphrase-file", str(passphrase_path), "--decrypt",
            "--output", str(restored), str(downloaded),
        ])
        if hashlib.sha256(restored.read_bytes()).digest() != digest:
            raise RuntimeError("NAS snapshot verification failed after download")
        print(f"{{\"result\":\"uploaded_verified\",\"filename\":\"{filename}\",\"encrypted_bytes\":{encrypted.stat().st_size}}}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Vault snapshot backup failed safely: {error}", file=__import__("sys").stderr)
        raise SystemExit(1)
