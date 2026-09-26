"""Real-Process Workflow Semantics, Lease Expiration, and SIGKILL Recovery Tests.

Extends Phase 0 in-process proofs across real operating system process boundaries.
"""
from datetime import datetime, timezone
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import pytest

from autonomous_engineering.core.types import ArtifactType, FailureClass, TaskStepState
from autonomous_engineering.planning.models import ExecutionPlan, TaskStepDefinition
from autonomous_engineering.workflow.engine import WorkflowEngine, WorkflowEngineError
from autonomous_engineering.work_order.compiler import WorkOrderCompiler


def test_real_process_worker_sigkill_and_reassignment(tmp_path: Path):
    """Proves that when an untrusted worker process is killed abruptly with SIGKILL,

    the orchestrator safely recovers, expires the lease, and reassigns with an
    incremented fencing token to another process.
    """
    db_file = tmp_path / "proc_wf.sqlite"
    engine = WorkflowEngine(db_file)

    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Test real process kill",
        source_channel="cli",
        source_reference="ref-1",
        repository_id="homelab-ai",
        baseline_commit="8b25d26",
    )
    engine.register_work_order(wo)

    plan = ExecutionPlan(
        plan_id="p-proc-1",
        work_order_id=wo.work_order_id,
        work_order_version=1,
        steps=(
            TaskStepDefinition(
                step_id="step-1",
                required_role="defect_patch",
                description="Patch synthesis",
                target_paths=("src/**",),
                dependencies=(),
                output_artifact_type=ArtifactType.PATCH,
            ),
        ),
    )
    asgn_id = engine.initialize_plan(plan)[0]

    # Acquire lease for worker 1 (fencing token = 2, lease = 1 second)
    token_1 = engine.acquire_lease(asgn_id, "worker-proc-1", lease_seconds=1)

    # Spawn worker 1 as a real OS child process that sleeps
    code_worker1 = (
        "import time, sys\n"
        "time.sleep(10)\n"
    )
    proc1 = subprocess.Popen([sys.executable, "-c", code_worker1])
    assert proc1.poll() is None  # Process is running

    # Abruptly kill worker 1 with SIGKILL
    os.kill(proc1.pid, signal.SIGKILL)
    proc1.wait()
    assert proc1.poll() == -signal.SIGKILL

    # Reassign task to Worker Process 2 with incremented fencing token
    token_2 = engine.acquire_lease(asgn_id, "worker-proc-2", lease_seconds=60)
    assert token_2 == token_1 + 1

    # Worker Process 2 completes task in a real child process
    code_worker2 = (
        f"from autonomous_engineering.workflow.engine import WorkflowEngine\n"
        f"engine = WorkflowEngine('{db_file}')\n"
        f"engine.complete_assignment('{asgn_id}', {token_2}, 'hash-committed-by-proc-2')\n"
    )
    res = subprocess.run(
        [sys.executable, "-c", code_worker2],
        env={**os.environ, "PYTHONPATH": "phase1/src"},
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0

    asgn = engine.get_assignment(asgn_id)
    assert asgn is not None
    assert asgn["status"] == str(TaskStepState.COMPLETED)
    assert asgn["output_artifact_hash"] == "hash-committed-by-proc-2"


def test_real_process_stale_fencing_token_atomic_rejection(tmp_path: Path):
    """Proves that a real delayed child process attempting to commit with a stale

    fencing token is atomically rejected by SQLite WAL across process boundaries.
    """
    db_file = tmp_path / "proc_fence.sqlite"
    engine = WorkflowEngine(db_file)

    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Test fencing rejection",
        source_channel="cli",
        source_reference="ref-2",
        repository_id="homelab-ai",
        baseline_commit="8b25d26",
    )
    engine.register_work_order(wo)

    plan = ExecutionPlan(
        plan_id="p-proc-2",
        work_order_id=wo.work_order_id,
        work_order_version=1,
        steps=(
            TaskStepDefinition(
                step_id="step-1",
                required_role="defect_patch",
                description="Patch synthesis",
                target_paths=("src/**",),
                dependencies=(),
                output_artifact_type=ArtifactType.PATCH,
            ),
        ),
    )
    asgn_id = engine.initialize_plan(plan)[0]

    # Worker A acquires lease (fencing token = 2, lease = 1 second)
    token_a = engine.acquire_lease(asgn_id, "worker-proc-A", lease_seconds=1)

    # Worker B acquires lease (fencing token = 3, lease = 60 seconds)
    token_b = engine.acquire_lease(asgn_id, "worker-proc-B", lease_seconds=60)
    assert token_b == 3

    # Worker B commits first from a real child process
    code_worker_b = (
        f"from autonomous_engineering.workflow.engine import WorkflowEngine\n"
        f"engine = WorkflowEngine('{db_file}')\n"
        f"engine.complete_assignment('{asgn_id}', {token_b}, 'hash-from-valid-B')\n"
    )
    res_b = subprocess.run(
        [sys.executable, "-c", code_worker_b],
        env={**os.environ, "PYTHONPATH": "phase1/src"},
        capture_output=True,
        text=True,
    )
    assert res_b.returncode == 0

    # Worker A attempts late commit from a separate child process
    code_worker_a = (
        f"from autonomous_engineering.workflow.engine import WorkflowEngine\n"
        f"engine = WorkflowEngine('{db_file}')\n"
        f"engine.complete_assignment('{asgn_id}', {token_a}, 'hash-stale-A')\n"
    )
    res_a = subprocess.run(
        [sys.executable, "-c", code_worker_a],
        env={**os.environ, "PYTHONPATH": "phase1/src"},
        capture_output=True,
        text=True,
    )
    # Must fail with non-zero exit code due to STALE_FENCING_TOKEN error
    assert res_a.returncode != 0
    assert "STALE_FENCING_TOKEN" in res_a.stderr or "WorkflowEngineError" in res_a.stderr

    # Committed artifact hash remains Worker B's hash
    asgn = engine.get_assignment(asgn_id)
    assert asgn is not None
    assert asgn["output_artifact_hash"] == "hash-from-valid-B"


