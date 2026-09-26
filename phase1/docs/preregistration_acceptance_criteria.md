# Phase 1 Acceptance Criteria and Preregistration

**Document ID**: PREREG-PHASE1-2026-09-26  
**Status**: REGISTERED (PRE-IMPLEMENTATION)  
**Author**: Antigravity Autonomous Engineering Agent  
**Base Repository Commit**: `8b25d26fb52cd7ca863ec4f428dd9ac45a8b65d6` (Phase 0 verified baseline)  
**Isolated Branch**: `phase1-controlled-live`  
**Isolated Worktree**: `.worktrees/phase1-controlled-live`  
**Target Live Model Endpoint**: `http://127.0.0.1:18010/v1` (Tunnel to `ai-5820-01:8010`, serving `engineering/b0` on dual Arc Pro B65)  

---

## 1. Baseline Verification and Historical Preservation Gates (G-01)

- **G-01.1 (Phase 0 Immutability)**: The Phase 0 commit `8b25d26` and its historical disposition (`OFFLINE_WORK_ORDER_VERTICAL_SLICE: PROVEN`) are verified and preserved without retroactive modification.
- **G-01.2 (Independent Audit & Adversarial Testing)**: Conduct a source-level review of Phase 0 invariants, identify security boundaries reliant on in-process simulation, and write executable adversarial test cases before implementing Phase 1 solutions.

---

## 2. Operating-System Execution Containment Gates (G-02)

- **G-02.1 (Kernel Namespace Isolation)**: Untrusted live workers must execute strictly within an OS-level sandbox powered by Linux user, IPC, PID, and network namespaces (`bwrap` / Bubblewrap).
- **G-02.2 (Filesystem Containment)**:
  - System paths (`/usr`, `/lib`, `/lib64`, `/bin`) are mounted strictly read-only.
  - Sensitive host paths (`/home`, `/etc/shadow`, credentials, other worktrees) are invisible/inaccessible.
  - The worker has writable access strictly to an ephemeral, disposable task worktree directory.
- **G-02.3 (Network Isolation)**: Network egress is completely disabled (`--unshare-net`) for worker task executions. Outbound socket calls must fail with `Network unreachable`.
- **G-02.4 (PID & Signal Isolation)**: The worker runs in a separate PID namespace and cannot view, trace, or signal host processes.

---

## 3. Real-Process Recovery and Durable Workflow Gates (G-03)

- **G-03.1 (Separate Process Boundaries)**: Verify workflow engine leasing, fencing, and crash resumption across real distinct operating system processes (`subprocess` / `multiprocessing`).
- **G-03.2 (Worker Process SIGKILL Recovery)**: When an active worker process is abruptly terminated via `SIGKILL`, its lease expires and the control plane reassigns the task with an incremented fencing token.
- **G-03.3 (Orchestrator Process SIGKILL Recovery)**: When the orchestrator process is killed mid-execution, re-launching it re-hydrates state directly from SQLite WAL on disk without relying on worker narratives.
- **G-03.4 (Atomic Fencing Token Rejection Across Processes)**: A late worker process submitting after lease expiry is atomically rejected by SQLite transaction (`STALE_FENCING_TOKEN`).

---

## 4. Controlled Live-Model Adapter Gates (G-04)

- **G-04.1 (Non-Authoritative Adapter)**: The live adapter acts strictly as an untrusted execution channel; it possesses no authority over task admission, scope grants, tool authorization, or acceptance criteria.
- **G-04.2 (Structured Request & Response Logging)**: All HTTP exchanges with `http://127.0.0.1:18010/v1` record correlated request IDs, token usage, raw completions, structured tool calls, and duration in the audit log.
- **G-04.3 (Handoff vs Acceptance)**: The model's response is treated as an advisory engineering handoff. Final disposition is decided strictly by independent validation of the produced patch artifact.
- **G-04.4 (Resource Boundary & Contention Guard)**: Sequential dispatch with concurrency = 1, ensuring zero contention with the running host campaign.

---

## 5. End-to-End Live Task Execution Gate (G-05)

- **G-05.1 (Genuine Engineering Defect)**: Execute against a real Python defect in a disposable repository fixture with pre-registered failing unit tests.
- **G-05.2 (Disconnected Human Interface)**: The interface submits the work order and disconnects. The control plane executes admission, containment setup, live model dispatch, patch synthesis, and independent validation autonomously.
- **G-05.3 (Independent Acceptance)**: Acceptance is achieved only if pre-registered tests pass under the independent validator in a clean sandbox.
- **G-05.4 (Audit Trail & Artifact Lineage)**: Full evidence bundle exported with SHA-256 CAS hashes for the prompt, model response, patch, and test verdict.

---

## 6. Final Terminal Disposition Gate (G-06)

- Only if all gates G-01 through G-05 pass, issue:
  `PHASE_1_CONTROLLED_LIVE_EXECUTION: PROVEN`
- If containment or live inference encounters an insurmountable blocker, report:
  `LIVE_INTEGRATION_BLOCKED_BY_RESOURCE_AUTHORITY` or `PARTIALLY_VALIDATED` with the exact root cause preserved.
