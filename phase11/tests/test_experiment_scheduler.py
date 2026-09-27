import pytest

from autonomous_engineering.optimization.experiment_scheduler import (
    ExperimentJob,
    ExperimentState,
    OptimizationExperimentScheduler,
    ProtectedResourceInterferenceError,
    SchedulerConcurrencyError,
)


def test_experiment_submission_and_concurrency_slots():
    scheduler = OptimizationExperimentScheduler(max_system_concurrency=2)
    job1 = ExperimentJob("job-1", "camp-1", "cand-1", ["t1", "t2"], priority=0)
    job2 = ExperimentJob("job-2", "camp-1", "cand-1", ["t3", "t4"], priority=0)
    job3 = ExperimentJob("job-3", "camp-1", "cand-1", ["t5", "t6"], priority=0)

    scheduler.submit_job(job1, target_model="engineering/b0")
    scheduler.submit_job(job2, target_model="engineering/b0")
    scheduler.submit_job(job3, target_model="engineering/b0")

    # Slot 1 and 2 succeed
    assert scheduler.acquire_execution_slot("job-1") is True
    assert scheduler.acquire_execution_slot("job-2") is True

    # Slot 3 exceeds concurrency limit
    with pytest.raises(SchedulerConcurrencyError):
        scheduler.acquire_execution_slot("job-3")

    # Release slot 1
    scheduler.release_execution_slot("job-1", completed_tasks_count=2)
    # Now slot 3 can be acquired
    assert scheduler.acquire_execution_slot("job-3") is True


def test_protected_resident_interference_prevented():
    scheduler = OptimizationExperimentScheduler(protected_resident_model="engineering/b0")
    job = ExperimentJob("job-swap", "camp-1", "candidate-swap-model", ["t1"], priority=0)

    # Attempting to schedule a job that replaces resident model without authorization raises error
    with pytest.raises(ProtectedResourceInterferenceError):
        scheduler.submit_job(job, target_model="unauthorized/other-model")


def test_job_pause_and_cancel():
    scheduler = OptimizationExperimentScheduler()
    job = ExperimentJob("job-ctrl", "camp-1", "cand-1", ["t1"], priority=0)
    scheduler.submit_job(job, target_model="engineering/b0")

    scheduler.pause_job("job-ctrl")
    assert scheduler.get_job_state("job-ctrl") == ExperimentState.PAUSED

    scheduler.cancel_job("job-ctrl")
    assert scheduler.get_job_state("job-ctrl") == ExperimentState.CANCELLED
