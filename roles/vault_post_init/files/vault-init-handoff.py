#!/usr/bin/env python3
"""Initialize only an uninitialized Vault and save recovery material privately."""
from __future__ import annotations

import argparse
import json
import os
import ssl
import stat
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


class InitError(RuntimeError):
    pass


def atomic_private_write(path: Path, content: bytes) -> bool:
    if path.is_symlink():
        raise InitError("Refusing to replace a recovery-material symlink")
    if path.exists():
        if not stat.S_ISREG(path.stat().st_mode):
            raise InitError("Recovery-material targets must be regular files")
        if path.read_bytes() == content and stat.S_IMODE(path.stat().st_mode) == 0o400:
            return False
        raise InitError("Refusing to overwrite existing recovery material")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o400)
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return True


def read_health(address: str, ca_file: Path) -> dict:
    context = ssl.create_default_context(cafile=str(ca_file))
    request = urllib.request.Request(address.rstrip("/") + "/v1/sys/health")
    try:
        with urllib.request.urlopen(request, context=context, timeout=10) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code in (501, 503):
            try:
                return json.loads(error.read())
            except json.JSONDecodeError:
                pass
        raise InitError(f"Vault health check failed with HTTP {error.code}") from None
    except (urllib.error.URLError, TimeoutError, ssl.SSLError) as error:
        raise InitError(f"Vault health check failed ({type(error).__name__})") from None


def persist_record(record: dict, handoff: Path) -> dict:
    info = handoff.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_mode & 0o077:
        raise InitError("Recovery handoff directory must be a private, regular directory")
    shares = record.get("unseal_keys_b64")
    if not isinstance(shares, list) or len(shares) != 1 or not isinstance(shares[0], str):
        raise InitError("Vault init response did not contain the configured single unseal share")
    root_token = record.get("root_token")
    if not isinstance(root_token, str) or not root_token:
        raise InitError("Vault init response did not contain a root token")
    record_path = handoff / "vault-init-record.json"
    encoded = (json.dumps(record, separators=(",", ":")) + "\n").encode("utf-8")
    changed = atomic_private_write(record_path, encoded)
    changed = atomic_private_write(handoff / "vault-unseal.key", (shares[0] + "\n").encode()) or changed
    changed = atomic_private_write(handoff / "vault-root-token", (root_token + "\n").encode()) or changed
    return {"changed": changed, "recovery_material_saved": True}


def initialize(address: str, ca_file: Path, vault_binary: str, handoff: Path, run=subprocess.run) -> dict:
    health = read_health(address, ca_file)
    if health.get("initialized"):
        raise InitError("Vault is already initialized; refusing to initialize or reset it")
    if health.get("sealed") is not True:
        raise InitError("Vault uninitialized seal state is ambiguous; refusing initialization")
    if (handoff / "vault-init-record.json").exists() or (handoff / "vault-root-token").exists() or (handoff / "vault-unseal.key").exists():
        raise InitError("Existing recovery material is present; refusing to overwrite it")
    environment = os.environ.copy()
    environment.pop("VAULT_TOKEN", None)
    environment.pop("VAULT_NAMESPACE", None)
    environment["VAULT_ADDR"] = address
    environment["VAULT_CACERT"] = str(ca_file)
    environment.pop("VAULT_SKIP_VERIFY", None)
    try:
        result = run(
            [vault_binary, "operator", "init", "-key-shares=1", "-key-threshold=1", "-format=json"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env=environment,
            timeout=60,
        )
        record = json.loads(result.stdout)
    except Exception as error:
        raise InitError(f"Vault initialization did not complete cleanly ({type(error).__name__})") from None
    return persist_record(record, handoff)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault-addr", required=True)
    parser.add_argument("--ca-cert", required=True)
    parser.add_argument("--vault-bin", default="/usr/local/bin/vault")
    parser.add_argument("--handoff-dir", required=True)
    parser.add_argument("--resume-record", action="store_true")
    args = parser.parse_args()
    handoff = Path(args.handoff_dir)
    if args.resume_record:
        record = json.loads((handoff / "vault-init-record.json").read_text(encoding="utf-8"))
        result = persist_record(record, handoff)
    else:
        result = initialize(args.vault_addr, Path(args.ca_cert), args.vault_bin, handoff)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Vault initialization handoff failed safely: {error}", file=__import__("sys").stderr)
        raise SystemExit(1)
