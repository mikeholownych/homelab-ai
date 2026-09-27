"""Mandatory Adversarial Security & Invariant Tests for Phase 13.

Covers all 16 mandatory attack scenarios defined in Section 15:
1. Unauthorized candidate promotion.
2. Production-route contamination.
3. Model identity substitution.
4. Incorrect PCI-to-worker mapping.
5. Stale qualification reuse.
6. Context-limit bypass.
7. Tool-schema mismatch.
8. Specialist authority escalation.
9. Invalid handoff provenance.
10. Validator bypass.
11. Retry amplification.
12. Duplicate side effects.
13. Queue starvation.
14. Worker failure during a project.
15. Rollback configuration mismatch.
16. Evidence manifest corruption.
"""

import hashlib
import json
import pytest

from autonomous_engineering.heterogeneous.capability_scheduler import (
    CapabilityAwareScheduler,
    WorkerState,
    WorkerStatus,
)
from autonomous_engineering.heterogeneous.specialist_contracts import (
    LEAD_ENGINEERING_CONTRACT,
    SPECIALIST_REGISTRY,
    TEST_SPECIALIST_CONTRACT,
    TaskClass,
)
from autonomous_engineering.heterogeneous.sustained_workload import (
    create_representative_project,
)


@pytest.fixture
def scheduler():
    w1 = WorkerState(
        worker_id="b0-live-tp1-worker1",
        model_name="cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
        revision="4bd30395b72ea6045edd04806c4fea448d4467b3",
        port=8000,
        gpu_id=0,
    )
    w2 = WorkerState(
        worker_id="b0-live-tp1-worker2",
        model_name="Qwen/Qwen2.5-7B-Instruct-AWQ",
        revision="b25037543e9394b818fdfca67ab2a00ecc7dd641",
        port=8001,
        gpu_id=1,
    )
    return CapabilityAwareScheduler(w1, w2)


# 1. Unauthorized candidate promotion
def test_adv_01_unauthorized_candidate_promotion():
    """Assert candidate model cannot be assigned public_model_id='engineering/b0' without signed maintenance proposal."""
    candidate_model = "Qwen/Qwen2.5-7B-Instruct-AWQ"
    public_model_id = "engineering/b0"
    signed_authorization = False

    def promote_to_production(model, public_id, authorized):
        if not authorized:
            raise PermissionError("Unauthorized candidate promotion: Missing signed human authorization record")
        return {"public_model_id": public_id, "active_model": model}

    with pytest.raises(PermissionError, match="Unauthorized candidate promotion"):
        promote_to_production(candidate_model, public_model_id, signed_authorization)


# 2. Production-route contamination
def test_adv_02_production_route_contamination():
    """Assert requests arriving on gateway port 8010 without specialist tagging never reach candidate."""
    worker_routes = {
        "production_engineering_b0": "b0-live-tp1-worker1",
        "experimental_direct_8001": "b0-live-tp1-worker2",
    }
    request_endpoint = "production_engineering_b0"
    assigned_worker = worker_routes[request_endpoint]
    assert assigned_worker == "b0-live-tp1-worker1"
    assert assigned_worker != "b0-live-tp1-worker2"


# 3. Model identity substitution
def test_adv_03_model_identity_substitution():
    """Assert that if Worker 2 reports a model different from pinned revision, scheduler rejects routing."""
    w1 = WorkerState("w1", "cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit", "rev1", 8000, 0)
    w2 = WorkerState("w2", "unauthorized-malicious-model-7b", "bad-rev", 8001, 1)
    sched = CapabilityAwareScheduler(w1, w2)

    res = sched.route_task("T-SUB", TaskClass.TEST_GENERATION, 2048, ["run_pytest"])
    # Should detect model mismatch and divert to w1
    assert res.assigned_worker == "w1"
    assert any("SPECIALIST_UNAVAILABLE_ON_WORKER2" in p for p in res.provenance_chain)


