"""Multi-Repository Engineering Service, Dependency DAG Scheduling, and Concurrency."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from pathlib import Path
import shutil
import tempfile
import threading
import time
from typing import Callable, Dict, List, Optional, Set, Tuple, Any

from autonomous_engineering.core.types import TaskStepState, WorkOrderState
from autonomous_engineering.repository.onboarding import (
    RepositoryOnboardingManager,
    RepositoryNotOnboardedError,
)
from autonomous_engineering.service.concurrency_manager import (
    ConcurrencyError,
    QueueCapacityExceededError,
    AdmissionStoppedError,
    IsolatedTaskWorkspace,
)
from autonomous_engineering.service.observability import ServiceObservability
from autonomous_engineering.workflow.engine import WorkflowEngine, WorkflowEngineError
from autonomous_engineering.workflow.hardened_pipeline import HardenedRealRepoPipeline
from autonomous_engineering.work_order.models import WorkOrder

logger = logging.getLogger(__name__)


class DependencyCycleError(ConcurrencyError):
    """Raised when task dependency graph contains a cycle."""


class DependencyFailedError(ConcurrencyError):
    """Raised when an upstream task dependency fails or is cancelled."""


class TaskSchedulingBlockedError(ConcurrencyError):
    """Raised when a task cannot be scheduled due to unmet dependencies or resource constraints."""


class TaskDependencyManager:
    """Manages explicit task dependencies, cycle detection, and readiness resolution."""

    def __init__(self) -> None:
        self._dependencies: Dict[str, Set[str]] = {}  # task_id -> set of prerequisite task_ids
        self._dependents: Dict[str, Set[str]] = {}    # task_id -> set of downstream task_ids
        self._priorities: Dict[str, int] = {}
        self._lock = threading.RLock()

    def register_task(
        self, task_id: str, dependencies: Optional[List[str]] = None, priority: int = 0
    ) -> None:
        """Registers a task and its declared dependencies, checking for cycles."""
        with self._lock:
            deps = set(dependencies or [])
            # Self-dependency check
            if task_id in deps:
                raise DependencyCycleError(f"Task '{task_id}' cannot depend on itself.")

            # Temporarily record to test for cycles
            self._dependencies[task_id] = deps
            self._priorities[task_id] = priority
            for d in deps:
                self._dependents.setdefault(d, set()).add(task_id)

            # Cycle detection
            if self._has_cycle():
                # Rollback
                for d in deps:
                    self._dependents[d].discard(task_id)
                del self._dependencies[task_id]
                del self._priorities[task_id]
                raise DependencyCycleError(
                    f"Registering task '{task_id}' with dependencies {deps} creates a cyclic dependency."
                )

    def _has_cycle(self) -> bool:
        """Tarjan's/DFS cycle detection on current dependency graph."""
        visited: Dict[str, int] = {}  # 0=unvisited, 1=visiting, 2=visited

        def dfs(node: str) -> bool:
            visited[node] = 1
            for neighbor in self._dependencies.get(node, ()):
                state = visited.get(neighbor, 0)
                if state == 1:
                    return True  # Back-edge detected
                if state == 0:
                    if dfs(neighbor):
                        return True
            visited[node] = 2
            return False

        for node in list(self._dependencies.keys()):
            if visited.get(node, 0) == 0:
                if dfs(node):
                    return True
        return False

    def get_dependencies(self, task_id: str) -> Set[str]:
        with self._lock:
            return set(self._dependencies.get(task_id, ()))

    def is_ready(
        self, task_id: str, terminal_states: Dict[str, WorkOrderState]
    ) -> Tuple[bool, Optional[str]]:
        """Evaluates readiness based on verified terminal dispositions of upstream tasks.
        
        Returns:
            (is_ready, failure_reason)
        """
        with self._lock:
            deps = self._dependencies.get(task_id, set())
            if not deps:
                return (True, None)

            for dep in deps:
                if dep not in terminal_states:
                    return (False, f"Blocked: upstream task '{dep}' is still pending/active.")
                state = terminal_states[dep]
                if state != WorkOrderState.ACCEPTED:
                    return (
                        False,
                        f"Dependency failed: upstream task '{dep}' reached non-accepted state '{state.value}'.",
                    )
            return (True, None)

    def get_priority(self, task_id: str) -> int:
        with self._lock:
            return self._priorities.get(task_id, 0)


