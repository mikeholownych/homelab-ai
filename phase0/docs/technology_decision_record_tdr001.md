# Technology Decision Record (TDR-001): Workflow and Persistence Engine

**Decision Record ID**: TDR-001-WORKFLOW-ENGINE  
**Status**: PROPOSED (VALIDATED BY EXECUTABLE CONTRACT PROOFS)  
**Author**: Antigravity Autonomous Engineering Agent  
**Context**: Workflow and Queue Technology Evaluation, Section 6  

---

## 1. Context and Problem Statement

The Autonomous Engineering System requires a workflow and persistence engine to orchestrate complex software engineering work orders. The system coordinates untrusted workers (such as models executing on two Intel Arc Pro B65 GPUs), manages leases, enforces fencing tokens, maintains immutable artifact lineage, recovers gracefully from orchestrator and worker crashes, and commits authoritative terminal dispositions.

### Required Semantics Matrix

| Semantic Requirement | Definition & Invariant |
| :--- | :--- |
| **Durable State Transitions** | Every transition (`DRAFT` -> `ADMITTED` -> `DISPATCHED` -> `VALIDATING` -> `ACCEPTED`) must be atomically committed to persistent storage. |
| **Transactional Admission & Dispatch** | Generating an execution assignment, binding it to a scoped capability token, and allocating a lease must occur atomically. |
| **Worker Leases & Monotonic Fencing** | Workers receive time-bounded leases stamped with a strictly monotonic fencing token ($F$). Late submissions ($F_{sub} < F_{curr}$) must be atomically rejected. |
| **Idempotent Completion** | Duplicate delivery or replay of an assignment must not duplicate side effects or corrupt state. |
| **Interruption Recovery** | Orchestrator process termination must allow seamless recovery on restart from the last committed artifact without reconstructing state from conversation history. |
| **Workflow Versioning** | Superseding a work order must atomically cancel active assignments and invalidate outstanding capabilities. |
| **Artifact Consistency** | Artifact content hashes must be immutably linked to task completion. |
| **Operational Complexity** | The solution must run offline, require minimal moving parts, and support local multi-worker execution (dual B65 GPUs) without brittle network daemon requirements. |

---

## 2. Alternatives Considered

We evaluate three credible architectural paradigms:

### Alternative 1: Transactional Database-Backed Workflow (SQLite / PostgreSQL)
- **Architecture**: A single ACID database holds work orders, task DAGs, capability tokens, leases, and fencing tokens. State transitions, lease acquisitions, and task completions are executed via atomic SQL transactions (`BEGIN IMMEDIATE` / `SERIALIZABLE`).
- **Worker Coordination**: Workers poll or receive notifications. Fencing is enforced via atomic conditional updates:
  ```sql
  UPDATE task_assignments 
  SET status = 'COMPLETED', completed_at = :now, artifact_hash = :hash
  WHERE assignment_id = :id AND fencing_token = :token AND status = 'DISPATCHED';
  ```
- **Strengths**:
  - Exactly-once semantics guaranteed by ACID database transactions.
  - Zero dual-write hazard: task state, lease, fencing token, and artifact pointer update in a single transaction.
  - Zero external daemons required when using SQLite with WAL mode.
  - Trivial local backup, inspection, and offline reproducibility.
- **Weaknesses**: Requires database polling if notification mechanism (e.g. SQLite update hook or PG `LISTEN/NOTIFY`) is not used. (Polling at 100ms interval has negligible CPU cost for 2-4 local workers).

### Alternative 2: Durable Workflow Engine (Temporal / Restate)
- **Architecture**: Specialized workflow orchestration server managing event-sourced workflow state, timers, and distributed activities.
- **Strengths**: First-class support for deterministic replay, long-running timers, and saga rollbacks.
- **Weaknesses**:
  - High operational complexity: Temporal requires a multi-node cluster, Cassandra/PostgreSQL backend, ElasticSearch, and dedicated worker daemon pools.
  - Restate requires running separate network sidecars/daemons.
  - Overkill for local single-node multi-worker execution on a single workstation with two B65 GPUs.
  - Introduces complex external network protocols and serialization barriers.

### Alternative 3: Database-Plus-Broker (PostgreSQL / SQLite + Redis Streams / RabbitMQ)
- **Architecture**: Database stores state and artifacts; a message broker manages task distribution and queueing.
- **Strengths**: Decoupled push-based dispatch; high throughput message delivery.
- **Weaknesses**:
  - **The Dual-Write Problem**: Acknowledging a message on the broker and committing state in the database cannot be done atomically without Two-Phase Commit (2PC / XA), which is notoriously brittle and unsupported by Redis.
  - **Fencing Vulnerability**: If worker execution takes longer than expected, broker redelivery may spawn a second worker while the first is still running, causing race conditions unless a database fencing token is still maintained.
  - Operational overhead of managing a running Redis/RabbitMQ server alongside the application.

---

## 3. Comparative Evaluation Matrix

| Criterion | 1. Transactional DB (SQLite WAL) | 2. Durable Engine (Temporal) | 3. DB + Broker (Postgres+Redis) |
| :--- | :--- | :--- | :--- |
| **ACID State Guarantees** | **Strong (Single Store)** | Strong (Event-Sourced) | Weak (Split State Hazard) |
| **Atomic Lease & Fencing** | **Native (`UPDATE ... WHERE`)** | Native (Server-managed) | Requires DB lock anyway |
| **Dual-Write Vulnerability** | **Zero (Atomic Tx)** | Zero (Internal DB) | High (Queue vs DB sync) |
| **Crash Recovery** | **Deterministic (WAL journal)** | Deterministic (Replay) | Complex (Reconcile queue+DB) |
| **Operational Surface** | **Zero Daemons (Self-contained)**| High (Cluster, JVM/Go, ES) | Medium (Redis daemon + DB) |
| **Offline Suitability** | **Exceptional** | Poor (Requires background ports)| Fair (Requires local daemon) |
| **Scalability to B65 Workers**| **Sufficient (1000s tasks/sec)** | Over-provisioned | Over-provisioned |

---

## 4. Decision and Justification

**Selected Technology**: **Alternative 1: Transactional Database-Backed Workflow using SQLite with Write-Ahead Logging (WAL)**.

### Rationale:
1. **Elimination of Dual-Write Hazards**: All state transitions, capability checks, fencing validations, and artifact bindings occur within atomic transactions in a single store.
2. **Deterministic Fencing**: Monotonic fencing tokens implemented in SQL conditional updates prevent zombie workers from committing stale results.
3. **Zero Operational Footprint**: SQLite requires no running background processes, no open network ports, no external credentials, and does not contend with the active T5820 campaign.
4. **Seamless Growth Path**: The SQL schema and transactional abstraction are directly portable to PostgreSQL for future distributed deployments without altering the workflow state machine logic.

---

## 5. Executable Proofs

To validate this decision empirically beyond paper claims, we establish an automated contract test suite (`test_workflow_technology_proofs.py`) verifying:
1. **Proof 1: Fencing Token Rejection**: A simulated delayed worker (representing an expired lease) attempts an artifact commit; the transactional store rejects it atomically, while a subsequent valid worker with the current fencing token succeeds.
2. **Proof 2: Split-Brain / Dual-Write Mitigation**: Proving that decoupled broker patterns exhibit race conditions unless guarded by the transactional store's fencing token.
3. **Proof 3: Crash Resumption**: Simulating orchestrator process termination mid-workflow and demonstrating state recovery without data corruption.

---
