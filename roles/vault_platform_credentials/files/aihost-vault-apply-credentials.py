#!/usr/bin/env python3
"""Converge T5820 service credentials directly from Vault without Ansible facts."""
from __future__ import annotations

import argparse
import json
import os
import pwd
import grp
import re
import ssl
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


SECRETS = {
    "gateway_client": ("local-ai/services/orchestrator-gateway/client-token", "token"),
    "opencode_client": ("local-ai/hosts/ai-5820-01/opencode-client-token", "token"),
    "vllm_compat": ("local-ai/services/vllm/api-key", "key"),
    # Engine-neutral worker slots: the key belongs to the GPU slot, not to whichever engine serves it.
    "worker1": ("local-ai/services/inference/worker1-api-key", "key"),
    "worker2": ("local-ai/services/inference/worker2-api-key", "key"),
}


def request(url: str, context: ssl.SSLContext, payload=None, token=None) -> dict:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Vault-Token"] = token
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="GET" if payload is None else "POST")
    try:
        with urllib.request.urlopen(req, context=context, timeout=20) as response:
            raw = response.read()
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as error:
        status = getattr(error, "code", None)
        raise RuntimeError(f"Vault request failed ({status or type(error).__name__})") from None
    return json.loads(raw) if raw else {}


def http_status(url: str, key: str | None = None) -> int | str:
    headers = {} if key is None else {"Authorization": f"Bearer {key}"}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=8) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except Exception as error:  # Do not expose headers, URL parameters, or secret values.
        return type(error).__name__


def read_regular_file(path: Path, label: str) -> str:
    info = Path(path).lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise RuntimeError(f"Refusing non-regular {label} path: {path}")
    return Path(path).read_text()


def atomic_write(path: Path, content: str, owner: str | None = None, group: str | None = None) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    before = path.stat() if path.exists() else None
    if before and path.read_text() == content:
        return False
    uid = pwd.getpwnam(owner).pw_uid if owner else (before.st_uid if before else 0)
    gid = grp.getgrnam(group).gr_gid if group else (before.st_gid if before else 0)
    mode = stat.S_IMODE(before.st_mode) if before else 0o400
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        os.fchown(fd, uid, gid)
        with os.fdopen(fd, "w", encoding="utf-8") as output:
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


def replace_one(path: Path, pattern: str, replacement: str, label: str) -> bool:
    content = path.read_text()
    updated, count = re.subn(pattern, replacement, content, count=1, flags=re.M)
    if count != 1:
        raise RuntimeError(f"Expected one {label} field in {path}")
    return atomic_write(path, updated)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _desired_owner(owner: str | None, group: str | None, info):
    uid = pwd.getpwnam(owner).pw_uid if owner else (info.st_uid if info else 0)
    gid = grp.getgrnam(group).gr_gid if group else (info.st_gid if info else 0)
    mode = stat.S_IMODE(info.st_mode) if info else 0o400
    return uid, gid, mode