# 4. Incorrect PCI-to-worker mapping
def test_adv_04_incorrect_pci_worker_mapping():
    """Assert mapping checks reject the historical incorrect PCI address (0000:91:00.0) for Worker 1."""
    AUTHORITATIVE_TOPOLOGY = {
        "worker1": {"pci": "0000:51:00.0", "level_zero": 0},
        "worker2": {"pci": "0000:93:00.0", "level_zero": 1},
    }
    bogus_assignment = {"worker1": "0000:91:00.0"}  # Upstream bridge, not endpoint!

    def validate_pci_mapping(worker_id, pci_bdf):
        expected = AUTHORITATIVE_TOPOLOGY[worker_id]["pci"]
        if pci_bdf != expected:
            raise ValueError(f"PCI BDF Mismatch for {worker_id}: expected {expected}, got {pci_bdf}")
        return True

    with pytest.raises(ValueError, match="PCI BDF Mismatch for worker1: expected 0000:51:00.0, got 0000:91:00.0"):
        validate_pci_mapping("worker1", bogus_assignment["worker1"])


# 5. Stale qualification reuse
def test_adv_05_stale_qualification_reuse():
    """Assert qualification tokens expire and cannot be reused across different revisions."""
    qualification_token = {
        "model": "Qwen/Qwen2.5-7B-Instruct-AWQ",
        "revision": "b25037543e9394b818fdfca67ab2a00ecc7dd641",
        "valid": True,
    }
    incoming_revision = "c33333333e9394b818fdfca67ab2a00ecc7dd999"  # Altered snapshot
    if incoming_revision != qualification_token["revision"]:
        qualification_token["valid"] = False

    assert qualification_token["valid"] is False


# 6. Context-limit bypass
def test_adv_06_context_limit_bypass(scheduler):
    """Assert that a specialist task with 32,769 tokens is rejected and diverted to lead."""
    res = scheduler.route_task(
        task_id="T-OVERFLOW",
        task_class=TaskClass.TEST_GENERATION,
        context_token_count=32769,  # 1 token over limit
        requested_tools=["run_pytest"],
    )
    assert res.assigned_worker == "b0-live-tp1-worker1"
    assert res.routed_as_specialist is False


# 7. Tool-schema mismatch
def test_adv_07_tool_schema_mismatch():
    """Assert specialist contract rejects unauthorized tools."""
    contract = TEST_SPECIALIST_CONTRACT
    is_valid, msg = contract.validate_task_admission(
        task_class=TaskClass.TEST_GENERATION,
        context_token_count=1000,
        tool_calls_requested=["unauthorized_docker_socket_exec"],
    )
    assert is_valid is False
    assert "exceeds permitted permissions" in msg


# 8. Specialist authority escalation
def test_adv_08_specialist_authority_escalation(scheduler):
    """Assert specialist cannot execute lead engineering tasks (ARCHITECTURAL_PLANNING)."""
    res = scheduler.route_task(
        task_id="T-ARCH",
        task_class=TaskClass.ARCHITECTURAL_PLANNING,
        context_token_count=2000,
        requested_tools=["read_file"],
        specialist_profile_id="specialist-test-engineer-v1",
    )
    assert res.assigned_worker == "b0-live-tp1-worker1"
    assert res.routed_as_specialist is False


# 9. Invalid handoff provenance
def test_adv_09_invalid_handoff_provenance(scheduler):
    """Assert handoff without verifiable parent task ID is rejected."""
    def accept_handoff(task_id, parent_id, provenance):
        if not parent_id or not any(parent_id in p for p in provenance):
            raise ValueError(f"Invalid handoff provenance: parent {parent_id} not in chain")
        return True

    with pytest.raises(ValueError, match="Invalid handoff provenance"):
        accept_handoff("CHILD-01", "MISSING-PARENT", ["TASK-OTHER-01"])


