# Autonomous Engineering System: Phase 7 Operational Runbook
## Sustained Unattended Execution, Incident Handling, and Administration

### 1. Architectural Overview & Operating Principles

The Phase 7 Autonomous Engineering System provides sustained, unattended engineering execution on the `aihost` codebase while strictly enforcing:
- **Authority Boundaries**: Human work orders define immutable intent and authorized mutation paths.
- **Untrusted Workers**: Author, Reviewer, and Repairer models are untrusted executors operating in sandboxed or isolated workspaces.
- **Fail-Closed Guarantees**: Point-of-use scope verification, monotonic fencing tokens, and independent validation ensure malformed or adversarial outputs are unconditionally rejected.
- **Crash Consistency**: The control plane utilizes SQLite WAL mode and atomic lease transactions to ensure non-destructive restarts across all 11 lifecycle boundaries.

---

### 2. Service Management Procedures

#### 2.1 Starting the Engineering Service Daemon
To start the persistent engineering service daemon:
```bash
PYTHONPATH=phase7/src:phase6/src:phase5/src:phase4/src:phase3/src:phase2/src:phase1/src:phase0/src \
python3 -m autonomous_engineering.service.engineering_service \
  --repo-dir /home/mike/Projects/aihost \
  --db-path /home/mike/Projects/aihost/.runtime/engineering_state.sqlite \
  --max-concurrency 4 \
  --max-queue-depth 16 \
  --poll-interval 0.5
```
**Startup Actions**:
1. Checks SQLite database integrity in WAL mode.
2. Performs automated startup lease reclamation (`_recover_stale_leases_on_startup`), identifying abandoned or expired leases from prior crashes and resetting task states.
3. Initializes the `ConcurrencyManager` and `ServiceObservability` subsystems.
4. Begins the background worker loop.

#### 2.2 Pausing and Resuming Admission
When maintenance or cluster investigations are required without terminating in-flight work:
```bash
# Pause new admissions (backpressure engages, in-flight work completes)
python3 -m autonomous_engineering.cli.admin pause-admission

# Resume admissions
python3 -m autonomous_engineering.cli.admin resume-admission
```
When paused, callers submitting new work orders receive an immediate `AdmissionStoppedError`.

#### 2.3 Graceful Shutdown and Drain
To stop the service cleanly:
1. Signal `SIGTERM` or `SIGINT` to the service daemon process.
2. The daemon sets `_running = False`, ceases claiming new tasks from the queue, and allows active task step executions to reach their next lifecycle boundary.
3. In-flight leases expire cleanly if terminated prematurely, and are re-acquired upon subsequent restart.

---

### 3. Monitoring, Telemetry & Health Checks

#### 3.1 Health Invariant Verification
The `ServiceObservability` engine monitors continuous health status:
```python
snapshot = service.observability.get_snapshot(current_queue_depth=depth, active_worker_count=count)
# Status: HEALTHY, DEGRADED, or STALLED
```
- **HEALTHY**: Stall detector indicates all active leases are within timeout bounds; queue depth is within capacity.
- **DEGRADED**: Queue depth exceeds 75% capacity or worker count is at maximum concurrency.
- **STALLED**: One or more active leases have exceeded `stall_timeout_sec` (default 300s) without advancing lifecycle state.

#### 3.2 Audit Logging
All state transitions are logged with timestamps, work order IDs, versions, and SHA-256 artifact hashes:
- `logs/audit_events.jsonl`: Structured append-only log of all admission, lease acquisition, scope checks, and terminal dispositions.
- `logs/service.log`: Standard operational daemon logs.

---

### 4. Incident Response & Failure Recovery

#### 4.1 Unplanned Service Daemon Termination (Crash / Power Loss)
If the host or daemon process crashes abruptly:
1. **Target Repository Safety**: Target repository is unaffected because workers operate in isolated temporary workspaces created by `ConcurrencyManager`.
2. **Database Consistency**: SQLite WAL mode prevents database corruption. Uncommitted SQLite transactions are rolled back automatically.
3. **Restart Procedure**: Restart the service daemon. The startup routine scans `task_assignments` for `DISPATCHED` records whose leases expired, increments the fencing token, and re-queues the step. Any delayed output from the zombie worker is rejected with `Stale fencing token`.

#### 4.2 Adversarial Scope Breach or Hunk Escapes
If an untrusted model attempts to touch files outside `authorized_mutation_paths`:
- Intercepted by `HardenedRealRepoPipeline.validate_patch_scope` at point-of-use.
- Immediate terminal transition to `WorkOrderState.REJECTED` with disposition `REJECTED_SCOPE_VIOLATION`.
- An audit alert is emitted. No modifications are applied to target repos or validation sandboxes.

#### 4.3 Out-of-Band Repository Mutation (TOCTOU Attack)
If an external process alters files in the target repository between validation and deliverable export:
- `HardenedRealRepoPipeline.export_deliverable` recalculates the target repository hash against the pre-validation snapshot.
- Raises `TOCTOUMutationError`.
- Export aborts; no tainted deliverable bundle is issued.
- Remediation: Investigate external processes modifying the repo tree, restore git clean state (`git status`, `git checkout`), and re-run validation.

#### 4.4 Queue Capacity Saturation
If work orders arrive faster than worker throughput:
- `ConcurrencyManager.check_admission_capacity` raises `QueueCapacityExceededError`.
- Caller receives HTTP 429 / backpressure signal.
- Remediation: Allow existing tasks to finish, or scale worker concurrency if GPU VRAM envelope permits.

---

### 5. Protected Host Infrastructure & Non-Interference Invariants

The Dell Precision 5820 host (`10.0.8.5`) and local workstation host run critical campaign processes that must NEVER be killed, signaled, or restarted:
1. **PID 986 (`hermes-agent`)**: Autonomous orchestrator gateway.
2. **PID 3130937 (`opencode`)**: Continuous automated test and benchmark runner.
3. **PID 2093382 (`ssh`)**: Persistent encrypted SSH tunnel forwarding local port 18010 to remote orchestrator gateway port 8010.

**Pre-Execution Invariant**: Always execute `phase7/tests/test_phase7_preregistration_gates.py` or run `phase7/run_demo.py` section 1 before beginning maintenance to confirm all three protected PIDs are active.
