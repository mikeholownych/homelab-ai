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
    "worker1": ("local-ai/services/vllm/worker1-api-key", "key"),
    "worker2": ("local-ai/services/vllm/worker2-api-key", "key"),
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


def read_worker_key(config_path: Path) -> str:
    match = re.search(r"^api-key:\s*[\"']?(.*?)[\"']?\s*$", config_path.read_text(), re.M)
    if not match:
        raise RuntimeError(f"Worker config has no API key field: {config_path}")
    return match.group(1)


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    config = json.loads(Path(parser.parse_args().config).read_text())
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
    worker_cfg = [Path(paths[f"worker{i}_dir"]) / "vllm-config.yaml" for i in (1, 2)]
    worker_env = [Path(paths[f"worker{i}_dir"]) / "vllm.env" for i in (1, 2)]
    previous = {
        "gateway_client": Path(paths["gateway_client"]).read_text().strip(),
        "opencode_client": Path(paths["opencode_client"]).read_text().strip(),
        "worker1": read_worker_key(worker_cfg[0]),
        "worker2": read_worker_key(worker_cfg[1]),
        "vllm_compat": Path(paths["vllm_compat"]).read_text().strip(),
    }

    files_changed = []
    for name, key in (("gateway_client", values["gateway_client"]), ("opencode_client", values["opencode_client"]), ("vllm_compat", values["vllm_compat"])):
        if atomic_write(Path(paths[name]), key + "\n"):
            files_changed.append(name)
    worker_auth_changed = False
    for index in (1, 2):
        directory = Path(paths[f"worker{index}_dir"])
        key = values[f"worker{index}"]
        token_path = directory / "worker-api-key"
        if atomic_write(token_path, key + "\n", "aihost-runtime", "aihost-runtime"):
            files_changed.append(f"worker{index}_token_file")
            worker_auth_changed = True
        if replace_one(worker_cfg[index - 1], r"^api-key:.*$", "api-key: " + json.dumps(key), f"worker{index} YAML API key"):
            files_changed.append(f"worker{index}_config")
            worker_auth_changed = True
        if replace_one(worker_env[index - 1], r"^VLLM_API_KEY=.*$", "VLLM_API_KEY=" + key, f"worker{index} environment API key"):
            files_changed.append(f"worker{index}_environment")
            worker_auth_changed = True

    env_lines = gateway_env.read_text().splitlines()
    specs_found = False
    for index, line in enumerate(env_lines):
        if line.startswith("ORCHESTRATOR_WORKER_SPECS="):
            specs = json.loads(line.split("=", 1)[1])
            require(len(specs) == 2, "Gateway worker roster does not contain exactly two workers")
            seen = set()
            for spec in specs:
                worker_id = spec.get("worker_id", "")
                worker_index = 1 if worker_id.endswith("worker1") else 2 if worker_id.endswith("worker2") else 0
                require(worker_index > 0 and worker_index not in seen, "Gateway worker roster has an unknown or duplicate worker")
                seen.add(worker_index)
                spec["token_file"] = f"/etc/local-ai/vllm/worker{worker_index}/worker-api-key"
            require(seen == {1, 2}, "Gateway worker roster is missing a configured worker")
            env_lines[index] = "ORCHESTRATOR_WORKER_SPECS=" + json.dumps(specs, separators=(",", ":"))
            specs_found = True
    require(specs_found, "Gateway worker specs are not configured")
    if atomic_write(gateway_env, "\n".join(env_lines) + "\n"):
        files_changed.append("gateway_worker_token_references")

    restarted = []
    if files_changed:
        before = {
            "gateway_client": http_status("http://127.0.0.1:8010/v1/models", previous["gateway_client"]),
            "opencode_client": http_status("http://127.0.0.1:8010/v1/models", previous["opencode_client"]),
            "worker1": http_status("http://127.0.0.1:8000/v1/models", previous["worker1"]),
            "worker2": http_status("http://127.0.0.1:8001/v1/models", previous["worker2"]),
            "shared1": http_status("http://127.0.0.1:8000/v1/models", previous["vllm_compat"]),
            "shared2": http_status("http://127.0.0.1:8001/v1/models", previous["vllm_compat"]),
        }
        require(all(status == 200 for status in before.values()), "A pre-rotation credential acceptance check failed")
        for index in (1, 2):
            if any(item.startswith(f"worker{index}_") for item in files_changed):
                unit = f"aihost-vllm-worker{index}.service"
                subprocess.run(["systemctl", "restart", unit], check=True, timeout=1200, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                restarted.append(unit)
                port = 7999 + index
                for _ in range(240):
                    if http_status(f"http://127.0.0.1:{port}/health") == 200 and http_status(f"http://127.0.0.1:{port}/v1/models", values[f"worker{index}"]) == 200:
                        break
                    time.sleep(5)
                else:
                    raise RuntimeError(f"Worker {index} failed health or replacement-key validation after restart")
        gateway_changed = any(name in files_changed for name in ("gateway_client", "opencode_client", "vllm_compat", "gateway_worker_token_references")) or worker_auth_changed
        if gateway_changed:
            unit = "aihost-orchestrator-gateway.service"
            subprocess.run(["systemctl", "restart", unit], check=True, timeout=60, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            restarted.append(unit)
            for _ in range(60):
                if http_status("http://127.0.0.1:8010/health") == 200:
                    break
                time.sleep(2)
            else:
                raise RuntimeError("Gateway failed health validation after restart")
        after = {
            "gateway_new": http_status("http://127.0.0.1:8010/v1/models", values["gateway_client"]),
            "opencode_new": http_status("http://127.0.0.1:8010/v1/models", values["opencode_client"]),
            "gateway_old": http_status("http://127.0.0.1:8010/v1/models", previous["gateway_client"]),
            "opencode_old": http_status("http://127.0.0.1:8010/v1/models", previous["opencode_client"]),
            "worker1_new": http_status("http://127.0.0.1:8000/v1/models", values["worker1"]),
            "worker2_new": http_status("http://127.0.0.1:8001/v1/models", values["worker2"]),
            "worker1_old": http_status("http://127.0.0.1:8000/v1/models", previous["worker1"]),
            "worker2_old": http_status("http://127.0.0.1:8001/v1/models", previous["worker2"]),
            "shared_old1": http_status("http://127.0.0.1:8000/v1/models", previous["vllm_compat"]),
            "shared_old2": http_status("http://127.0.0.1:8001/v1/models", previous["vllm_compat"]),
        }
        require(all(after[name] == 200 for name in ("gateway_new", "opencode_new", "worker1_new", "worker2_new")), "A replacement credential was rejected")
        require(all(after[name] in (401, 403) for name in ("gateway_old", "opencode_old", "worker1_old", "worker2_old", "shared_old1", "shared_old2")), "A specific previous credential remains accepted")
        evidence = {"before": before, "after": after}
    else:
        checks = {
            "gateway": http_status("http://127.0.0.1:8010/v1/models", values["gateway_client"]),
            "opencode": http_status("http://127.0.0.1:8010/v1/models", values["opencode_client"]),
            "worker1": http_status("http://127.0.0.1:8000/v1/models", values["worker1"]),
            "worker2": http_status("http://127.0.0.1:8001/v1/models", values["worker2"]),
        }
        require(all(status == 200 for status in checks.values()), "A Vault replacement credential failed its live boundary check")
        require(all(http_status(f"http://127.0.0.1:{port}/health") == 200 for port in (8000, 8001)), "A vLLM worker health check failed")
        require(http_status("http://127.0.0.1:8010/health") == 200, "Gateway health check failed")
        evidence = {"live_acceptance": checks}

    states = {unit: subprocess.check_output(["systemctl", "is-active", unit], text=True).strip() for unit in ("aihost-orchestrator-gateway.service", "aihost-vllm-worker1.service", "aihost-vllm-worker2.service")}
    require(all(state == "active" for state in states.values()), "A platform service is not active")
    bplus = "ORCHESTRATOR_SCHEDULING_MODE=CONFIGURATION_B_PLUS" in gateway_env.read_text()
    require(bplus, "Configuration B+ is not active in the gateway environment")
    print(json.dumps({"changed": bool(files_changed), "changed_files": files_changed, "restarted": restarted, "service_states": states, "configuration_b_plus": bplus, **evidence}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Vault credential convergence failed safely: {error}", file=__import__("sys").stderr)
        raise SystemExit(1)