def _stage_file(path: Path, content: bytes, metadata: tuple[int, int, int]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchown(fd, metadata[0], metadata[1])
        os.fchmod(fd, metadata[2])
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return temporary


def apply_transaction(targets, restart_units, restart, verify_new, verify_old) -> None:
    """Stage a credential set, promote it, and restore the last working set on failure."""
    prepared = []
    snapshots = {}
    promoted = []
    try:
        for path, text, owner, group in targets:
            path = Path(path)
            info = path.lstat() if path.exists() or path.is_symlink() else None
            if info and (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)):
                raise RuntimeError(f"Refusing to replace a non-regular credential target: {path}")
            metadata = _desired_owner(owner, group, info)
            previous = path.read_bytes() if info else None
            snapshots[path] = (previous, metadata)
            content = text.encode("utf-8")
            if previous == content and info and (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == metadata:
                continue
            temporary = _stage_file(path, content, metadata)
            prepared.append((path, temporary))
            if Path(temporary).read_bytes() != content:
                raise RuntimeError(f"Staged credential validation failed: {path.name}")

        if not prepared:
            return

        for path, temporary in prepared:
            os.replace(temporary, path)
            promoted.append(path)
        for unit in restart_units:
            restart(unit)
        verify_new()
        return
    except BaseException as failure:
        if not promoted:
            raise RuntimeError("Credential migration failed before promotion; active files remain unchanged") from None

        rollback_errors = []
        for path in reversed(promoted):
            previous, metadata = snapshots[path]
            try:
                if previous is None:
                    path.unlink(missing_ok=True)
                else:
                    temporary = _stage_file(path, previous, metadata)
                    os.replace(temporary, path)
            except Exception:
                rollback_errors.append("file restoration")

        for unit in restart_units:
            try:
                restart(unit)
            except Exception:
                rollback_errors.append("service reconciliation")
        try:
            verify_old()
        except Exception:
            rollback_errors.append("previous credential boundary validation")
        if rollback_errors:
            raise RuntimeError(
                "Credential migration failed and rollback could not restore the previous working state"
            ) from None
        raise RuntimeError("Credential migration failed; previous state restored") from None
    finally:
        for _path, temporary in prepared:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def worker_key_file(worker: dict) -> Path:
    return Path(worker["key_dir"]) / "worker-api-key"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    config = json.loads(read_regular_file(Path(parser.parse_args().config), "runtime config"))
    context = ssl.create_default_context(cafile=config["ca_cert"])
    api = config["vault_addr"].rstrip("/") + "/v1/"
    role_id = Path(config["role_id_file"]).read_text().strip()
    secret_id = Path(config["secret_id_file"]).read_text().strip()
    auth = request(api + "auth/approle/login", context, {"role_id": role_id, "secret_id": secret_id})["auth"]
    ttl = int(auth.get("lease_duration", 0))
    require(0 < ttl <= 3600 and "root" not in auth.get("policies", []), "Vault issued an out-of-contract workload token")
    token = auth["client_token"]
    values = {}
    for name, (path, key) in SECRETS.items():
        result = request(api + "secret/data/" + path, context, token=token)
        values[name] = result["data"]["data"][key]
        require(isinstance(values[name], str) and values[name], f"Vault returned an empty {name} credential")

    paths = config["paths"]
    gateway_env = Path(config["gateway_env"])
    workers = {w["name"]: w for w in config["workers"]}
    require(set(workers) == {"worker1", "worker2"}, "Worker roster must define exactly worker1 and worker2")
    gateway_unit = config.get("gateway_unit", "aihost-orchestrator-gateway.service")
    gateway_url = config.get("gateway_url", "http://127.0.0.1:8010")
    previous = {
        "gateway_client": read_regular_file(Path(paths["gateway_client"]), "gateway credential").strip(),
        "opencode_client": read_regular_file(Path(paths["opencode_client"]), "OpenCode credential").strip(),
        "vllm_compat": read_regular_file(Path(paths["vllm_compat"]), "vLLM compatibility credential").strip(),
    }
    for name, worker in workers.items():
        previous[name] = read_regular_file(worker_key_file(worker), f"{name} token file").strip()

    targets = []
    files_changed = []

    def add_target(path: Path, content: str, name: str, owner=None, group=None):
        path = Path(path)
        if not path.exists() or path.read_text() != content:
            targets.append((path, content, owner, group))
            files_changed.append(name)

    for name in ("gateway_client", "opencode_client", "vllm_compat"):
        add_target(Path(paths[name]), values[name] + "\n", name)
    changed_workers = []
    for name, worker in workers.items():
        owner = worker.get("owner")
        before_text = worker_key_file(worker).read_text() if worker_key_file(worker).exists() else None
        if before_text != values[name] + "\n":
            targets.append((worker_key_file(worker), values[name] + "\n", owner, owner))
            files_changed.append(f"{name}_token_file")
            changed_workers.append(name)

    def worker_urls(name: str) -> tuple[str, str]:
        base = f"http://127.0.0.1:{workers[name]['port']}"
        return base + "/v1/models", base + "/health"

    def validate_boundary(credentials: dict, label: str) -> dict:
        results = {
            f"gateway_{label}": http_status(gateway_url + "/v1/models", credentials["gateway_client"]),
            f"opencode_{label}": http_status(gateway_url + "/v1/models", credentials["opencode_client"]),
        }
        for name in workers:
            results[f"{name}_{label}"] = http_status(worker_urls(name)[0], credentials[name])
            require(http_status(worker_urls(name)[1]) == 200, f"{name} health check failed")
        require(all(status == 200 for status in results.values()), "A credential failed its live acceptance check (" + label + ")")
        require(http_status(gateway_url + "/health") == 200, "Gateway health check failed")
        units = [gateway_unit] + [w["unit"] for w in workers.values()]
        states = {unit: subprocess.check_output(["systemctl", "is-active", unit], text=True).strip() for unit in units}
        require(all(state == "active" for state in states.values()), "A platform service is not active")
        require("ORCHESTRATOR_SCHEDULING_MODE=CONFIGURATION_B_PLUS" in read_regular_file(gateway_env, "gateway environment"), "Configuration B+ is not active")
        return results

    restarted = []
    if files_changed:
        before = validate_boundary(previous, "old")
        restart_units = [workers[name]["unit"] for name in changed_workers]
        # The gateway reads worker token files and client tokens at start; any credential change reloads it.
        restart_units.append(gateway_unit)

        def restart(unit):
            subprocess.run(["systemctl", "restart", unit], check=True, timeout=1800 if unit != gateway_unit else 120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if unit not in restarted:
                restarted.append(unit)

        evidence = {}
        apply_transaction(
            targets,
            restart_units,
            restart,
            lambda: evidence.update(validate_boundary(values, "new")),
            lambda: validate_boundary(previous, "old"),
        )
        evidence = {"before": before, "after": evidence}
    else:
        evidence = {"live_acceptance": validate_boundary(values, "current")}

    units = [gateway_unit] + [w["unit"] for w in workers.values()]
    states = {unit: subprocess.check_output(["systemctl", "is-active", unit], text=True).strip() for unit in units}
    require(all(state == "active" for state in states.values()), "A platform service is not active")
    print(json.dumps({"changed": bool(files_changed), "changed_files": files_changed, "restarted": restarted, "service_states": states, **evidence}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Vault credential convergence failed safely: {error}", file=__import__("sys").stderr)
        raise SystemExit(1)
