# Phase 7 Qualification Report: Crash Consistency & Fault Recovery (Workstream A)

## 1. Executive Summary

Workstream A establishes the crash consistency, fail-stop durability, and lease recovery capabilities of the Phase 7 Autonomous Engineering System. By subjecting the hardened execution pipeline to systematic fault injection at every lifecycle boundary, we demonstrate that:
1. The execution control plane never suffers database corruption or lost work-order state.
2. In-flight tasks interrupted at any of the 11 boundaries can be cleanly audited and recovered.
3. Abandoned worker leases are systematically reclaimed upon daemon restart, with monotonic fencing tokens strictly rejecting late-arriving commits from zombie workers.

---

## 2. Lifecycle Boundary Fault Injection Matrix

The pipeline execution flow was systematically instrumented with fail-stop crash hooks (`LifecycleBoundary`) triggering simulated SIGKILL / power termination events. All 11 boundaries were empirically verified in `test_crash_consistency_and_recovery.py` and `phase7/run_demo.py`:

| # | Lifecycle Boundary Hook | Description & Trigger Point | Observed Engine State Post-Crash | Recovery Action & Proof | Status |
|---|---|---|---|---|---|
| 01 | `PRE_ACQUISITION` | Prior to acquiring initial step lease | Work order in `ADMITTED` state | Cleanly re-polled by scheduler on restart | **PASS** |
| 02 | `POST_LEASE` | Immediately after task lease granted | Step in `DISPATCHED` state, token issued | Lease expires; reclaimed by startup loop | **PASS** |
| 03 | `DURING_INVESTIGATION` | During repository path investigation | Investigation artifact in flight | Re-executed on lease expiration | **PASS** |
| 04 | `DURING_PLANNING` | During execution DAG plan compilation | Plan unfinalized in DB | Cleanly re-planned on re-dispatch | **PASS** |
| 05 | `DURING_IMPLEMENTATION` | During author worker patch generation | Patch uncommitted; lease held | Reclaimed on restart; zombie commit rejected | **PASS** |
| 06 | `DURING_REVIEW` | During reviewer specialist critique | Review assignment uncommitted | Re-assigned to reviewer worker | **PASS** |
| 07 | `DURING_REPAIR` | During repair loop revision generation | Repair assignment uncommitted | Re-assigned to repair worker | **PASS** |
| 08 | `DURING_VALIDATION` | In independent sandbox test execution | Sandbox discarded; verdict pending | Cleanly re-validated in fresh sandbox | **PASS** |
| 09 | `DURING_SUPERVISOR_DISPOSITION`| Prior to recording terminal disposition | Verdict in CAS; disposition unwritten | Transaction rolled back; completed on replay| **PASS** |
| 10 | `DURING_EXPORT` | During deliverable bundle assembly | Export directory incomplete | Partial directory wiped; re-exported | **PASS** |
| 11 | `POST_EXPORT_PRE_ACK` | After export, prior to client ACK | Deliverable intact; unacknowledged | Bundle preserved; ACK safely re-emitted | **PASS** |

---

## 3. SQLite WAL Mode & Transactional Durability

The underlying `WorkflowEngine` operates SQLite in Write-Ahead Logging (`WAL`) mode (`PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;`).

### Verification Findings:
1. **Atomic State Transitions**: Every state change (admission, lease acquisition, step completion, and terminal disposition) occurs within an explicit `BEGIN IMMEDIATE TRANSACTION ... COMMIT` block.
2. **Crash Resilience**: Abrupt process terminations leave the WAL file intact. Upon reconnection, SQLite automatically replays the valid WAL frames and rolls back uncommitted partial writes.
3. **Zero State Desynchronization**: In all 11 boundary crash simulations, querying `engine.get_work_order()` returned a structurally intact, deserializable JSON record matching the pre-crash or committed state.

---

## 4. Startup Lease Reclamation & Zombie Worker Fencing

When an execution daemon crashes or restarts while a worker is running:
1. The worker assignment remains in `DISPATCHED` status with an assigned `fencing_token` (e.g., token 1).
2. Upon service startup, `PersistentEngineeringService._recover_stale_leases_on_startup()` queries for dispatched assignments where `lease_expires_at < current_timestamp`.
3. The engine increments the assignment fencing token (token 1 -> token 2) and resets the assignment status to `PENDING`.
4. If the zombie worker process subsequently completes its computation and attempts to commit its patch with token 1, the engine calls `complete_assignment(asgn_id, stale_token, ...)`:
   - Fencing check: `record["fencing_token"] != stale_token` (2 != 1).
   - Engine raises `WorkflowEngineError("Stale fencing token")`.
   - The unverified commit is rejected without modifying artifacts or pipeline state.

### Empirical Test Evidence:
- Verified in `phase7/tests/test_crash_consistency_and_recovery.py::test_startup_lease_reclaim_and_fencing`.
- Verified in `phase7/run_demo.py` section 4 (1 stale lease successfully recovered and fenced).
