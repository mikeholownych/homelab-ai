# Phase 11 Experiment Scheduling Report: Concurrency Management and Serving Isolation

## Executive Summary

Phase 11 Workstream H implemented the Optimization Experiment Scheduler. The scheduler governs batch evaluation runs, enforces maximum concurrency constraints, provides durable crash-resilient job tracking in SQLite WAL mode, and strictly guards against interference with protected resident serving models.

---

## 1. Concurrency Containment & Slot Allocation

- **Slot Cap**: The scheduler enforces an absolute maximum concurrency limit (default $N=2$) to prevent host resource starvation and GPU memory contention.
- **Dynamic Slot Acquisition**: Jobs acquire slots atomically. When slots are exhausted, subsequent submissions are queued in `PENDING` state until running jobs transition to terminal states (`COMPLETED`, `FAILED`, `CANCELLED`).
- **Resource Recovery**: Slot release is guaranteed via transactional finalizers, ensuring abnormal job termination does not leak concurrency slots.

---

## 2. Protected Resident Non-Interference Guard

The scheduler inspects every submitted job configuration before slot assignment:
- If a job requests `execution_mode == PHYSICAL` and targets a model identity distinct from the active resident model (`Qwen/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`), the scheduler verifies whether an operator-signed maintenance proposal exists.
- In the absence of an authorized proposal, the job is immediately rejected with `ResidentInterferenceError`.
- This ensures experimental model runs can never inadvertently displace or crash active engineering services.

---

## 3. Persistent Job Tracking & State Control

- All job transitions (`PENDING` $\to$ `RUNNING` $\to$ `PAUSED` $\to$ `COMPLETED` / `CANCELLED`) are persisted synchronously to SQLite in WAL mode.
- Operators can pause, resume, or cancel long-running evaluation experiments cleanly without leaving orphan subprocesses or unfinalized locks.
