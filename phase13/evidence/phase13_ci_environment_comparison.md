# Phase 13 CI vs Local Environment Comparison Report

## 1. Executive Summary

This report documents the precise environment and execution differences between the local developer workspace where 492/492 regression tests pass, and the GitHub Actions CI environment where `make quality` fails.

- **Investigation Date**: 2026-09-28
- **Core Discrepancy**: Local manual runs utilized an ad-hoc shell environment variable (`PYTHONPATH="phase13/src:..."`) targeting only `phase*/tests`, whereas CI executed `make quality` -> `make test` -> `.venv/bin/pytest -q` without `PYTHONPATH`, exposing missing repository configuration.

---

## 2. Environment Comparison Matrix

```
+-----------------------------------+--------------------------------+--------------------------------+
| Dimension                         | Local Development Workspace    | Canonical GitHub Actions CI    |
+-----------------------------------+--------------------------------+--------------------------------+
| Operating System                  | Linux (Ubuntu 24.04 LTS)       | Linux (Ubuntu 24.04.5 LTS)     |
| Runner Image                      | Dell Precision T5820 Host      | GitHub Hosted 20260920.314.1   |
| Python Version                    | 3.12.3                         | 3.12.3                         |
| Virtualenv Location               | `/home/mike/Projects/aihost/.venv` | `/home/runner/work/.../.venv`  |
| Pytest Version                    | 9.1.1                          | 9.1.1                          |
| Pytest Command Invoked in CI      | `make test` (`pytest -q`)      | `make quality` (`pytest -q`)   |
| Historical Command for 492 tests  | `PYTHONPATH="phase13/src:..."` | None (empty PYTHONPATH)        |
| Pytest Config File (`pytest.ini`) | Absent prior to remediation    | Absent prior to remediation    |
| Effective `sys.path` in CI        | `['/workspace', ...]`          | `['/workspace', ...]`          |
| Fixture Exclusion                 | Implicit (targeted directories)| Unrestricted root recursion    |
+-----------------------------------+--------------------------------+--------------------------------+
```

---

## 3. Discrepancy Attribution

1. **Undeclared Prerequisite**:
   The documented test command in operational runbooks (`phase9/docs/operational_runbook.md`, etc.) relied on explicitly passing:
   `PYTHONPATH="phase13/src:phase12/src:...:phase0/src:." pytest phase0/tests ...`
   This requirement was never encoded into a repository configuration file (`pytest.ini` or `pyproject.toml`) or the `Makefile`.

2. **Target Mismatch**:
   - Local verification runs targeted `phase0/tests phase1/tests ... phase13/tests` directly, implicitly bypassing `phase*/fixtures/`.
   - CI runs `make test`, which invokes `$(PYTEST) -q` from repository root without positional arguments.
   - Without a `pytest.ini` declaring `pythonpath` and `norecursedirs`, pytest scans the root directory recursively, attempting to import fixture mock code and failing to import `autonomous_engineering`.

3. **Remediation Requirement**:
   Encode the exact `pythonpath` and `norecursedirs` settings into canonical `pytest.ini` so that any bare invocation of `pytest` or `make test` in any environment (local, CI, container) executes identically without manual environment wrappers.
