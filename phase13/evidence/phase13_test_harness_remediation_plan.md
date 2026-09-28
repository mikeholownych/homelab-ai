# Phase 13 Test Harness Remediation Plan

## 1. Executive Summary

This remediation plan defines the minimal, behavior-preserving corrections necessary to resolve the root causes of pytest collection failures and downstream quality check defects.

- **Author**: Principal Engineering Agent
- **Date**: 2026-09-28
- **Scope**: Repository test configuration, documentation index contract, and static integration checks.
- **Guiding Principle**: Minimal root-cause intervention with zero behavioral degradation.

---

## 2. Remediation Tasks and Target Files

### 2.1 Canonical Pytest Configuration (`pytest.ini`)
- **Defect**: Lack of repository-level pytest configuration caused bare `pytest -q` in CI to fail resolving `autonomous_engineering` across 14 phase trees, and unrestrictedly collect mock tests in `*/fixtures/*`.
- **Correction**: Introduce root `pytest.ini` with:
  1. `pythonpath`: mapping `phase13/src` through `phase0/src` and `.`.
  2. `norecursedirs`: ignoring `.*`, `build`, `dist`, `fixtures`, `.worktrees`.
- **Impact**: Zero change to production source code. Establishes deterministic test discovery across local, CI, and container runs.

### 2.2 Documentation Index Contract (`docs/README.md`)
- **Defect**: Missing entry for `t5820-orchestrator-implementation-2026-09-25.md` in `docs/README.md`, violating `tests/test_documentation_contract.py`.
- **Correction**: Add link to `docs/t5820-orchestrator-implementation-2026-09-25.md` under Operations.
- **Impact**: Restores contract compliance.

### 2.3 Operations Contract Single-Path Task Recognition (`tests/test_operations_contract.py`)
- **Defect**: `test_thermal_guard_state_directory_is_created` only inspected `task.get("loop")`, missing `{{ monitoring_config_dir }}` which was defined via single-path `path:` attribute with dedicated permissions.
- **Correction**: Check both `path` and `loop` in directory verification task loop.
- **Impact**: Fixes false-negative assertion without modifying production Ansible tasks.

### 2.4 Pinned Upstream Docker Package Drift (`tests/integration/Dockerfile.baseline`)
- **Defect**: Upstream Ubuntu 24.04 security repository package updates caused point-release pins for `auditd`, `locales`, `netplan.io`, and `sudo` to 404 during container build.
- **Correction**: Update point releases in `Dockerfile.baseline`:
  - `auditd=1:3.1.2-2.1ubuntu0.1`
  - `locales=2.39-0ubuntu8.9`
  - `netplan.io=1.1.2-8ubuntu1~24.04.3`
  - `sudo=1.9.15p5-3ubuntu5.24.04.3`
- **Impact**: Allows baseline container image build to succeed deterministically.

### 2.5 Realpath Normalization for Localhost-Safe Checks (`tests/integration/baseline_os.yml`, `tests/integration/observability_gate_check.yml`)
- **Defect**: Unnormalized paths containing `..` (`{{ playbook_dir }}/../../.ansible/...`) tripped the `aihost_path_is_safe_descendant` security filter.
- **Correction**: Apply Jinja `realpath` filter to `localhost_safe_root` and `observability_gate_root`.
- **Impact**: Resolves path descendant assertion safely without altering target filesystem directories.

### 2.6 Guard Directory Creation in Tuning Idempotency (`scripts/check-tuning-idempotency`)
- **Defect**: Output redirection to `/tmp/opencode/tuning-idem-*.log` fails if `/tmp/opencode` does not exist on fresh CI runners.
- **Correction**: Add `mkdir -p /tmp/opencode`.
- **Impact**: Ensures runner robustness.
