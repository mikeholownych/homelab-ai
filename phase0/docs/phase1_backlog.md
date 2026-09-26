# Phase 1 Implementation Backlog

**Document ID**: BACKLOG-PHASE1-2026-09-26  
**Status**: APPROVED BASELINE  
**Author**: Antigravity Autonomous Engineering Agent  
**Context**: Gaps Exposed by Phase 0 Vertical Slice Prototype (Section 14)  

---

## 1. Overview and Scope

The Phase 0 offline prototype proved the core architectural invariants, durable state machine, cryptographic capability scoping, failure containment boundaries, and independent acceptance model. 

In accordance with Section 14, this backlog is strictly limited to gaps and technical transitions exposed by the prototype that are necessary to transition from offline simulation to live local model execution on the dual Intel Arc Pro B65 workstation.

---

## 2. Prioritized Engineering Backlog

### P1-01: Live Intel Arc Pro B65 Execution Adapters (vLLM XPU & IPEX-LLM)
- **Gap Exposed**: Phase 0 relied on deterministic simulated worker adapters (`FastCoderWorker`, `InvestigatorWorker`).
- **Required Implementation**:
  - Implement asynchronous HTTP/SSE streaming adapters connecting to local vLLM XPU (Card 0) and IPEX-LLM (Card 1) endpoints.
  - Implement robust streaming tool parsers (e.g., Hermes function calling, ChatML tool extraction) that intercept tool calls and route them through `ScopeGuard`.
  - Handle model timeouts, context overflow errors, and GPU out-of-memory events with explicit classification into `FailureClass.TIMEOUT` and `FailureClass.ENVIRONMENT_ERROR`.

### P1-02: OS-Level Sandbox Containment (Linux cgroups & Namespaces)
- **Gap Exposed**: In Phase 0, `ScopeGuard` enforces path whitelist checks in-process at the Python layer. An adversarial or hallucinating model executing shell commands could bypass in-process checks.
- **Required Implementation**:
  - Wrap worker tool execution inside ephemeral Linux namespaces (`unshare` / `bwrap`) or rootless containers.
  - Restrict filesystem mount points strictly to the target repository worktree and read-only system libraries.
  - Enforce zero network egress (`--unshare-net`) at the kernel level for worker sandboxes.

### P1-03: Interactive Human Clarification Flow for Ambiguity Resolution
- **Gap Exposed**: In Phase 0, compiler ambiguity detection sets work orders to `AMBIGUOUS`, which fails admission closed.
- **Required Implementation**:
  - Implement an interactive clarification message exchange in `HumanInterfaceAdapter`.
  - When compiler surfaces an `Ambiguity` with status `UNRESOLVED`, generate a structured questionnaire for the human operator.
  - Upon receiving human resolution, update `Ambiguity.status = HUMAN_RESOLVED` and transition work order to `ADMITTED` without re-authorizing unaffected fields.

### P1-04: Concurrent Parallel Task Dispatch in Workflow Engine
- **Gap Exposed**: Phase 0 executes DAG steps sequentially; multi-task parallel branches were modeled with `permitted_parallelism = 1`.
- **Required Implementation**:
  - Extend `WorkflowEngine.advance_ready_tasks` to dispatch multiple independent tasks concurrently when dependency conditions are satisfied.
  - Maintain fine-grained worker lease tables allowing Card A and Card B to process independent tasks simultaneously without lock contention.

### P1-05: Automated Empirical Benchmark Feeder for Worker Registry
- **Gap Exposed**: Worker capability profiles in Phase 0 were loaded with empirical pass rates from test fixtures.
- **Required Implementation**:
  - Implement an automated bridge connecting the offline benchmark harness to `WorkerCapabilityRegistry`.
  - Automatically re-evaluate worker capability pass rates after model weight updates, quantization changes, or driver upgrades.
  - Automatically mark workers `DEGRADED` or `OFFLINE` if consecutive task failures exceed failure thresholds.

### P1-06: Git Worktree Isolation for Competing Repair Hypotheses
- **Gap Exposed**: Independent validation in Phase 0 used temporary directory tree copies (`tempfile.TemporaryDirectory`).
- **Required Implementation**:
  - Integrate native `git worktree add --detach` and `git worktree remove` for validator sandboxes and multi-hypothesis parallel repair branches.
  - Leverage Git's internal object store to avoid duplicating repository bytes on disk.

---
