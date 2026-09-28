# Phase 13 Test Harness Remote CI Proof

- **Date:** 2026-09-28
- **Author:** Autonomous Engineering System
- **Status:** Complete / Verified
- **Branch:** `main`
- **Canonical Remote:** `origin` (`git@github.com:mikeholownych/homelab-ai.git`)
- **Workflow:** `quality` (`.github/workflows/quality.yml`)
- **Job:** `repository quality`
- **Runner:** `ubuntu-24.04` (GitHub-hosted)
- **Target Commits:**
  - `59d96890cf2016834b27ee2236652ebec49c86bb`: Test discovery and downstream check contracts
  - `bf29e29eaf8cb89664a167c2ebc1bf562abd33c3`: Virtualenv Python environment propagation
- **Canonical CI Run ID:** `36419342736`
- **Canonical CI Run URL:** [Run 36419342736](https://github.com/mikeholownych/homelab-ai/actions/runs/36419342736)

---

## 1. Remote CI Forensics and Remediation Progression

### Prior Failure States in Canonical CI

1. **Run `36412964630` (Commit `42b3495c`):**
   - Step: `Run repository quality gates` -> `make quality` -> `make test` -> `pytest -q`
   - Failure: `ModuleNotFoundError: No module named 'autonomous_engineering'`
   - Root Cause: Missing root [`pytest.ini`](file:///home/mike/Projects/aihost/pytest.ini) causing pytest to run with default collection, skipping multi-phase `pythonpath` mappings and descending into nested fixtures.

2. **Run `36417819081` (Commit `59d96890`):**
   - Step: `Run repository quality gates` -> `make test`
   - Progress: 933 passed, 3 skipped, 126 subtests passed.
   - Failure: 38 tests failed in [`tests/test_run_wrapper.py`](file:///home/mike/Projects/aihost/tests/test_run_wrapper.py) with `ModuleNotFoundError: No module named 'jsonschema'` when [`scripts/run-ansible-snapshot`](file:///home/mike/Projects/aihost/scripts/run-ansible-snapshot) invoked [`scripts/finalize-evidence.py`](file:///home/mike/Projects/aihost/scripts/finalize-evidence.py).
   - Root Cause: In GitHub Actions, dependencies from `requirements.txt` are installed exclusively in `.venv`. The workflow did not export `.venv/bin` to `PATH`, and `test_run_wrapper.py` passed `PATH` with fake tools prepended to the runner's default `PATH`, causing `python3 -I` in `run-ansible-snapshot` to execute system Python (`/usr/bin/python3` or `/opt/hostedtoolcache/...`) where `jsonschema` was not installed.

### Applied Remediation (Commit `bf29e29e`)

1. **Workflow `PATH` Configuration ([`.github/workflows/quality.yml`](file:///home/mike/Projects/aihost/.github/workflows/quality.yml)):**
   - Added step `Add virtual environment to PATH` exporting `$GITHUB_WORKSPACE/.venv/bin` to `$GITHUB_PATH`.
2. **Makefile `PATH` Export ([`Makefile`](file:///home/mike/Projects/aihost/Makefile)):**
   - Added `export PATH := $(CURDIR)/$(VENV_DIR)/bin:$(PATH)` ensuring make targets and spawned subprocesses inherit the virtualenv.
3. **Test Harness Subprocess Isolation ([`tests/test_run_wrapper.py`](file:///home/mike/Projects/aihost/tests/test_run_wrapper.py)):**
   - In `run_wrapper` and `start_wrapper`, injected `Path(sys.executable).parent` directly into `merged_env["PATH"]` immediately following mock tool directories, ensuring child processes executed by `run-ansible-snapshot` resolve the test runner's Python environment.

---

## 2. Remote Workflow Execution Record (Run 36419342736)

- **Step 1:** Set up job — Success
- **Step 2:** Check out repository — Success
- **Step 3:** Set up Python 3.12 — Success
- **Step 4:** Create virtual environment (`python -m venv .venv`) — Success
- **Step 5:** Add virtual environment to PATH (`echo "$GITHUB_WORKSPACE/.venv/bin" >> "$GITHUB_PATH"`) — Success
- **Step 6:** Install Python dependencies (`.venv/bin/python -m pip install --require-hashes -r requirements.txt`) — Success
- **Step 7:** Install Ansible collections (`.venv/bin/ansible-galaxy collection install -r requirements.yml`) — Success
- **Step 8:** Run repository quality gates (`make quality`):
  - `lint`: `yamllint .` and `ansible-lint .` passed (0 errors, 0 warnings across 1006 files).
  - `test`: `pytest -q` passed across all phase packages, contract tests, and run wrapper tests.
  - `syntax`: Syntax checks passed on 11/11 playbooks.
  - `check`: Check mode plays passed against baseline and observability fixtures.
  - `idempotency`: Docker harness idempotency verification passed on Ubuntu noble and resolute.
  - `tuning-idempotency`: OS tuning convergence and byte-stable second pass passed.
- **Step 9:** Show active Ansible config overrides (`ansible-config dump --only-changed`) — Success
