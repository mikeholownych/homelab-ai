# Phase 2 Backlog: Narrowly Scoped Engineering Tasks Derived from Observed Evidence

## Overview

During Phase 1 execution, the core architectural invariants were proven across real OS processes:
- Strong OS execution containment via Bubblewrap (`bwrap --unshare-all`).
- Interruption recovery and atomic fencing token verification across real child processes.
- Controlled live model execution (`engineering/b0` on Intel Arc Pro B65) for one disposable engineering task.
- Independent acceptance validation inside the ephemeral container with terminal disposition `ACCEPTED`.

The following backlog items represent empirical gaps, observed edge cases, and architectural extensions identified during Phase 1 execution.

---

### Item 1: Resilient Multi-Strategy Diff Normalization and AST-Aware Patching
- **Observation**: Live LLM inference models (including `engineering/b0`) frequently produce unified diffs where context lines retain source indentation rather than diff-standard single-space prefixes, and where hunk header line count arithmetic (`@@ -a,b +c,d @@`) is imprecise. Standard GNU `patch` and `git apply` fail on these subtle formatting variations.
- **Phase 2 Scope**:
  - Implement a specialized Python AST-aware diff normalizer that can match and align hunks against target AST blocks (functions, classes, methods).
  - Support semantic hunk application fallback when line-level context matches within a threshold distance.
  - Maintain cryptographic CAS logging of both raw model output and normalized patch artifacts.

---

### Item 2: Empirical Hardware Benchmarking and Heterogeneous Multi-Worker Routing
- **Observation**: In Phase 1, routing was prepared and tested with `EvidenceSource.EMPIRICAL_DEPLOYED_MEASUREMENT` vs `SYNTHETIC_FIXTURE`, but live execution was strictly constrained to 1 worker at concurrency 1 to avoid contention with the active T5820 campaign.
- **Phase 2 Scope**:
  - Execute an empirical capability evaluation suite against both physical Intel Arc Pro B65 GPUs (PCIe `0000:03:00.0` and `0000:04:00.0`).
  - Measure pass rates, latency, and failure distributions for distinct specialized roles: `investigation`, `defect_patch`, and `independent_review`.
  - Activate multi-worker heterogeneous routing in `OrchestratorControlPlane` to dispatch distinct roles across the measured configurations without hardcoded card assignment.

---

### Item 3: Cgroup v2 Resource Limiting and Rootless Container Isolation
- **Observation**: Phase 1 proved filesystem isolation (read-only system roots, private worktree mount, blocked home directory access) and network isolation (`--unshare-net`). However, memory consumption and CPU share were bounded only by process timeouts.
- **Phase 2 Scope**:
  - Integrate Linux cgroups v2 (`memory.max`, `cpu.weight`, `pids.max`) via `systemd-run --user` or Bubblewrap cgroup support to guard against denial-of-service / memory leaks from malicious or buggy generated code.
  - Add configurable disk write quotas on the mounted worktree directory.

---

### Item 4: Token Usage Telemetry & Streaming Gateway Instrumentation
- **Observation**: The local OpenAI-compatible inference proxy omitted top-level `"usage"` token counts in non-streaming responses.
- **Phase 2 Scope**:
  - Update `LiveModelWorker` to support streaming chunks (`stream=True`) and collect raw completion token counts directly from the backend vLLM/IPEX events.
  - Record fine-grained prompt token count, completion token count, and latency metrics in the CAS metadata dictionary for comprehensive auditability.

---

### Item 5: Human Supervisor Escalation Gate for Budget Exhaustion
- **Observation**: `BoundedRepairController` cleanly terminates at `FAILED_BUDGET_EXHAUSTED` when retries exceed the work order budget.
- **Phase 2 Scope**:
  - Allow human interface adapters to receive an escalation notification when budget exhaustion occurs.
  - Support human authorization to inject additional budget or resolve material ambiguity without resetting the entire DAG state or discarding valid preceding artifacts.
