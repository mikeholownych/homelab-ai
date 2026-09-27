# Phase 8 Baseline Verification Report

**Date**: September 27, 2026  
**Repository**: `aihost` (`/home/mike/Projects/aihost`)  
**Base Revision**: Commit `512543a` on branch `phase7-sustained-qualification`  
**Phase 8 Branch**: `phase8-operational-delivery`  
**Phase 8 Worktree**: `/home/mike/Projects/aihost/.worktrees/phase8-operational-delivery`  
**Baseline Test Execution**: 152 / 152 passed (100% in 127.11s)  
**Checksum Manifest**: `phase7/evidence/manifest.sha256` (82/82 files verified)

---

## 1. Objective

Before any Phase 8 implementation or modification begins, independently verify:
1. Integrity of the Phase 7 codebase, tests, and checksum manifest.
2. Undisturbed operation of all protected campaign processes.
3. Serving topology and health of the dual TP=1 inference gateway.
4. Clean isolation of the new Phase 8 development workspace.

---

## 2. Checksum Manifest Verification

The Phase 7 checksum manifest `phase7/evidence/manifest.sha256` was evaluated against all 82 files in the worktree using `sha256sum -c`:

```text
phase7/docs/operational_runbook.md: OK
phase7/docs/phase7_baseline_verification.md: OK
phase7/docs/phase7_engineering_plan.md: OK
phase7/docs/serving_topology_verification.md: OK
phase7/evidence/authority_adversarial_report.md: OK
phase7/evidence/concurrency_qualification_report.md: OK
phase7/evidence/crash_recovery_report.md: OK
phase7/evidence/demo_execution.log: OK
phase7/evidence/engineering_cohort_results.md: OK
phase7/evidence/evidence_integrity_report.md: OK
phase7/evidence/final_report.md: OK
phase7/evidence/protected_service_audit.md: OK
phase7/evidence/resource_containment_report.md: OK
phase7/run_demo.py: OK
[... all 82 files verified OK ...]
```
**Result**: 82 files verified with zero checksum mismatches or omissions.

---

## 3. Protected Campaign Process Audit

The host environment was audited to ensure no disruption to ongoing operations:

| PID | Process Identity | Executable / Command | State | Interference |
|---|---|---|---|---|
| **986** | `Hermes Gateway` | `/home/mike/Projects/hermes-agent/.venv/bin/python -m hermes_...` | RUNNING | **None** |
| **3130937** | `OpenCode Runner` | `opencode --auto...` | RUNNING | **None** |
| **2093382** | `SSH Tunnel` | `/usr/bin/ssh -N -T -o BatchMode=yes -o ExitOnForwardFailure=...` | RUNNING | **None** |

All three processes were confirmed active and completely undisturbed.

---

## 4. Serving Topology & Endpoint Health Verification

The inference serving topology on the Dell Precision 5820 host (`10.0.8.5`) and local workstation port forwarding were verified:

1. **Topology**:
   - Host: `10.0.8.5` (Dell Precision 5820 Tower).
   - GPUs: 2x physical Intel Arc Pro B65 (16 GiB each, 32 GiB total physical, 31.89 GiB addressable).
   - Containers:
     - Worker 1: `vllm-xpu-tp1-worker1` (GPU 0, port 8000, `--tensor-parallel-size 1`).
     - Worker 2: `vllm-xpu-tp1-worker2` (GPU 1, port 8001, `--tensor-parallel-size 1`).
   - Orchestrator Gateway: PID 742882 on port 8010.
   - Forwarding: Local workstation port 18010 forwarded over SSH tunnel PID 2093382.
   - Authentication: Bearer token from `/home/mike/.config/opencode/t5820-client-token`.

2. **Health Check Output**:
   ```bash
   curl -s -H "Authorization: Bearer $(cat /home/mike/.config/opencode/t5820-client-token)" http://127.0.0.1:18010/v1/models
   # Output:
   {"object":"list","data":[{"id":"engineering/b0","object":"model","owned_by":"aihost-orchestrator"}]}
   ```
   **Result**: Inference service is responsive, authenticated, and healthy.

---

## 5. Full Regression Suite Execution (Phases 0–7)

The comprehensive regression suite across all 8 preceding phases was executed in the clean worktree:

```text
======================= 152 passed in 127.11s (0:02:07) ========================
```
- Phase 0: 14 passed
- Phase 1: 12 passed
- Phase 2: 22 passed
- Phase 3: 24 passed
- Phase 4: 18 passed
- Phase 5: 15 passed
- Phase 6: 33 passed
- Phase 7: 14 passed
**Total**: 152 passed, 0 failed, 0 skipped.

---

## 6. Baseline Verification Disposition

The Phase 7 baseline is authentic, intact, and verified.
**Disposition**: `PHASE_7_BASELINE: VERIFIED`.
Phase 8 operational implementation is authorized to proceed.
