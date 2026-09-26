# Phase 0 Prototype: Reproducible Local Invocation Instructions

**Document ID**: RUN-INSTRUCTIONS-PHASE0-2026-09-26  
**Status**: APPROVED  
**Author**: Antigravity Autonomous Engineering Agent  
**Context**: Reproducible Local Invocation, Section 14  

---

## 1. Prerequisites and Environment

The Phase 0 prototype runs entirely offline on the local workstation without external network connections, GPU hardware allocations, or production credentials.

- **Operating System**: Linux x86_64 (Tested on Ubuntu 24.04/26.04, Kernel 6.8.0)
- **Python**: Python 3.12+
- **Standard Dependencies**: `pytest >= 9.0`, `sqlite3 >= 3.45`, `pydantic >= 2.0` (all standard in system python)
- **Repository Isolation**: Worktree `.worktrees/phase0-offline-prototype` on branch `phase0-offline-prototype`.

---

## 2. Running the Complete Automated Test Suite

To run all 39 contract, recovery, and failure-injection tests:

```bash
cd /home/mike/Projects/aihost/.worktrees/phase0-offline-prototype
PYTHONPATH=phase0/src python3 -m pytest phase0/tests -v
```

### Expected Output Summary:
```
phase0/tests/test_artifacts_and_provenance.py::test_artifact_store_content_addressing_and_provenance PASSED
...
phase0/tests/test_failure_injection_suite.py::test_failure_mode_1_duplicate_assignment_delivery PASSED
...
phase0/tests/test_failure_injection_suite.py::test_failure_mode_12_attempted_mutation_outside_authorized_scope PASSED
...
phase0/tests/test_vertical_slice_e2e.py::test_vertical_slice_end_to_end_disconnected_success PASSED
phase0/tests/test_vertical_slice_e2e.py::test_vertical_slice_bounded_repair_and_revalidation PASSED
phase0/tests/test_workflow_technology_proofs.py::test_proof1_fencing_token_rejects_zombie_worker PASSED
phase0/tests/test_workflow_technology_proofs.py::test_proof2_dual_write_split_brain_mitigation PASSED
phase0/tests/test_workflow_technology_proofs.py::test_proof3_crash_interruption_and_recovery PASSED

============================== 39 passed in ~10s ==============================
```

---

## 3. Running the Standalone Vertical Slice Demonstration

To execute the end-to-end disconnected execution demonstration script:

```bash
cd /home/mike/Projects/aihost/.worktrees/phase0-offline-prototype
python3 phase0/run_demo.py
```

This will:
1. Initialize the SQLite WAL database and SHA-256 Content-Addressed Store.
2. Register heterogeneous simulated B65 worker capability profiles.
3. Ingest a raw defect repair instruction via the Human Interface Adapter.
4. Simulate human interface session disconnection.
5. Execute admission, DAG planning, worker routing, patch synthesis, and independent validation.
6. Commit terminal disposition `ACCEPTED`.
7. Reconnect the interface adapter and dump the full tamper-evident evidence bundle.

---
