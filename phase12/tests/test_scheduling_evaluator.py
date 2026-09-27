import pytest
from autonomous_engineering.physical_qualification.scheduling_evaluator import (
    HeterogeneousSchedulingEvaluator,
    DeploymentTopology,
)


def test_topology_a_homogeneous():
    evaluator = HeterogeneousSchedulingEvaluator()
    res = evaluator.evaluate_topology_a_homogeneous(100)
    assert res.topology == DeploymentTopology.TOPOLOGY_A_HOMOGENEOUS_CONTROL
    assert res.worker_1_model == res.worker_2_model
    assert res.tasks_per_hour > 100.0
    assert res.specialist_handoff_overhead_sec == 0.0
    assert res.gpu0_memory_utilization_pct > 80.0
    assert res.gpu1_memory_utilization_pct > 80.0


def test_topology_b_heterogeneous_specialist():
    evaluator = HeterogeneousSchedulingEvaluator()
    res = evaluator.evaluate_topology_b_heterogeneous_specialist(100)
    assert res.topology == DeploymentTopology.TOPOLOGY_B_HETEROGENEOUS_SPECIALIST
    assert res.worker_2_model == "Qwen/Qwen2.5-7B-Instruct-AWQ"
    # Cost efficiency and throughput higher than baseline
    assert res.cost_efficiency_score > 1.2
    assert res.gpu1_memory_utilization_pct < 30.0  # Low memory usage
    assert res.specialist_handoff_overhead_sec > 0.0  # Handoff overhead tracked


def test_topology_c_cooperative_long_context():
    evaluator = HeterogeneousSchedulingEvaluator()
    res = evaluator.evaluate_topology_c_cooperative_long_context(100)
    assert res.topology == DeploymentTopology.TOPOLOGY_C_COOPERATIVE_LONG_CONTEXT
    res_a = evaluator.evaluate_topology_a_homogeneous(100)
    assert res.tasks_per_hour < res_a.tasks_per_hour

