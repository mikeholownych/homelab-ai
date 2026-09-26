# Phase 2 Preregistration: Acceptance Criteria and Non-Negotiable Boundaries
## Durable Multi-Worker Execution, Empirical Capability and Representative Engineering Validation

**Date**: 2026-09-26  
**Workspace**: `/home/mike/Projects/aihost/.worktrees/phase2-multi-worker`  
**Base Commit**: `db1172a93c6e5fefa7b2f80631d874e3da2b09c7` (from branch `phase1-controlled-live`)  
**Status**: **FROZEN PRIOR TO IMPLEMENTATION**

---

### Non-Negotiable Architectural Invariants

1. **Authority Centralization**: Models and execution adapters are untrusted workers. The execution control plane is the sole authority for admission, capability issuance, scheduling, state transitions, and terminal disposition.
2. **Session Independence**: Human instructions enter via human-interface adapters and compile into canonical, versioned work orders. Once admitted, execution proceeds to completion independently of any human interface session.
3. **Artifact-Centered Lineage**: Worker-to-worker communication occurs exclusively via immutable, content-addressed artifacts in the CAS `ArtifactStore`. Downstream workers never receive unverified worker self-reports or raw conversation narratives.
4. **Current-State Authority Revalidation**: Authority, mutation scope, tool permissions, and work order version are rechecked atomically before dispatching an assignment and before committing an output artifact.
5. **Operating-System Containment**: All code mutations, execution attempts, and validation test runs take place inside Bubblewrap (`bwrap`) containers enforcing unshared namespaces (PID, IPC, UTS, user, mount, cgroup), cleared environments, read-only system mounts, and blocked network egress (`--unshare-net`).
6. **Supervisor-Authoritative Acceptance**: Passing tests, worker acknowledgment, or model consensus do not constitute task acceptance. Acceptance is determined solely by the supervisor running independent validators against the exact produced artifact.
7. **Strict Campaign Isolation**: The active T5820 autonomous-readiness campaign, its gateway, vLLM processes, OpenCode session, model weights, and the original checkout at `/home/mike/Projects/aihost` must remain undisturbed. Concurrency must be strictly controlled to prevent hardware contention.

---

### Preregistered Acceptance Gates

#### Gate 1: Phase 1 Independent Verification & Baseline Preservation
- **Criterion**: The delivered Phase 1 implementation (56 files listed in `phase1/evidence/manifest.sha256`) must verify 100% against its cryptographic checksums, the 55 regression tests (39 Phase 0 + 16 Phase 1) must pass without modification, and Phase 1 must be preserved as an immutable baseline.
- **Verification**: `sha256sum -c phase1/evidence/manifest.sha256`, execution of full test suite in clean worktree.

#### Gate 2: Durable Dependency-Aware Scheduling (Bounded DAG)
- **Criterion**: The workflow engine must schedule a DAG of specialized task steps: `investigation` -> `test_development` -> `implementation` -> `independent_review` -> `bounded_repair` -> `independent_validation`. Downstream assignments must remain pending until all upstream dependencies are completed. Stale assignments must be rejected if an upstream dependency is superseded or failed.
- **Verification**: Unit and property tests verifying DAG ordering, topological dispatch, dependency resolution, and atomic state transitions in SQLite WAL.

#### Gate 3: Artifact-Centered Handoff Contracts
- **Criterion**: Every handoff must produce an immutable CAS artifact with full cryptographic provenance.
  - Implementer receives canonical WorkOrder, source revision digest, and constraints.
  - Reviewer receives candidate patch artifact and acceptance criteria; reviewer findings must link to concrete source lines and hashes. Review findings are advisory.
  - Repair worker receives failed artifact, validator error logs, and current patch; cannot exceed retry budget.
- **Verification**: Handoff schema validation tests, audit event trail assertions, and artifact lineage traversal tests.

#### Gate 4: Empirical Worker Capability Measurement & Bounded Routing
- **Criterion**: Capability registry must distinguish `SYNTHETIC_FIXTURE`, `CONTROLLED_BENCHMARK`, and `EMPIRICAL_DEPLOYED_MEASUREMENT`. Routing must select qualified workers based on empirical measurements bound to the deployed configuration (Intel Arc Pro B65, Qwen3-Coder INT4, vLLM XPU) and enforce independence constraints (implementer != reviewer). Router must fail closed when required capabilities are not empirically demonstrated.
- **Verification**: Registry and router contract tests verifying independence constraints and empirical pass-rate thresholds.

#### Gate 5: Real-Process Interruption, Concurrency & Recovery (12 Failure Modes)
- **Criterion**: Must prove resilience across real OS child processes using POSIX signals:
  1. Concurrent assignments with independent dependencies.
  2. Duplicate assignment dispatch handling.
  3. Worker SIGKILL during implementation.
  4. Worker SIGKILL after artifact write but before DB commit.
  5. Orchestrator restart with active workers.
  6. Stale fencing token rejection (zombie worker).
  7. Delayed review of superseded artifact.
  8. Work order revision during cooperative execution.
  9. Capability token revocation during active assignment.
  10. Validator interruption recovery.
  11. Partial DAG completion recovery.
  12. Retry-budget exhaustion termination.
- **Verification**: Multi-process integration tests with real OS processes (`subprocess.Popen`) and monotonic fencing tokens.

#### Gate 6: Representative Engineering Task Cohort
- **Criterion**: Evaluate four distinct engineering task classes in isolated repositories:
  1. **Defect Repair**: Reproducible defect repair (`calculate_moving_average` in `stats_utils.py`).
  2. **Multi-File Implementation**: Coordinated feature across multiple modules with contract enforcement.
  3. **Meaningful Test Development**: Authoring independent test suite that genuinely fails on the baseline defect and passes on the fix (verified against mutant/fault injection).
  4. **Maintainability & Refactoring**: Code simplification and dead-code removal with verified behavioral preservation (all existing tests remain passing).
- **Verification**: Independent acceptance execution under Bubblewrap containment for each cohort task.

#### Gate 7: Matched Cooperative vs. Single-Worker Comparison
- **Criterion**: Compare the cooperative workflow (Implementer + Reviewer + Repair) against single-worker execution on identical starting revisions, acceptance contracts, and aggregate resource budgets. Measure accepted completion rate, defect detection, and resource efficiency.
- **Verification**: Comparative benchmark suite producing side-by-side execution metrics.

#### Gate 8: Supervisor-Authoritative Completion & Auditability
- **Criterion**: Final task disposition (`ACCEPTED`, `REJECTED`, `FAILED_BUDGET_EXHAUSTED`, `UNAUTHORIZED`) must be computed by the supervisor from validator verdicts and execution evidence. Complete tamper-evident evidence bundle must be exportable via `HumanInterfaceAdapter`.
- **Verification**: Audit trail validation, CAS integrity verification, and tamper-detection checks.

#### Gate 9: Operational Integrity & Zero Host Impact
- **Criterion**: Primary checkout (`/home/mike/Projects/aihost`) and running T5820 processes (PID 2093382, OpenCode, vLLM) must remain untouched.
- **Verification**: `git status` check on main repository, port and process check.
