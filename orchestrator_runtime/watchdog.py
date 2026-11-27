"""Worker busy-watchdog logic (docs/design/WORKER-BUSY-WATCHDOG.md): pure, clock-injected, no I/O.

Signal: a worker is *stalled* while its engine reports requests running and none of its progress counters (in-flight prompt/generation
tokens, completed-token totals) have changed. ``StallTracker`` turns engine readings into "seconds stalled"; the gateway exports it as
``aihost_engine_stalled_seconds``. ``Ladder`` decides the next rung for one worker (drain, graceful stop, forced kill, restart, readmit)
and limits restarts per hour. The executor that performs the actions lives in scripts/worker_watchdog.py and runs on the controller.
"""
from __future__ import annotations

import enum
from collections import deque
from dataclasses import dataclass, field


class StallTracker:
    """Per worker: how long has the engine been running work without progress or stalled on PCIe/NVMe I/O."""

    def __init__(self) -> None:
        self._state: dict[str, tuple[float, float]] = {}  # worker -> (progress value, time it last changed)
        self._io_stall_since: dict[str, float] = {}  # worker -> time sustained PCIe/NVMe I/O wait began

    def update(
        self,
        worker_id: str,
        now: float,
        running: float | None,
        progress: float | None,
        *,
        nvme_io_wait_ratio: float | None = None,
        nvme_io_wait_threshold: float = 0.75,
        nvme_read_latency_s: float | None = None,
        nvme_read_latency_threshold_s: float = 0.05,
    ) -> float:
        """Seconds stalled.

        Combines token-progress stall detection with sustained PCIe/NVMe I/O wait stalls while
        requests are running. Unknown readings or an idle engine reset both clocks cleanly.
        """
        if running is None or progress is None or running <= 0:
            self._state.pop(worker_id, None)
            self._io_stall_since.pop(worker_id, None)
            return 0.0

        last = self._state.get(worker_id)
        if last is None or progress != last[0]:
            self._state[worker_id] = (progress, now)
            progress_stall_s = 0.0
        else:
            progress_stall_s = max(0.0, now - last[1])

        io_stalled = (
            (nvme_io_wait_ratio is not None and nvme_io_wait_ratio >= nvme_io_wait_threshold)
            or (nvme_read_latency_s is not None and nvme_read_latency_s >= nvme_read_latency_threshold_s)
        )
        if io_stalled:
            since = self._io_stall_since.setdefault(worker_id, now)
            io_stall_s = max(0.0, now - since)
        else:
            self._io_stall_since.pop(worker_id, None)
            io_stall_s = 0.0

        return max(progress_stall_s, io_stall_s)

    def unresponsive(self, worker_id: str, now: float) -> float:
        """The engine accepted the connection but did not answer in time (a wedged main loop answers /metrics no better than
        it answers requests). If work was running at the last reading, the stall clock keeps counting from the last progress."""
        last = self._state.get(worker_id)
        return max(0.0, now - last[1]) if last is not None else 0.0

    def active(self, worker_id: str) -> bool:
        return worker_id in self._state

    def forget(self, worker_id: str) -> None:
        self._state.pop(worker_id, None)
        self._io_stall_since.pop(worker_id, None)


class Action(str, enum.Enum):
    DRAIN = "drain"
    STOP = "stop"
    KILL = "kill"
    RESTART = "restart"
    UNDRAIN = "undrain"
    ALERT = "alert"


@dataclass(frozen=True)
class Policy:
    stuck_after_s: float = 120.0
    drain_wait_s: float = 30.0
    max_restarts_per_hour: int = 3


@dataclass
class _Worker:
    phase: str = "healthy"  # healthy, draining, stopping, killing, restarting, verifying, abandoned
    since: float = 0.0
    restarts: deque = field(default_factory=deque)  # timestamps of completed restarts


class Ladder:
    """One rung at a time per worker. ``decide`` says what to do next; ``performed`` reports how the executor's action went."""

    def __init__(self, policy: Policy | None = None) -> None:
        self.policy = policy or Policy()
        self._workers: dict[str, _Worker] = {}

    def _w(self, worker_id: str) -> _Worker:
        return self._workers.setdefault(worker_id, _Worker())

    def phase(self, worker_id: str) -> str:
        return self._w(worker_id).phase

    def _restarts_last_hour(self, w: _Worker, now: float) -> int:
        while w.restarts and now - w.restarts[0] > 3600:
            w.restarts.popleft()
        return len(w.restarts)

    def decide(self, worker_id: str, stalled_s: float, now: float) -> Action | None:
        w, p = self._w(worker_id), self.policy
        if w.phase == "healthy":
            if stalled_s < p.stuck_after_s:
                return None
            if self._restarts_last_hour(w, now) >= p.max_restarts_per_hour:
                w.phase, w.since = "abandoned", now
                return Action.ALERT
            return Action.DRAIN
        if w.phase == "draining":
            if stalled_s < p.stuck_after_s:  # the engine moved again: it recovered, put it back
                return Action.UNDRAIN
            return Action.STOP if now - w.since >= p.drain_wait_s else None
        if w.phase == "killing":
            return Action.KILL
        if w.phase == "stopping":
            return Action.STOP
        if w.phase == "restarting":
            return Action.RESTART
        if w.phase == "verifying":
            return Action.UNDRAIN
        return None  # abandoned: left out of rotation until a human resets it

    def performed(self, worker_id: str, action: Action, now: float, ok: bool) -> None:
        w = self._w(worker_id)
        if action is Action.DRAIN:
            w.phase, w.since = ("draining", now) if ok else ("healthy", now)
        elif action is Action.STOP:
            w.phase = "restarting" if ok else "killing"
        elif action is Action.KILL:
            w.phase = "restarting" if ok else "abandoned"
        elif action is Action.RESTART:
            if ok:
                w.restarts.append(now)
                w.phase = "verifying"
            else:
                w.phase = "abandoned"
        elif action is Action.UNDRAIN:
            if ok:
                w.phase = "healthy"

    def abandon(self, worker_id: str, now: float) -> None:
        """The executor gave up (for example the worker never became ready again): leave it out of rotation."""
        w = self._w(worker_id)
        w.phase, w.since = "abandoned", now

    def reset(self, worker_id: str) -> None:
        """Human acknowledgement of an abandoned worker."""
        self._workers.pop(worker_id, None)
