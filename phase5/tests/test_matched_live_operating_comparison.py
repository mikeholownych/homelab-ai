"""Tests for Matched Live Operating Comparison across 12-Task Cohort."""
import pytest
from autonomous_engineering.eval.live_comparison import (
    MatchedLiveOperatingComparison,
    RoutingTopology,
)


@pytest.fixture
def task_cohort_def():
    task_cohort = [
        "defect_repair_repo",
        "defect_repair_series_repo",
        "heldout_defect_01_off_by_one_paging",
        "multi_file_repo",
        "multi_file_tax_repo",
        "heldout_multifile_01_rate_limiter",
        "test_dev_repo",
        "test_dev_auth_repo",
        "heldout_testdev_01_fencing_invariant",
        "maintainability_repo",
        "maintainability_config_repo",
        "heldout_maintain_01_decouple_notifier",
    ]
    task_classes = {
        "defect_repair_repo": "defect_repair",
        "defect_repair_series_repo": "defect_repair",
        "heldout_defect_01_off_by_one_paging": "defect_repair",
        "multi_file_repo": "multi_file",
        "multi_file_tax_repo": "multi_file",
        "heldout_multifile_01_rate_limiter": "multi_file",
        "test_dev_repo": "test_development",
        "test_dev_auth_repo": "test_development",
        "heldout_testdev_01_fencing_invariant": "test_development",
        "maintainability_repo": "maintainability",
        "maintainability_config_repo": "maintainability",
        "heldout_maintain_01_decouple_notifier": "maintainability",
    }
    return task_cohort, task_classes


def test_matched_live_comparison_cohort(task_cohort_def):
    cohort, classes = task_cohort_def
    evaluator = MatchedLiveOperatingComparison(cohort, classes)
    report = evaluator.run_live_comparison()

    assert report.total_cohort_tasks == 12
    assert len(report.class_summaries) == 12  # 4 classes * 3 topologies

    # Acceptance rates
    assert report.overall_acceptance_by_topology["heterogeneous"] == 1.0
    assert report.overall_acceptance_by_topology["homogeneous"] == 1.0
    assert report.overall_acceptance_by_topology["single_worker"] == 1.0

    # Efficiency comparisons
    hetero_summaries = [s for s in report.class_summaries if s.topology == RoutingTopology.HETEROGENEOUS]
    homo_summaries = [s for s in report.class_summaries if s.topology == RoutingTopology.HOMOGENEOUS]

    total_hetero_time = sum(s.mean_duration_seconds for s in hetero_summaries)
    total_homo_time = sum(s.mean_duration_seconds for s in homo_summaries)

    # Heterogeneous review is faster
    assert total_hetero_time < total_homo_time

    # Heterogeneous review eliminates false positive alarms (0 false findings)
    total_hetero_false = sum(s.false_findings for s in hetero_summaries)
    total_homo_false = sum(s.false_findings for s in homo_summaries)
    assert total_hetero_false == 0
    assert total_homo_false > 0
