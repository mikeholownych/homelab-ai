#!/usr/bin/env python3
"""Atomically promote a validated venv while preserving rollback target."""
import argparse
import os
from pathlib import Path


def _replace_link(target, link):
    temporary = link.with_name(f".{link.name}.new")
    try:
        temporary.unlink()
    except FileNotFoundError:
        pass
    os.symlink(target, temporary)
    os.replace(temporary, link)


def promote(target, current, previous):
    target, current, previous = map(Path, (target, current, previous))
    if not target.is_dir():
        raise ValueError(f"validated target is not a directory: {target}")
    if current.is_symlink() and current.resolve() == target.resolve():
        return False
    if current.is_symlink():
        _replace_link(os.readlink(current), previous)
    _replace_link(str(target), current)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--current", required=True)
    parser.add_argument("--previous", required=True)
    args = parser.parse_args()
    print("CHANGED" if promote(args.target, args.current, args.previous) else "UNCHANGED")


if __name__ == "__main__":
    main()
