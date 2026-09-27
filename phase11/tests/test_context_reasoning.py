import pytest

from autonomous_engineering.optimization.context_reasoning import (
    ContextReasoningOptimizer,
    ContextStrategyType,
)


def test_context_strategy_benchmarking_and_selection():
    optimizer = ContextReasoningOptimizer()
    full_context = "def test_func(): pass\n" * 500
    symbols = ["test_func"]
    deps = ["pytest"]

    benchmarks = optimizer.benchmark_context_strategies(full_context, symbols, deps)
    assert len(benchmarks) == 4

    # Optimal selection ensures evidence completeness >= 95%
    selected = optimizer.select_optimal_strategy(benchmarks, min_evidence_completeness=95.0)
    assert selected == ContextStrategyType.DEPENDENCY_GRAPH

    # If lower completeness allowed, targeted symbols can be selected
    selected_relaxed = optimizer.select_optimal_strategy(benchmarks, min_evidence_completeness=80.0)
    assert selected_relaxed == ContextStrategyType.TARGETED_SYMBOLS
