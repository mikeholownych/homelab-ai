from pathlib import Path
import pytest

from autonomous_engineering.optimization.corpus import (
    CorpusContaminationError,
    CorpusPartition,
    DuplicateTaskError,
    EngineeringEvaluationCorpusManager,
    EvaluationTask,
    TaskNotFoundError,
)


def test_corpus_initialization_and_partitioning():
    mgr = EngineeringEvaluationCorpusManager(suite_version="1.0.0")
    mgr.build_standard_corpus()

    all_ids = mgr.list_all_task_ids()
    assert len(all_ids) == 12

    dev_tasks = mgr.get_partition_tasks(CorpusPartition.DEVELOPMENT)
    cal_tasks = mgr.get_partition_tasks(CorpusPartition.CALIBRATION)
    assert len(dev_tasks) == 4
    assert len(cal_tasks) == 4

    # Held out partition access with authorization
    held_out = mgr.get_partition_tasks(CorpusPartition.HELD_OUT, allow_held_out=True)
    assert len(held_out) == 4


def test_held_out_quarantine_contamination_protection():
    mgr = EngineeringEvaluationCorpusManager(suite_version="1.0.0")
    mgr.build_standard_corpus()

    # Attempting to access held-out tasks without explicit authorization fails closed
    with pytest.raises(CorpusContaminationError):
        mgr.get_partition_tasks(CorpusPartition.HELD_OUT, allow_held_out=False)

    with pytest.raises(CorpusContaminationError):
        mgr.get_task("task-eval-proj-09", allow_held_out=False)

    # With authorization, succeeds
    task = mgr.get_task("task-eval-proj-09", allow_held_out=True)
    assert task.task_id == "task-eval-proj-09"
    assert task.partition == CorpusPartition.HELD_OUT


def test_duplicate_task_rejected():
    mgr = EngineeringEvaluationCorpusManager()
    t = EvaluationTask(
        task_id="t1",
        workload_class="defect_repair",
        repository_id="repo",
        source_commit="commit",
        title="Title",
        description="Desc",
        authorized_scope=["src/"],
        target_files=[],
        required_specialization="implementation-engineer",
        acceptance_criteria=[],
        resource_budget_tokens=1000,
        expected_disposition="ACCEPTED",
        partition=CorpusPartition.DEVELOPMENT,
        suite_version="1.0.0",
    )
    mgr.register_task(t)
    with pytest.raises(DuplicateTaskError):
        mgr.register_task(t)


def test_corpus_digest_deterministic():
    mgr1 = EngineeringEvaluationCorpusManager()
    mgr1.build_standard_corpus()
    d1 = mgr1.compute_corpus_digest()

    mgr2 = EngineeringEvaluationCorpusManager()
    mgr2.build_standard_corpus()
    d2 = mgr2.compute_corpus_digest()

    assert len(d1) == 64
    assert d1 == d2
