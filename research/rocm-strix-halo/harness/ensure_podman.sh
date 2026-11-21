#!/usr/bin/env bash
# Verify container runtime and ROCm-related device nodes on the lab host.
# Prints a JSON summary to stdout; exits non-zero when prerequisites are missing.
set -euo pipefail

python3 <<'PY'
import glob
import json
import os
import shutil
import subprocess
import sys

errors: list[str] = []
if shutil.which("podman"):
    runtime = "podman"
elif shutil.which("docker"):
    runtime = "docker"
else:
    runtime = None
    errors.append("no container runtime (podman or docker)")

kfd = os.path.exists("/dev/kfd")
if not kfd:
    errors.append("/dev/kfd missing")

accel0 = os.path.exists("/dev/accel/accel0")
render_nodes = sorted(glob.glob("/dev/dri/renderD*"))
if not render_nodes:
    errors.append("no /dev/dri/renderD* nodes")

user = subprocess.check_output(["id", "-un"], text=True).strip()
groups = subprocess.check_output(["id", "-Gn"], text=True).split()

ok = runtime is not None and kfd and bool(render_nodes)

summary = {
    "ok": ok,
    "runtime": runtime,
    "kfd": kfd,
    "render_nodes": render_nodes,
    "accel0": accel0,
    "user": user,
    "groups": groups,
    "errors": errors,
}

print(json.dumps(summary, indent=2))
sys.exit(0 if ok else 1)
PY