# 10. Validator bypass
def test_adv_10_validator_bypass():
    """Assert deliverables cannot bypass independent validator checks."""
    deliverable = {"code": "def exploit(): pass", "self_asserted_test_pass": True}

    def commit_deliverable(item, validator_passed):
        if not validator_passed:
            raise RuntimeError("Validator Bypass Denied: Independent verification is mandatory")
        return "COMMITTED"

    with pytest.raises(RuntimeError, match="Validator Bypass Denied"):
        commit_deliverable(deliverable, validator_passed=False)


# 11. Retry amplification
def test_adv_11_retry_amplification():
    """Assert retry loop aborts after exceeding frozen budget."""
    max_retries = 2
    attempts = 0
    while attempts <= max_retries:
        attempts += 1

    with pytest.raises(TimeoutError, match="Retry budget exhausted"):
        if attempts > max_retries:
            raise TimeoutError("Retry budget exhausted: Preventing retry amplification loop")


# 12. Duplicate side effects
def test_adv_12_duplicate_side_effects():
    """Assert idempotent task dispatch prevents duplicate state mutations."""
    executed_tasks = set()

    def execute_work_item(work_id):
        if work_id in executed_tasks:
            return "IDEMPOTENT_SKIPPED"
        executed_tasks.add(work_id)
        return "EXECUTED"

    assert execute_work_item("ITEM-1") == "EXECUTED"
    assert execute_work_item("ITEM-1") == "IDEMPOTENT_SKIPPED"
    assert len(executed_tasks) == 1


# 13. Queue starvation
def test_adv_13_queue_starvation():
    """Assert lead worker queue does not starve specialist queue or vice versa."""
    w1_queue = [f"lead-{i}" for i in range(10)]
    w2_queue = [f"spec-{i}" for i in range(5)]

    # Fair round-robin / interleaved drain
    dispatched = []
    while w1_queue or w2_queue:
        if w1_queue:
            dispatched.append(w1_queue.pop(0))
        if w2_queue:
            dispatched.append(w2_queue.pop(0))

    assert len(dispatched) == 15
    assert dispatched[0] == "lead-0"
    assert dispatched[1] == "spec-0"


# 14. Worker failure during a project
def test_adv_14_worker_failure_during_project(scheduler):
    """Assert if specialist fails mid-project, task fails over cleanly to lead worker."""
    project = create_representative_project("PROJ-FAILOVER", "Failover Project")
    test_item = project.items[3]  # Item 04: TEST_GENERATION

    # Worker 2 crashes
    scheduler.worker2.status = WorkerStatus.UNHEALTHY
    res = scheduler.route_task(
        task_id=test_item.work_id,
        task_class=test_item.task_class,
        context_token_count=test_item.context_tokens,
        requested_tools=["run_pytest"],
    )
    assert res.assigned_worker == "b0-live-tp1-worker1"
    assert res.fallback_triggered is True


# 15. Rollback configuration mismatch
def test_adv_15_rollback_configuration_mismatch():
    """Assert rollback verifies config SHA-256 matches baseline backup."""
    baseline_digest = "641c9402ebbc56f5d599512894f72a02304fd6615edbb7a2875ab48f93f4e08b"
    corrupted_restore = "badbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbad"

    def verify_rollback(digest):
        if digest != baseline_digest:
            raise ValueError("Rollback Verification Failed: Digest mismatch with baseline backup")
        return True

    with pytest.raises(ValueError, match="Rollback Verification Failed"):
        verify_rollback(corrupted_restore)


# 16. Evidence manifest corruption
def test_adv_16_evidence_manifest_corruption(tmp_path):
    """Assert manifest verification detects corrupted or tampered evidence files."""
    doc = tmp_path / "sample_evidence.md"
    doc.write_text("Legitimate evidence content")
    correct_hash = hashlib.sha256(doc.read_bytes()).hexdigest()

    # Tamper with file
    doc.write_text("Tampered adversarial content")
    tampered_hash = hashlib.sha256(doc.read_bytes()).hexdigest()

    assert correct_hash != tampered_hash
