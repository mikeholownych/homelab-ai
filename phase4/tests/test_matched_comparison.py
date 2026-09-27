"""Tests for 3-Way Matched Comparison Engine."""
import pytest
from autonomous_engineering.eval.candidates import (
    CONTROL_QWEN3_CODER_30B_AWQ,
    CANDIDATE_PHI4_FP8,
)
from autonomous_engineering.eval.comparison import (
    ComparisonTopology,
    MatchedComparisonEvaluator,
)


def test_matched_comparison_execution():
    evaluator = MatchedComparisonEvaluator(
        author_candidate=CONTROL_QWEN3_CODER_30B_AWQ,
        homogeneous_reviewer=CONTROL_QWEN3_CODER_30B_AWQ,
        heterogeneous_reviewer=CANDIDATE_PHI4_FP8,
    )

    tasks = [
        "defect_repair_repo",
        "multi_file_repo",
        "test_dev_repo",
        "maintainability_repo",
        "heldout_defect_01_off_by_one_paging",
        "heldout_multifile_01_rate_limiter",
        "heldout_testdev_01_fencing_invariant",
        "heldout_maintain_01_decouple_notifier",
    ]
    task_classes = {
        "defect_repair_repo": "defect_repair",
        "multi_file_repo": "multi_file",
        "test_dev_repo": "test_development",
        "maintainability_repo": "maintainability",
        "heldout_defect_01_off_by_one_paging": "defect_repair",
        "heldout_multifile_01_rate_limiter": "multi_file",
        "heldout_testdev_01_fencing_invariant": "test_development",
        "heldout_maintain_01_decouple_notifier": "maintainability",
    }

    summaries = evaluator.evaluate_task_cohort(tasks, task_classes)

    assert ComparisonTopology.HOMOGENEOUS_PAIR in summaries
    assert ComparisonTopology.HETEROGENEOUS_PAIR in summaries
    assert ComparisonTopology.SINGLE_WORKER_CONTROL in summaries

    homo = summaries[ComparisonTopology.HOMOGENEOUS_PAIR]
    hetero = summaries[ComparisonTopology.HETEROGENEOUS_PAIR]
    single = summaries[ComparisonTopology.SINGLE_WORKER_CONTROL]

    assert homo.total_tasks == len(tasks)
    assert hetero.total_tasks == len(tasks)
    assert single.total_tasks == len(tasks)

    # Heterogeneous with specialist reviewer should match or exceed homogeneous acceptance
    assert hetero.acceptance_rate >= homo.acceptance_rate
    # Both cooperative pairs should match or beat single worker control
    assert homo.acceptance_rate >= single.acceptance_rate
    assert hetero.acceptance_rate >= single.acceptance_rate

    # Heterogeneous reviewer is faster and consumes fewer tokens
    assert hetero.mean_duration_seconds < homo.mean_duration_seconds
    assert hetero.mean_tokens_consumed < homo.mean_tokens_consumed


def test_topology_superiority_metric():
    evaluator = MatchedComparisonEvaluator(
        author_candidate=CONTROL_QWEN3_CODER_30B_AWQ,
        homogeneous_reviewer=CONTROL_QWEN3_CODER_30B_AWQ,
        heterogeneous_reviewer=CANDIDATE_PHI4_FP8,
    )
    summaries = evaluator.evaluate_task_cohort(["task-1", "task-2"], {"task-1": "defect", "task-2": "feature"})
    hetero = summaries[ComparisonTopology.HETEROGENEOUS_PAIR]
    single = summaries[ComparisonTopology.SINGLE_WORKER_CONTROL]

    # Check comparison operator
    assert hetero.beats_topology(single) or hetero.acceptance_rate >= single.acceptance_rate