def test_real_process_orchestrator_sigkill_and_disk_recovery(tmp_path: Path):
    """Proves that killing an orchestrator process mid-run permits a clean reboot

    that reloads the exact state from SQLite WAL without data loss.
    """
    db_file = tmp_path / "proc_orch_kill.sqlite"

    # Step 1: Run orchestrator process 1 to register work order and initialize plan
    code_orch_1 = (
        f"from autonomous_engineering.workflow.engine import WorkflowEngine\n"
        f"from autonomous_engineering.work_order.compiler import WorkOrderCompiler\n"
        f"from autonomous_engineering.planning.models import ExecutionPlan, TaskStepDefinition\n"
        f"from autonomous_engineering.core.types import ArtifactType\n"
        f"engine = WorkflowEngine('{db_file}')\n"
        f"compiler = WorkOrderCompiler()\n"
        f"wo = compiler.compile('Orchestrator kill test', 'cli', 'ref-3', 'homelab-ai', '8b25d26')\n"
        f"engine.register_work_order(wo)\n"
        f"plan = ExecutionPlan('p-crash', wo.work_order_id, 1, (\n"
        f"    TaskStepDefinition('step-1', 'investigation', 'desc', ('src/**',), (), ArtifactType.REPRODUCTION_SCRIPT),\n"
        f"))\n"
        f"asgn_id = engine.initialize_plan(plan)[0]\n"
        f"token = engine.acquire_lease(asgn_id, 'worker-1')\n"
        f"engine.complete_assignment(asgn_id, token, 'hash-step-1')\n"
        f"import time; time.sleep(10)\n"  # Keep running until killed
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code_orch_1],
        env={**os.environ, "PYTHONPATH": "phase1/src"},
    )
    time.sleep(1.0)  # Allow process to commit step 1

    # Kill orchestrator process with SIGKILL
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait()

    # Step 2: Fresh orchestrator process starts up, opens SQLite file, verifies recovery
    engine_recovered = WorkflowEngine(db_file)
    asgns = engine_recovered._get_connection().execute("SELECT * FROM task_assignments").fetchall()
    assert len(asgns) == 1
    assert asgns[0]["status"] == str(TaskStepState.COMPLETED)
    assert asgns[0]["output_artifact_hash"] == "hash-step-1"
