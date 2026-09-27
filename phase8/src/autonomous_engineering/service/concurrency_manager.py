"""Concurrency, Workspace Isolation, and Conflict Management for Sustained Autonomous Engineering."""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple

from autonomous_engineering.work_order.models import WorkOrder


class ConcurrencyError(Exception):
    """Base error for concurrency management."""


class QueueCapacityExceededError(ConcurrencyError):
    """Raised when queue depth exceeds bounded capacity."""


class AdmissionStoppedError(ConcurrencyError):
    """Raised when task admission is paused by an operator."""


@dataclass
class IsolatedTaskWorkspace:
    """Isolated filesystem workspace for an active engineering task."""
    work_order_id: str
    version: int
    workspace_dir: Path
    locked_paths: Set[str] = field(default_factory=set)

    def cleanup(self) -> None:
        if self.workspace_dir.exists():
            shutil.rmtree(self.workspace_dir, ignore_errors=True)


class ConcurrencyManager:
    """Manages concurrent worker execution, workspace isolation, path locks, and backpressure."""

    def __init__(
        self,
        base_repo_dir: Path,
        max_concurrency: int = 4,
        max_queue_depth: int = 16,
    ) -> None:
        self.base_repo_dir = base_repo_dir
        self.max_concurrency = max_concurrency
        self.max_queue_depth = max_queue_depth
        self._lock = threading.RLock()
        self._active_workspaces: Dict[str, IsolatedTaskWorkspace] = {}
        self._locked_paths: Dict[str, str] = {}  # file_path -> work_order_id
        self._admission_enabled: bool = True

    def pause_admission(self) -> None:
        with self._lock:
            self._admission_enabled = False

    def resume_admission(self) -> None:
        with self._lock:
            self._admission_enabled = True

    @property
    def is_admission_enabled(self) -> bool:
        with self._lock:
            return self._admission_enabled

    def check_admission_capacity(self, current_queue_size: int) -> None:
        """Enforces queue capacity bounds and operator controls."""
        with self._lock:
            if not self._admission_enabled:
                raise AdmissionStoppedError("Task admission is paused by operator.")
            if current_queue_size >= self.max_queue_depth:
                raise QueueCapacityExceededError(
                    f"Queue capacity of {self.max_queue_depth} exceeded (current depth: {current_queue_size}). Backpressure engaged."
                )

    def can_acquire_paths(self, work_order: WorkOrder) -> Tuple[bool, List[str]]:
        """Checks whether the work order's authorized paths conflict with active tasks."""
        with self._lock:
            conflicts = []
            for p in work_order.authorization.authorized_mutation_paths:
                rel_p = str(p).lstrip("/")
                if rel_p in self._locked_paths and self._locked_paths[rel_p] != work_order.work_order_id:
                    conflicts.append(rel_p)
            return (len(conflicts) == 0, conflicts)

    def acquire_workspace(self, work_order: WorkOrder) -> IsolatedTaskWorkspace:
        """Creates an isolated workspace and locks authorized mutation paths."""
        with self._lock:
            if len(self._active_workspaces) >= self.max_concurrency:
                raise ConcurrencyError(
                    f"Max worker concurrency ({self.max_concurrency}) reached."
                )

            can_acquire, conflicts = self.can_acquire_paths(work_order)
            if not can_acquire:
                raise ConcurrencyError(
                    f"Path lock conflict: paths {conflicts} are currently locked by other tasks."
                )

            # Create isolated workspace by copying the baseline repository
            tmp_dir = Path(tempfile.mkdtemp(prefix=f"ws_{work_order.work_order_id}_"))
            # Copy base repo files
            for item in self.base_repo_dir.iterdir():
                if item.name.startswith("."):
                    continue
                dest = tmp_dir / item.name
                if item.is_dir():
                    shutil.copytree(item, dest, symlinks=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                else:
                    shutil.copy2(item, dest)

            locked: Set[str] = set()
            for p in work_order.authorization.authorized_mutation_paths:
                rel_p = str(p).lstrip("/")
                self._locked_paths[rel_p] = work_order.work_order_id
                locked.add(rel_p)

            workspace = IsolatedTaskWorkspace(
                work_order_id=work_order.work_order_id,
                version=work_order.version,
                workspace_dir=tmp_dir,
                locked_paths=locked,
            )
            self._active_workspaces[work_order.work_order_id] = workspace
            return workspace

    def release_workspace(self, work_order_id: str) -> None:
        """Releases workspace and associated path locks."""
        with self._lock:
            if work_order_id in self._active_workspaces:
                ws = self._active_workspaces.pop(work_order_id)
                for p in ws.locked_paths:
                    if self._locked_paths.get(p) == work_order_id:
                        del self._locked_paths[p]
                ws.cleanup()

    def get_active_count(self) -> int:
        with self._lock:
            return len(self._active_workspaces)

    def get_locked_paths(self) -> Dict[str, str]:
        with self._lock:
            return dict(self._locked_paths)