class MultiRepoConcurrencyManager:
    """Manages concurrent execution across multiple repositories with path locking and limits."""

    def __init__(
        self,
        max_total_concurrency: int = 4,
        max_concurrency_per_repo: int = 2,
        max_queue_depth: int = 32,
    ) -> None:
        self.max_total_concurrency = max_total_concurrency
        self.max_concurrency_per_repo = max_concurrency_per_repo
        self.max_queue_depth = max_queue_depth
        self._lock = threading.RLock()
        self._active_workspaces: Dict[str, IsolatedTaskWorkspace] = {}
        # (repo_id, rel_path) -> work_order_id
        self._locked_paths: Dict[Tuple[str, str], str] = {}
        self._repo_active_counts: Dict[str, int] = {}
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
        with self._lock:
            if not self._admission_enabled:
                raise AdmissionStoppedError("Task admission paused by operator.")
            if current_queue_size >= self.max_queue_depth:
                raise QueueCapacityExceededError(
                    f"Queue capacity of {self.max_queue_depth} exceeded. Backpressure engaged."
                )

    def can_acquire_paths(
        self, repository_id: str, work_order_id: str, authorized_paths: Tuple[Path | str, ...]
    ) -> Tuple[bool, List[str]]:
        """Checks path locks within the specified repository."""
        with self._lock:
            conflicts = []
            for p in authorized_paths:
                rel_p = str(p).lstrip("/")
                key = (repository_id, rel_p)
                if key in self._locked_paths and self._locked_paths[key] != work_order_id:
                    conflicts.append(rel_p)
            return (len(conflicts) == 0, conflicts)

    def can_dispatch_repo(self, repository_id: str) -> bool:
        with self._lock:
            if len(self._active_workspaces) >= self.max_total_concurrency:
                return False
            active_in_repo = self._repo_active_counts.get(repository_id, 0)
            return active_in_repo < self.max_concurrency_per_repo

    def acquire_workspace(
        self, work_order: WorkOrder, base_repo_dir: Path
    ) -> IsolatedTaskWorkspace:
        """Provisions an isolated workspace and locks repository paths."""
        with self._lock:
            repo_id = (
                work_order.intent.target_repo.repository_id
                if getattr(work_order, "intent", None) and getattr(work_order.intent, "target_repo", None)
                else getattr(getattr(work_order, "contract", None), "repository_id", "default")
            )

            if len(self._active_workspaces) >= self.max_total_concurrency:
                raise ConcurrencyError(
                    f"Max total concurrency ({self.max_total_concurrency}) reached."
                )

            active_in_repo = self._repo_active_counts.get(repo_id, 0)
            if active_in_repo >= self.max_concurrency_per_repo:
                raise ConcurrencyError(
                    f"Max concurrency for repository '{repo_id}' ({self.max_concurrency_per_repo}) reached."
                )

            can_acquire, conflicts = self.can_acquire_paths(
                repo_id, work_order.work_order_id, work_order.authorization.authorized_mutation_paths
            )
            if not can_acquire:
                raise ConcurrencyError(
                    f"Path lock conflict in '{repo_id}': paths {conflicts} are currently locked."
                )

            # Copy baseline repository to isolated workspace
            tmp_dir = Path(tempfile.mkdtemp(prefix=f"ws_{repo_id}_{work_order.work_order_id}_"))
            for item in base_repo_dir.iterdir():
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
                self._locked_paths[(repo_id, rel_p)] = work_order.work_order_id
                locked.add(rel_p)

            workspace = IsolatedTaskWorkspace(
                work_order_id=work_order.work_order_id,
                version=work_order.version,
                workspace_dir=tmp_dir,
                locked_paths=locked,
            )
            self._active_workspaces[work_order.work_order_id] = workspace
            self._repo_active_counts[repo_id] = active_in_repo + 1
            return workspace

    def release_workspace(self, work_order_id: str, repository_id: Optional[str] = None) -> None:
        """Cleans up workspace and unsets path locks."""
        with self._lock:
            if work_order_id in self._active_workspaces:
                ws = self._active_workspaces.pop(work_order_id)
                keys_to_del = [k for k, v in self._locked_paths.items() if v == work_order_id]
                for k in keys_to_del:
                    del self._locked_paths[k]

                # Update repo count
                if repository_id and repository_id in self._repo_active_counts:
                    self._repo_active_counts[repository_id] = max(0, self._repo_active_counts[repository_id] - 1)
                else:
                    # Decrement all matching
                    for rid in list(self._repo_active_counts.keys()):
                        if self._repo_active_counts[rid] > 0:
                            self._repo_active_counts[rid] -= 1
                            break

                ws.cleanup()

    def get_active_count(self) -> int:
        with self._lock:
            return len(self._active_workspaces)

    def get_repo_active_count(self, repository_id: str) -> int:
        with self._lock:
            return self._repo_active_counts.get(repository_id, 0)


