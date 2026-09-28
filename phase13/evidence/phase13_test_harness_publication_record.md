# Phase 13 Test Harness Publication Record

- **Date:** 2026-09-28
- **Author:** Autonomous Engineering System
- **Status:** Complete / Verified
- **Branch:** `main`
- **Canonical Remote:** `origin` (`git@github.com:mikeholownych/homelab-ai.git`)
- **Publication Commits:**
  - `59d96890cf2016834b27ee2236652ebec49c86bb`: `fix(test): configure canonical pytest discovery and resolve downstream check contracts`
  - `bf29e29eaf8cb89664a167c2ebc1bf562abd33c3`: `fix(ci): propagate virtualenv python environment to test subprocesses and quality runner`
- **Prior Published State:**
  - `4c364fbeeae0ea138549666014e7a83d7122b07e`: `docs(phase13): record remote CI proof and publication gate reconciliation`
  - `42b3495c4a37eb89593648fc20a20e18920d692c`: `fix(quality): remediate legacy ansible-lint and yamllint defects`
  - `04b530141d63991278ff5f9fe6db8f8040bc1ca0`: `docs(phase13): record canonical remote publication proof and audit addendum`
  - `90890390f70a5c404bc557876a337582b1da79b5`: `feat(phase13): finalize Configuration B production promotion and publish closure record`

---

## 1. Publication Summary

Under the explicit human authorization provided for Phase 13 Remote Publication Recovery (Pytest Collection and Package Import Remediation), bounded changes were implemented, verified locally, and published to canonical `origin/main` to achieve clean pytest collection and test execution in canonical CI.

### Published Scope of Changes

1. **Root Pytest Discovery Configuration ([`pytest.ini`](file:///home/mike/Projects/aihost/pytest.ini)):**
   - Explicitly mapped `pythonpath` across `phase13/src` down through `phase0/src` and repository root `.`.
   - Excluded non-test source fixtures and git worktree directories via `norecursedirs = .* build dist CVS _darcs {arch} *.egg fixtures .worktrees`.
   - Registered canonical test marker `integration`.

2. **Documentation Contract Alignment ([`docs/README.md`](file:///home/mike/Projects/aihost/docs/README.md)):**
   - Added reference link to [`docs/t5820-orchestrator-implementation-2026-09-25.md`](file:///home/mike/Projects/aihost/docs/t5820-orchestrator-implementation-2026-09-25.md) to satisfy repository documentation contract tests.

3. **Operations Contract Path Recognition ([`tests/test_operations_contract.py`](file:///home/mike/Projects/aihost/tests/test_operations_contract.py)):**
   - Extended `test_thermal_guard_state_directory_is_created` to recognize single-path `path:` task attributes (such as `{{ monitoring_config_dir }}`) in addition to `loop:` lists.

4. **Integration Container Base Pinned Packages ([`tests/integration/Dockerfile.baseline`](file:///home/mike/Projects/aihost/tests/integration/Dockerfile.baseline)):**
   - Updated Ubuntu 24.04 package point-release pins (`auditd=1:3.1.2-2.1ubuntu0.1`, `locales=2.39-0ubuntu8.9`, `netplan.io=1.1.2-8ubuntu1~24.04.3`, `sudo=1.9.15p5-3ubuntu5.24.04.3`) to resolve 404 archive fetch errors in container build harnesses.

5. **Path Normalization in Check-Mode Plays ([`tests/integration/baseline_os.yml`](file:///home/mike/Projects/aihost/tests/integration/baseline_os.yml), [`tests/integration/observability_gate_check.yml`](file:///home/mike/Projects/aihost/tests/integration/observability_gate_check.yml)):**
   - Applied `| realpath` filter to safe roots to prevent false-positive path-traversal assertions when checking unnormalized parent traversals (`..`).

6. **Tuning Idempotency Temp Directory Creation ([`scripts/check-tuning-idempotency`](file:///home/mike/Projects/aihost/scripts/check-tuning-idempotency)):**
   - Added `mkdir -p /tmp/opencode` to ensure log redirection succeeds on clean GitHub runner environments.

7. **Virtual Environment Propagation ([`Makefile`](file:///home/mike/Projects/aihost/Makefile), [`.github/workflows/quality.yml`](file:///home/mike/Projects/aihost/.github/workflows/quality.yml), [`tests/test_run_wrapper.py`](file:///home/mike/Projects/aihost/tests/test_run_wrapper.py)):**
   - In `Makefile`: Exported `PATH := $(CURDIR)/$(VENV_DIR)/bin:$(PATH)` so child processes and make targets inherit the virtualenv's Python environment.
   - In `.github/workflows/quality.yml`: Added step `echo "$GITHUB_WORKSPACE/.venv/bin" >> "$GITHUB_PATH"` to ensure all workflow steps execute with the venv in `PATH`.
   - In `tests/test_run_wrapper.py`: Injected executing Python directory (`Path(sys.executable).parent`) into `PATH` immediately following mocked tool directories in `run_wrapper` and `start_wrapper`, ensuring helper scripts (such as `scripts/finalize-evidence.py`) resolve Python dependencies like `jsonschema`.

---

## 2. Remote Publication Git Log Verification

```text
commit bf29e29eaf8cb89664a167c2ebc1bf562abd33c3
Author: Mike Holownych <mike@holownych.com>
Date:   Mon Sep 28 12:02:56 2026 +0000

    fix(ci): propagate virtualenv python environment to test subprocesses and quality runner

commit 59d96890cf2016834b27ee2236652ebec49c86bb
Author: Mike Holownych <mike@holownych.com>
Date:   Mon Sep 28 11:46:12 2026 +0000

    fix(test): configure canonical pytest discovery and resolve downstream check contracts
```

Both commits were pushed directly to `origin/main` and confirmed synchronized with remote authority.
