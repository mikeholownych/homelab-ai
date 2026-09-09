#!/usr/bin/env python3
"""Validate SHA256 checksums for kernel workspace artifacts and inputs."""

import argparse
import hashlib
import sys
from pathlib import Path


def compute_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def validate_checksums_file(checksums_path: Path, root_dir: Path) -> tuple[int, int, list[str]]:
    passed = 0
    failed = 0
    errors: list[str] = []

    if not checksums_path.exists():
        return 0, 1, [f"Checksums file not found: {checksums_path}"]

    for line_number, line in enumerate(checksums_path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split(None, 1)
        if len(parts) != 2:
            errors.append(f"Malformed line {line_number} in {checksums_path}: {line}")
            failed += 1
            continue

        expected_hash, rel_path = parts[0].strip(), parts[1].strip().lstrip("*")
        target_path = (root_dir / rel_path).resolve()

        if not target_path.exists():
            errors.append(f"Target file does not exist: {rel_path} (line {line_number})")
            failed += 1
            continue

        actual_hash = compute_sha256(target_path)
        if actual_hash.lower() != expected_hash.lower():
            errors.append(
                f"Checksum mismatch for {rel_path}: expected {expected_hash}, got {actual_hash}"
            )
            failed += 1
        else:
            passed += 1

    return passed, failed, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate kernel workspace SHA256 checksums")
    parser.add_argument(
        "--checksums",
        "-c",
        type=Path,
        default=Path(__file__).resolve().parent / "SHA256SUMS",
        help="Path to SHA256SUMS file",
    )
    parser.add_argument(
        "--root",
        "-r",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root directory",
    )
    args = parser.parse_args()

    passed, failed, errors = validate_checksums_file(args.checksums, args.root)
    for error in errors:
        print(f"FAIL: {error}", file=sys.stderr)

    if failed > 0:
        print(f"Validation failed: {passed} passed, {failed} failed", file=sys.stderr)
        return 1

    print(f"Validation passed: {passed} files verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
