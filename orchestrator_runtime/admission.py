"""Admission control: the gateway decides when a request may occupy a worker slot, and never queues inside a worker.

Each worker has an in-flight count and a bounded adaptive concurrency limit (start at the observed slot count, halve on
distress, grow back after a run of healthy completions). Requests that cannot be admitted wait in a bounded per-pool
queue ordered by priority class, then fair share across clients, then arrival (R2). Waiting ends at admission, at the
request's deadline (R7), at the queue's maximum wait, or when the client goes away (R1). Drained workers (R5) admit
nothing new. Everything here is deterministic given arrival order.
"""
from __future__ import annotations

import itertools
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Iterable

PRIORITIES = {"interactive": 0, "batch": 1, "background": 2}


class AdmissionRejected(Exception):
    def __init__(self, code: str, status: int, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message
        self.retry_after = retry_after


class AdmissionCancelled(Exception):
    """The client went away (or its deadline hit) while it was waiting; nothing was dispatched."""


class PoolUnavailable(Exception):
    """No worker in the pool is eligible at all (as opposed to eligible but busy): the caller may fall back."""


@dataclass
class Ticket:
    pool: str
    priority: str = "interactive"
    client_id: str = "default"
    deadline: float | None = None  # time.monotonic() value
    seq: int = 0
    enqueued_at: float = field(default_factory=time.monotonic)
    cancelled: threading.Event = field(default_factory=threading.Event)


@dataclass
class _WorkerSlots:
    inflight: int = 0
    limit: int = 1
    ceiling: int = 1
    healthy_streak: int = 0
    durations: deque = field(default_factory=lambda: deque(maxlen=50))


class AdmissionController:
    def __init__(self, *, queue_max: int = 32, max_wait_seconds: float = 120.0, metrics=None,
                 aimd_increase_after: int = 5, aimd_degraded_factor: float = 3.0) -> None:
        self.queue_max = queue_max
        self.max_wait_seconds = max_wait_seconds
        self.metrics = metrics
        self.aimd_increase_after = aimd_increase_after
        self.aimd_degraded_factor = aimd_degraded_factor
        self._cond = threading.Condition(threading.RLock())
        self._workers: dict[str, _WorkerSlots] = {}
        self._queues: dict[str, list[Ticket]] = {}
        self._served: dict[tuple[str, str], int] = {}
        self._drained: dict[str, float] = {}
        self._seq = itertools.count(1)

    # ------------------------------------------------------------------ capacity input
    def set_slots(self, worker_id: str, slots_total: int) -> None:
        """Observed slot count bounds the adaptive limit: never above what the engine can actually run at once."""
        slots_total = max(1, int(slots_total))
        with self._cond:
            slot = self._workers.setdefault(worker_id, _WorkerSlots(limit=slots_total, ceiling=slots_total))
            if slot.ceiling != slots_total:
                previous_ceiling = slot.ceiling
                slot.ceiling = slots_total
                # Before AIMD has reduced the limit, a newly observed larger worker should start at
                # its full slot count. Preserve an already-adapted limit when only the ceiling changes.
                if slot.limit == previous_ceiling:
                    slot.limit = slots_total
                else:
                    slot.limit = max(1, min(slot.limit, slots_total))
            self._export(worker_id, slot)
            self._cond.notify_all()

    def _export(self, worker_id: str, slot: _WorkerSlots) -> None:
        if self.metrics is not None:
            self.metrics.worker_concurrency_limit.set(slot.limit, worker_id=worker_id)

    # ------------------------------------------------------------------ drain (R5)
    def drain(self, worker_id: str) -> None:
        with self._cond:
            self._drained.setdefault(worker_id, time.time())
            self._cond.notify_all()

    def undrain(self, worker_id: str) -> None:
        with self._cond:
            self._drained.pop(worker_id, None)
            self._cond.notify_all()

    def drained(self) -> dict[str, float]:
        with self._cond:
            return dict(self._drained)

    def inflight(self, worker_id: str) -> int:
        with self._cond:
            slot = self._workers.get(worker_id)
            return slot.inflight if slot else 0

    def limit(self, worker_id: str) -> int:
        with self._cond:
            slot = self._workers.get(worker_id)
            return slot.limit if slot else 0

    def queue_depth(self, pool: str | None = None) -> int:
        with self._cond:
            if pool is not None:
                return len(self._queues.get(pool, []))
            return sum(len(q) for q in self._queues.values())

    # ------------------------------------------------------------------ admission
    def new_ticket(self, pool: str, *, priority: str = "interactive", client_id: str = "default",
                   deadline: float | None = None) -> Ticket:
        return Ticket(pool=pool, priority=priority if priority in PRIORITIES else "interactive",
                      client_id=client_id, deadline=deadline, seq=next(self._seq))

    def _order_key(self, ticket: Ticket) -> tuple[int, int, int]:
        return (PRIORITIES[ticket.priority], self._served.get((ticket.pool, ticket.client_id), 0), ticket.seq)

    def _retry_after(self, pool: str, position: int) -> int:
        durations = [d for slot in self._workers.values() for d in slot.durations]
        typical = statistics.median(durations) if durations else 30.0
        return int(min(120, max(1, round(typical * (position + 1)))))

    def acquire(self, ticket: Ticket, candidates: Callable[[], Iterable[str]]) -> str:
        """Block until a slot on one of ``candidates()`` (ordered by preference) is granted to this ticket.

        ``candidates`` is re-evaluated on every wake so health, drain and capacity changes are honoured while waiting.
        Raises PoolUnavailable when nothing in the pool is eligible at all, AdmissionRejected for queue-full,
        max-wait and deadline, and AdmissionCancelled when the client went away.
        """
        with self._cond:
            queue = self._queues.setdefault(ticket.pool, [])
            if len(queue) >= self.queue_max:
                raise AdmissionRejected("capacity_exhausted", 429, f"pool '{ticket.pool}' queue is full",
                                        self._retry_after(ticket.pool, len(queue)))
            queue.append(ticket)
            self._metric_queue(ticket.pool)
            try:
                while True:
                    if ticket.cancelled.is_set():
                        raise AdmissionCancelled()
                    now = time.monotonic()
                    if ticket.deadline is not None and now >= ticket.deadline:
                        raise AdmissionRejected("deadline_exceeded", 504, "deadline passed while queued")
                    if now - ticket.enqueued_at >= self.max_wait_seconds:
                        raise AdmissionRejected("capacity_exhausted", 429, f"no capacity in pool '{ticket.pool}' within "
                                                f"{self.max_wait_seconds:.0f}s",
                                                self._retry_after(ticket.pool, queue.index(ticket)))
                    eligible = [w for w in candidates() if w not in self._drained]
                    if not eligible:
                        raise PoolUnavailable(ticket.pool)
                    if min(queue, key=self._order_key) is ticket:
                        for worker_id in eligible:
                            slot = self._workers.setdefault(worker_id, _WorkerSlots())
                            if slot.inflight < slot.limit:
                                slot.inflight += 1
                                self._served[(ticket.pool, ticket.client_id)] = self._served.get((ticket.pool, ticket.client_id), 0) + 1
                                return worker_id
                    self._cond.wait(0.25)
            finally:
                if ticket in queue:
                    queue.remove(ticket)
                self._metric_queue(ticket.pool)
                self._cond.notify_all()

    def _metric_queue(self, pool: str) -> None:
        if self.metrics is not None:
            self.metrics.scheduler_queue_depth.set(len(self._queues.get(pool, [])), pool=pool)

    def release(self, worker_id: str, *, ok: bool, duration: float | None = None, distress: bool = False) -> None:
        """Free the slot and adapt the limit: halve on distress (timeout, provider failure, or a call far slower than
        this worker's recent median); add one after a run of healthy completions, never above the slot ceiling."""
        with self._cond:
            slot = self._workers.setdefault(worker_id, _WorkerSlots())
            slot.inflight = max(0, slot.inflight - 1)
            slow = False
            if duration is not None:
                if slot.durations and len(slot.durations) >= 5:
                    slow = duration > self.aimd_degraded_factor * statistics.median(slot.durations)
                if ok:
                    slot.durations.append(duration)
            if distress or not ok or slow:
                slot.limit = max(1, slot.limit // 2)
                slot.healthy_streak = 0
            else:
                slot.healthy_streak += 1
                if slot.healthy_streak >= self.aimd_increase_after and slot.limit < slot.ceiling:
                    slot.limit += 1
                    slot.healthy_streak = 0
            self._export(worker_id, slot)
            self._cond.notify_all()
