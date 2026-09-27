"""Tests for Human Interface Adapter and CLI."""
import json
from pathlib import Path
import pytest
import tempfile

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.core.types import (
    AmbiguityStatus,
    ArtifactType,
    FailureClass,
    RevisionKind,
    WorkOrderState,
)
from autonomous_engineering.interface.adapter import HumanInterfaceAdapter
from autonomous_engineering.interface.cli import run_cli
from autonomous_engineering.workflow.engine import WorkflowEngine, WorkflowEngineError
from autonomous_engineering.work_order.compiler import WorkOrderCompiler
from autonomous_engineering.work_order.models import AcceptanceCriterion


@pytest.fixture
def test_env():
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        db_path = tmp_path / "test_engine.sqlite"
        art_path = tmp_path / "artifacts"
        engine = WorkflowEngine(db_path)
        store = ArtifactStore(art_path)
        adapter = HumanInterfaceAdapter(engine, store)
        yield {
            "tmp_path": tmp_path,
            "db_path": db_path,
            "art_path": art_path,
            "engine": engine,
            "store": store,
            "adapter": adapter,
        }


def test_cli_submit_inspect_status(test_env):
    db = str(test_env["db_path"])
    art = str(test_env["art_path"])

    # 1. Test CLI submit
    ret = run_cli([
        "--db", db,
        "--artifacts", art,
        "submit",
        "--prompt", "Fix edge cases in stats_utils.py",
        "--repo", "homelab-ai",
        "--commit", "8b25d26",
        "--scope", "src/stats_utils.py",
        "--test", "tests/test_stats_utils.py",
    ])
    assert ret == 0

    # Retrieve work order id from engine
    with test_env["engine"]._get_connection() as conn:
        row = conn.execute("SELECT work_order_id, version FROM work_orders").fetchone()
        wo_id = row["work_order_id"]
        v = row["version"]

    # 2. Test CLI inspect
    ret_inspect = run_cli([
        "--db", db,
        "--artifacts", art,
        "inspect", wo_id,
        "--version", str(v),
    ])
    assert ret_inspect == 0

    # 3. Test CLI status
    ret_status = run_cli([
        "--db", db,
        "--artifacts", art,
        "status", wo_id,
        "--version", str(v),
    ])
    assert ret_status == 0

    # 4. Test CLI status --json
    ret_json = run_cli([
        "--db", db,
        "--artifacts", art,
        "status", wo_id,
        "--version", str(v),
        "--json",
    ])
    assert ret_json == 0


def test_cli_pause_resume_cancel(test_env):
    db = str(test_env["db_path"])
    art = str(test_env["art_path"])
    engine: WorkflowEngine = test_env["engine"]
    adapter: HumanInterfaceAdapter = test_env["adapter"]

    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Test pause resume cancel",
        source_channel="test",
        source_reference="ref-1",
        repository_id="repo-1",
        baseline_commit="c1",
        proposed_mutation_paths=["src/foo.py"],
        acceptance_criteria=[
            AcceptanceCriterion("c1", "test", "pytest", "tests/test_foo.py")
        ],
    )
    adapter.submit_work_order(wo)
    wo_id = wo.work_order_id
    v = wo.version

    # Set state to EXECUTING so it can be paused
    with engine._get_connection() as conn:
        conn.execute("UPDATE work_orders SET state = 'EXECUTING' WHERE work_order_id = ?", (wo_id,))
        conn.commit()

    # CLI pause
    ret_pause = run_cli(["--db", db, "--artifacts", art, "pause", wo_id, "--version", str(v)])
    assert ret_pause == 0
    st = adapter.query_status(wo_id, v)
    assert st.state == WorkOrderState.PAUSED

    # CLI resume
    ret_resume = run_cli(["--db", db, "--artifacts", art, "resume", wo_id, "--version", str(v)])
    assert ret_resume == 0
    st = adapter.query_status(wo_id, v)
    assert st.state == WorkOrderState.EXECUTING

    # CLI cancel
    ret_cancel = run_cli(["--db", db, "--artifacts", art, "cancel", wo_id, "--version", str(v), "--reason", "Test cancel"])
    assert ret_cancel == 0
    st = adapter.query_status(wo_id, v)
    assert st.state == WorkOrderState.CANCELLED
    assert st.terminal_disposition == "CANCELLED"