class MultiRepoEngineeringService:
    """Persistent engineering service coordinating multi-repository work orders and DAG dependencies."""

    def __init__(
        self,
        engine: WorkflowEngine,
        pipeline: HardenedRealRepoPipeline,
        onboarding_manager: RepositoryOnboardingManager,
        concurrency_manager: Optional[MultiRepoConcurrencyManager] = None,
        observability: Optional[ServiceObservability] = None,
        poll_interval_seconds: float = 0.1,
    ) -> None:
        self.engine = engine
        self.pipeline = pipeline
        self.onboarding_manager = onboarding_manager
        self.concurrency = concurrency_manager or MultiRepoConcurrencyManager()
        self.observability = observability or ServiceObservability()
        self.dependency_manager = TaskDependencyManager()
        self.poll_interval = poll_interval_seconds
        self._running = False
        self._terminal_states: Dict[str, WorkOrderState] = {}
        self._registered_repo_dirs: Dict[str, Path] = {}
        self._lock = threading.RLock()

    def register_repository_dir(self, repository_id: str, repo_path: Path) -> None:
        with self._lock:
            self._registered_repo_dirs[repository_id] = repo_path

    def submit_work_order(
        self,
        work_order: WorkOrder,
        dependencies: Optional[List[str]] = None,
        priority: int = 0,
    ) -> None:
        """Submits and registers a work order with explicit dependencies and cycle detection."""
        repo_id = (
            work_order.intent.target_repo.repository_id
            if getattr(work_order, "intent", None) and getattr(work_order.intent, "target_repo", None)
            else getattr(getattr(work_order, "contract", None), "repository_id", None)
        )
        if not repo_id or not self.onboarding_manager.is_onboarded(repo_id):
            raise RepositoryNotOnboardedError(
                f"Cannot submit work order: repository '{repo_id}' is not onboarded."
            )

        # Register task in dependency manager (raises DependencyCycleError if cycle detected)
        self.dependency_manager.register_task(
            work_order.work_order_id, dependencies=dependencies, priority=priority
        )

        # Check queue capacity
        active_count = self.concurrency.get_active_count()
        self.concurrency.check_admission_capacity(active_count)

        # Submit and admit via pipeline
        dec = self.pipeline.submit_and_admit(work_order)
        if not dec.admitted:
            raise WorkflowEngineError(f"Admission rejected: {dec.reason}")

    def execute_task(self, work_order_id: str, version: int = 1) -> WorkOrderState:
        """Executes a task if its dependencies are satisfied; otherwise blocks or cascades failure."""
        with self._lock:
            # Check dependencies
            is_ready, reason = self.dependency_manager.is_ready(work_order_id, self._terminal_states)
            if not is_ready:
                if "Dependency failed" in (reason or ""):
                    # Cascading rejection
                    self.engine.set_terminal_disposition(
                        work_order_id=work_order_id,
                        version=version,
                        disposition="DEPENDENCY_FAILED",
                        state=WorkOrderState.REJECTED,
                    )
                    self._terminal_states[work_order_id] = WorkOrderState.REJECTED
                    return WorkOrderState.REJECTED
                else:
                    raise TaskSchedulingBlockedError(reason or "Task is blocked on dependencies.")

        # Determine target repository
        wo_record = self.engine.get_work_order(work_order_id, version)
        if not wo_record:
            raise WorkflowEngineError(f"Work order {work_order_id} v{version} not found.")

        # Execute lifecycle via hardened pipeline
        state = self.pipeline.execute_lifecycle(work_order_id, version)
        with self._lock:
            self._terminal_states[work_order_id] = state
        return state

    def get_task_state(self, work_order_id: str) -> Optional[WorkOrderState]:
        with self._lock:
            return self._terminal_states.get(work_order_id)
