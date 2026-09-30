#!/usr/bin/env python3
"""Generate and verify manifest.sha256 for Phase 14 evidence artifacts."""

import hashlib
import os
import sys

EVIDENCE_DIR = "phase14/evidence"
MANIFEST_FILE = os.path.join(EVIDENCE_DIR, "manifest.sha256")


def compute_sha256(filepath: str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def generate_manifest():
    if not os.path.exists(EVIDENCE_DIR):
        print(f"Error: {EVIDENCE_DIR} does not exist.")
        sys.exit(1)

    files = sorted(os.listdir(EVIDENCE_DIR))
    entries = []
    for fname in files:
        if fname == "manifest.sha256" or fname.startswith("."):
            continue
        full_path = os.path.join(EVIDENCE_DIR, fname)
        if os.path.isfile(full_path):
            digest = compute_sha256(full_path)
            entries.append(f"{digest}  {fname}")

    with open(MANIFEST_FILE, "w") as f:
        f.write("\n".join(entries) + "\n")

    print(f"Generated {MANIFEST_FILE} with {len(entries)} verified evidence entries:")
    for entry in entries:
        print(f"  {entry}")


def verify_manifest():
    if not os.path.exists(MANIFEST_FILE):
        print(f"Error: {MANIFEST_FILE} does not exist.")
        sys.exit(1)

    with open(MANIFEST_FILE, "r") as f:
        lines = f.readlines()

    all_ok = True
    verified_count = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        expected_digest, fname = parts
        full_path = os.path.join(EVIDENCE_DIR, fname)
        if not os.path.exists(full_path):
            print(f"MISSING: {fname}")
            all_ok = False
            continue
        actual_digest = compute_sha256(full_path)
        if actual_digest != expected_digest:
            print(f"CORRUPT: {fname} (expected {expected_digest}, got {actual_digest})")
            all_ok = False
        else:
            verified_count += 1

    if all_ok:
        print(f"\nManifest verification successful: {verified_count}/{verified_count} artifacts verified.")
    else:
        print("\nManifest verification FAILED.")
        sys.exit(1)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "verify":
        verify_manifest()
    else:
        generate_manifest()