def test_adapter_clarify_and_revision(test_env):
    adapter: HumanInterfaceAdapter = test_env["adapter"]
    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Do something ambiguous with math",
        source_channel="test",
        source_reference="ref-ambig",
        repository_id="repo-1",
        baseline_commit="c1",
        proposed_mutation_paths=["src/math.py"],
        acceptance_criteria=[
            AcceptanceCriterion("c1", "test", "pytest", "tests/test_math.py")
        ],
    )
    adapter.submit_work_order(wo)
    wo_id = wo.work_order_id

    # Add an ambiguity to inspect
    insp = adapter.inspect_work_order(wo_id, 1)
    assert insp is not None
    assert insp["work_order_id"] == wo_id

    # Test revise_work_order
    receipt = adapter.revise_work_order(
        work_order_id=wo_id,
        version=1,
        revision_kind=RevisionKind.SCOPE_EXPANSION,
        change_reason="Add new module to scope",
        author="operator",
        updated_paths=["src/math.py", "src/helpers.py"],
    )
    assert receipt.version == 2
    assert receipt.work_order_id == wo_id

    # Previous version must be SUPERSEDED
    old_st = adapter.query_status(wo_id, 1)
    assert old_st.state == WorkOrderState.SUPERSEDED

    # New version must be DRAFT and inspectable
    new_insp = adapter.inspect_work_order(wo_id, 2)
    assert new_insp["version"] == 2
    assert "src/helpers.py" in new_insp["authorized_mutation_paths"]


def test_artifact_delivery_and_tamper_detection(test_env):
    adapter: HumanInterfaceAdapter = test_env["adapter"]
    store: ArtifactStore = test_env["store"]
    engine: WorkflowEngine = test_env["engine"]

    compiler = WorkOrderCompiler()
    wo = compiler.compile(
        raw_text="Delivery test",
        source_channel="test",
        source_reference="ref-deliv",
        repository_id="repo-1",
        baseline_commit="c1",
        proposed_mutation_paths=["src/foo.py"],
        acceptance_criteria=[
            AcceptanceCriterion("c1", "test", "pytest", "tests/test_foo.py")
        ],
    )
    adapter.submit_work_order(wo)
    wo_id = wo.work_order_id

    # Store a valid patch artifact
    patch_text = (
        "diff --git a/src/foo.py b/src/foo.py\n"
        "--- a/src/foo.py\n"
        "+++ b/src/foo.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-def old(): pass\n"
        "+def new(): return True\n"
    )
    art_rec = store.put(
        content=patch_text,
        artifact_type=ArtifactType.PATCH,
        work_order_id=wo_id,
        work_order_version=1,
        step_id="step-patch",
        producing_worker_id="worker-b65-0",
        producing_profile_hash="prof-b65-0",
        capability_token_id="tok-deliv-1",
    )

    # Initialize assignment in engine and mark completed
    with engine._get_connection() as conn:
        conn.execute(
            """
            INSERT INTO task_assignments (
                assignment_id, work_order_id, work_order_version, step_id,
                required_role, status, fencing_token, output_artifact_hash,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            """,
            ("asgn-1", wo_id, 1, "step-patch", "defect_patch", "COMPLETED", 1, art_rec.artifact_hash),
        )
        conn.commit()

    engine.set_terminal_disposition(wo_id, 1, "ACCEPTED", WorkOrderState.ACCEPTED)

    # 1. Normal delivery retrieval
    bundle = adapter.deliver_accepted_artifact(wo_id, 1)
    assert bundle["work_order_id"] == wo_id
    assert bundle["deliverable"]["artifact_hash"] == art_rec.artifact_hash
    assert "src/foo.py" in bundle["deliverable"]["changed_files"]
    assert "git apply --check" in bundle["local_inspection"]["check_command"]

    # 2. Tamper detection test: corrupt artifact content on disk
    artifact_file = store._path_for(art_rec.artifact_hash)
    artifact_file.write_bytes(b"tampered content corrupted by adversary")

    with pytest.raises(WorkflowEngineError) as exc_info:
        adapter.deliver_accepted_artifact(wo_id, 1)
    assert exc_info.value.failure_class == FailureClass.ARTIFACT_TAMPERED
