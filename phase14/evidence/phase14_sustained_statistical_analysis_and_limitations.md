# Phase 14 Experiment 02: Statistical Analysis, Uncertainty, and Limitations

## 1. Statistical Confidence and Hypothesis Testing

- **Offered Workload Sample**: 20 total physical project executions across two distinct arrival regimes (8 projects in Regime 1, 12 projects in Regime 2).
- **Regime 2 Sustained Throughput Difference**: **+1.64 proj/hr (+10.17%)**.
- **P95 Latency Reduction**: **-119.62 seconds**.
- **Acceptance Rate**: 100% (20/20 projects accepted across all gates).

## 2. Scope and Operational Limitations

1. **Bounded Arrival Regimes**: Evaluated at $\lambda = 12.0$ proj/hr (sub-saturated) and $\lambda = 19.5$ proj/hr (capacity stress boundary). Workloads far beyond $\lambda = 22.0$ proj/hr will saturate Worker 1 in both configurations.
2. **Model Invariance**: Validated specifically on the homogeneous dual-30B deployment (`cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`). Heterogeneous deployments (e.g. 7B on Worker 2) require separate qualification under Phase 13 contracts.
3. **Queue Scheduling**: Evaluated under FIFO queue discipline with bounded buffer ($Q_{\max}=10$). Priority or preemption queueing models were not tested in this experiment.

## 3. Operational Relevance Assessment

The observed sustained throughput increase exceeds the threshold for operational relevance (+10%), establishing that rebalancing Item 01 investigation to Worker 2 provides a real, measurable throughput expansion under sustained arrivals without degrading acceptance or system stability.
