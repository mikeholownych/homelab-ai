# Phase 13 CI Pytest Failure Forensics Report

## 1. Executive Summary

This report documents the forensic investigation into the GitHub Actions CI failures observed in runs `36412964630` (commit `42b3495`) and `36413311901` (commit `4c364fb`).

- **Target Workflow**: `.github/workflows/quality.yml` (`quality`)
- **Failing Step**: `Run repository quality gates` (`make quality` -> `make test`)
- **Failing Command**: `.venv/bin/pytest -q`
- **Failing Exception**: `ModuleNotFoundError: No module named 'autonomous_engineering'`
- **Failure Scope**: 109 collection errors across `phase0/` through `phase13/`
- **Root Cause**: Pytest invocation lacked `pythonpath` configuration to resolve the multi-root source trees of `autonomous_engineering`, while recursively attempting to collect mock tests within pipeline test fixture directories (`*/fixtures/*`).

---

## 2. Authoritative Remote CI Telemetry

From GitHub Actions run logs (`gh run view 36412964630 --log-failed`):

```
repository quality    Run repository quality gates    2026-09-28T11:01:08.8622255Z .venv/bin/pytest -q
repository quality    Run repository quality gates    2026-09-28T11:01:11.8970545Z 
repository quality    Run repository quality gates    2026-09-28T11:01:11.8972816Z ==================================== ERRORS ====================================
repository quality    Run repository quality gates    2026-09-28T11:01:11.8973784Z ____ ERROR collecting phase0/fixtures/sample_repo/tests/test_math_utils.py _____
repository quality    Run repository quality gates    2026-09-28T11:01:11.8974915Z ImportError while importing test module '/home/runner/work/homelab-ai/homelab-ai/phase0/fixtures/sample_repo/tests/test_math_utils.py'.
repository quality    Run repository quality gates    2026-09-28T11:01:11.8976102Z Hint: make sure your test modules/packages have valid Python names.
repository quality    Run repository quality gates    2026-09-28T11:01:11.8976527Z Traceback:
repository quality    Run repository quality gates    2026-09-28T11:01:11.8977209Z /usr/lib/python3.12/importlib/__init__.py:90: in import_module
repository quality    Run repository quality gates    2026-09-28T11:01:11.8977926Z     return _bootstrap._gcd_import(name[level:], package, level)
repository quality    Run repository quality gates    2026-09-28T11:01:11.8978589Z            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
repository quality    Run repository quality gates    2026-09-28T11:01:11.8979313Z phase0/fixtures/sample_repo/tests/test_math_utils.py:1: in <module>
repository quality    Run repository quality gates    2026-09-28T11:01:11.8980053Z     from src.math_utils import add, divide, multiply, subtract
repository quality    Run repository quality gates    2026-09-28T11:01:11.8980838Z E   ModuleNotFoundError: No module named 'src.math_utils'
...
repository quality    Run repository quality gates    2026-09-28T11:01:11.9546933Z ERROR phase9/tests/test_physical_resource_management.py
repository quality    Run repository quality gates    2026-09-28T11:01:11.9547058Z ERROR phase9/tests/test_reasoning_budget_manager.py
repository quality    Run repository quality gates    2026-09-28T11:01:11.9547230Z ERROR phase9/tests/test_workload_classifier.py
repository quality    Run repository quality gates    2026-09-28T11:01:11.9547424Z !!!!!!!!!!!!!!!!!! Interrupted: 109 errors during collection !!!!!!!!!!!!!!!!!!!
repository quality    Run repository quality gates    2026-09-28T11:01:11.9547510Z 109 errors in 2.77s
repository quality    Run repository quality gates    2026-09-28T11:01:12.0001194Z make: *** [Makefile:41: test] Error 2
```

---

## 3. Dissection of the 109 Collection Errors

The 109 collection errors decompose into two distinct mechanisms:

1. **Fixture Repo Internal Tests (15 files)**:
   - Directories such as `phase0/fixtures/sample_repo/tests/`, `phase1/fixtures/disposable_repo/tests/`, and `phase4/fixtures/heldout/.../tests/` contain mock code used as test fixtures for the autonomous repair and evaluation engine.
   - When pytest runs with default recursion, it attempts to collect these test files as if they were top-level suite modules, failing on imports like `from src.math_utils import ...` or `from src.fencing_token import ...`.
   - **Resolution**: Exclude `fixtures` via `norecursedirs` in `pytest.ini`.

2. **Autonomous Engineering Phase Suite Tests (94 files)**:
   - The test suites in `phase0/tests/` through `phase13/tests/` test the Autonomous Engineering System and import packages via `autonomous_engineering.<submodule>`.
   - The implementations reside in `phase*/src/autonomous_engineering/`.
   - Because no root package was installed and no `pythonpath` was declared in pytest configuration, `sys.path` in CI only contained the repository root (added by `tests/conftest.py`).
   - **Resolution**: Declare `pythonpath` spanning `phase13/src` down through `phase0/src` and `.` in `pytest.ini`.

Both mechanisms share the single root cause of unconfigured repository-level test discovery and pythonpath configuration.
