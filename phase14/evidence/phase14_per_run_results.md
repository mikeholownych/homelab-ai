# Phase 14 Experiment 01: Per-Run Physical Qualification Results

## 1. Physical Campaign Execution Overview

- **Sample Size**: 6 matched engineering project pairs (12 total project executions).
- **Model Configuration**: Homogeneous Dual-30B AWQ (`cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`).
- **Control Configuration (Config B)**: Stage 1 sequential on Worker 1; Stage 2 parallelized; Stage 3 sequential on Worker 1.
- **Candidate Configuration (Config B+)**: Stage 1 Item 01 on Worker 2 (quarantined handoff); Stage 1 Items 02/03 on Worker 1; Stage 2 parallelized; Stage 3 sequential on Worker 1.
- **Temperature**: `0.0` (deterministic decoding).
- **Target Git SHA**: `a8c3b6a1a4c27f391f28ebdf5a74c1bfd1d148ce`.

## 2. Configuration B (Control) Per-Run Results

| Project ID | Archetype | Turnaround (s) | W1 Demand (s) | W2 Demand (s) | W2 Idle (s) | Accepted |
|---|---|---|---|---|---|---|
| `proj-api-01` | API Refactoring | 196.89 | 196.89 | 81.69 | 115.20 | True |
| `proj-sec-02` | Security Remediation | 196.47 | 196.47 | 81.84 | 114.64 | True |
| `proj-schema-03` | Schema Contract | 196.21 | 196.21 | 81.26 | 114.95 | True |
| `proj-worker-04` | Async Worker | 196.12 | 196.11 | 81.50 | 114.62 | True |
| `proj-db-05` | Database Migration | 197.28 | 197.28 | 82.09 | 115.19 | True |
| `proj-obs-06` | Observability Gateway | 200.77 | 200.76 | 81.82 | 118.95 | True |

**Mean Turnaround**: 197.29s | **Mean W1 Demand**: 197.28s | **Throughput**: 18.25 proj/hr

## 3. Configuration B+ (Candidate) Per-Run Results

| Project ID | Archetype | Turnaround (s) | W1 Demand (s) | W2 Demand (s) | W2 Idle (s) | Accepted |
|---|---|---|---|---|---|---|
| `proj-api-01` | API Refactoring | 198.09 | 169.59 | 110.48 | 87.61 | True |
| `proj-sec-02` | Security Remediation | 196.95 | 168.78 | 110.02 | 86.93 | True |
| `proj-schema-03` | Schema Contract | 196.65 | 168.34 | 109.73 | 86.91 | True |
| `proj-worker-04` | Async Worker | 196.59 | 168.26 | 110.25 | 86.34 | True |
| `proj-db-05` | Database Migration | 196.76 | 168.52 | 109.92 | 86.84 | True |
| `proj-obs-06` | Observability Gateway | 196.02 | 167.85 | 109.72 | 86.30 | True |

**Mean Turnaround**: 196.84s | **Mean W1 Demand**: 168.56s | **Throughput**: 18.29 proj/hr

## 4. Stage-by-Stage Latency Breakdown (Averages)

| Configuration | Stage 1 (s) | Stage 2 Concurrent (s) | Stage 3 Lead (s) | Total Elapsed (s) |
|---|---|---|---|---|
| **Config B (Control)** | 99.21 | 41.57 | 56.51 | 197.29 |
| **Config B+ (Candidate)** | 98.68 | 41.52 | 56.65 | 196.84 |
