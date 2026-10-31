#!/usr/bin/env python3
"""Content manifest for immutable gateway artifacts; no imports from the release."""
import argparse
import hashlib
import json
from pathlib import Path

MODULES = ("orchestrator_gateway", "orchestrator_runtime", "orchestrator_contract")


def manifest(root, lock):
    files = {}
    for name in MODULES:
        for p in sorted((root / name).rglob("*")):
            if p.is_symlink():
                raise ValueError("gateway artifacts must not contain symbolic links")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
                files[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    files["gateway-requirements.lock"] = hashlib.sha256(lock.read_bytes()).hexdigest()
    if not all(any(k.startswith(name + "/") for k in files) for name in MODULES):
        raise ValueError("incomplete gateway artifact")
    return files


def main():
    a = argparse.ArgumentParser()
    a.add_argument("root", type=Path)
    a.add_argument("lock", type=Path)
    a.add_argument("--verify", type=Path)
    args = a.parse_args()
    actual = manifest(args.root, args.lock)
    if args.verify:
        expected = json.loads(args.verify.read_text())
        if actual != expected:
            raise SystemExit("gateway artifact content verification failed")
    else:
        print(json.dumps(actual, sort_keys=True))


if __name__ == "__main__":
    main()
